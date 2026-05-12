"""Chess.com Public API client.

The Chess.com Public Data API is documented here:
    https://www.chess.com/news/view/published-data-api

What this client demonstrates:
  - Strict User-Agent header (Chess.com rejects requests without one).
  - Retry with exponential backoff on 5xx and 429 responses.
  - Native handling of the `Retry-After` header for rate limits.
  - Streaming iteration over month archives so we don't load
    everything into memory.
  - Typed dataclasses for player + game so call sites get type help.
  - Time-class filtering (Bullet/Blitz/Rapid/Daily) — a first-class
    Chess.com concept that matters for blunder analysis.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional

import requests

from config import config

log = logging.getLogger(__name__)

BASE = "https://api.chess.com/pub"

# Chess.com classifies all games into one of these time classes.
# Surfacing this lets the caller filter — important because blunder
# patterns differ wildly between Bullet (time pressure) and Daily (deep thought).
TimeClass = str  # "bullet" | "blitz" | "rapid" | "daily"
VALID_TIME_CLASSES = {"bullet", "blitz", "rapid", "daily"}


class ChessComError(Exception):
    """Base exception for Chess.com API failures."""


class PlayerNotFound(ChessComError):
    """Returned when the username does not exist on Chess.com."""


@dataclass(frozen=True)
class PlayerProfile:
    username: str
    player_id: Optional[int]
    name: Optional[str]
    country: Optional[str]
    joined: Optional[int]   # unix timestamp
    last_online: Optional[int]
    status: Optional[str]


@dataclass(frozen=True)
class PlayerStats:
    """Subset of /pub/player/{username}/stats we actually use."""
    bullet_rating: Optional[int]
    blitz_rating: Optional[int]
    rapid_rating: Optional[int]
    daily_rating: Optional[int]

    def best_rating(self) -> Optional[int]:
        """Highest current rating across time classes — used as a coarse
        skill anchor when calibrating blunder thresholds."""
        ratings = [r for r in (self.bullet_rating, self.blitz_rating,
                               self.rapid_rating, self.daily_rating)
                   if r is not None]
        return max(ratings) if ratings else None


@dataclass(frozen=True)
class ArchivedGame:
    """One game from a monthly archive."""
    url: str
    pgn: str
    time_class: TimeClass
    time_control: str
    end_time: Optional[int]
    rated: bool
    white_username: str
    black_username: str
    white_rating: Optional[int]
    black_rating: Optional[int]
    result: Optional[str]


class ChessComClient:
    """Thin, well-behaved wrapper over the Chess.com Public API.

    Use as a context manager so the underlying requests Session is cleaned up:

        with ChessComClient() as client:
            stats = client.get_stats("magnuscarlsen")
            for game in client.iter_games("magnuscarlsen", max_games=50):
                ...
    """

    def __init__(
        self,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
        retry_max: Optional[int] = None,
        retry_backoff: Optional[float] = None,
        session: Optional[requests.Session] = None,
    ):
        self.user_agent = user_agent or config.chesscom_user_agent
        self.timeout = timeout or config.chesscom_request_timeout
        self.retry_max = retry_max or config.chesscom_retry_max
        self.retry_backoff = retry_backoff or config.chesscom_retry_backoff
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })

    # ------- context manager -------
    def __enter__(self) -> "ChessComClient":
        return self

    def __exit__(self, *args) -> None:
        self.session.close()

    # ------- request layer -------
    def _get(self, path: str) -> dict:
        """GET a path under /pub with retries and rate-limit handling."""
        url = f"{BASE}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(self.retry_max + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                last_exc = e
                wait = self.retry_backoff ** attempt
                log.warning("Network error on %s (attempt %d): %s — retrying in %.1fs",
                            path, attempt + 1, e, wait)
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                raise PlayerNotFound(f"Not found: {path}")

            if resp.status_code == 429:
                # Chess.com tells us how long to wait via Retry-After
                retry_after = float(resp.headers.get("Retry-After", "5"))
                log.warning("Rate-limited on %s — waiting %.1fs", path, retry_after)
                time.sleep(retry_after)
                continue

            if 500 <= resp.status_code < 600:
                wait = self.retry_backoff ** attempt
                log.warning("Server %d on %s (attempt %d) — retrying in %.1fs",
                            resp.status_code, path, attempt + 1, wait)
                time.sleep(wait)
                continue

            if not resp.ok:
                raise ChessComError(f"{resp.status_code} on {path}: {resp.text[:200]}")

            return resp.json()

        raise ChessComError(
            f"Gave up on {path} after {self.retry_max + 1} attempts: {last_exc}"
        )

    # ------- public methods -------
    def get_profile(self, username: str) -> PlayerProfile:
        data = self._get(f"/player/{username.lower()}")
        return PlayerProfile(
            username=data.get("username", username),
            player_id=data.get("player_id"),
            name=data.get("name"),
            country=data.get("country", "").rsplit("/", 1)[-1] or None,
            joined=data.get("joined"),
            last_online=data.get("last_online"),
            status=data.get("status"),
        )

    def get_stats(self, username: str) -> PlayerStats:
        data = self._get(f"/player/{username.lower()}/stats")

        def _rating(key: str) -> Optional[int]:
            return (data.get(key, {}) or {}).get("last", {}).get("rating")

        return PlayerStats(
            bullet_rating=_rating("chess_bullet"),
            blitz_rating=_rating("chess_blitz"),
            rapid_rating=_rating("chess_rapid"),
            daily_rating=_rating("chess_daily"),
        )

    def get_archives(self, username: str) -> List[str]:
        """List of monthly-archive URLs, oldest first."""
        return self._get(f"/player/{username.lower()}/games/archives")["archives"]

    def iter_games(
        self,
        username: str,
        max_games: int = 50,
        time_classes: Optional[List[TimeClass]] = None,
        rated_only: bool = False,
    ) -> Iterator[ArchivedGame]:
        """Yield games newest-first.

        Args:
            username: Chess.com handle (case insensitive).
            max_games: stop after this many games yielded.
            time_classes: if provided, only yield games matching these
                          (e.g. ["blitz", "rapid"]).
            rated_only: skip unrated games.
        """
        username_lc = username.lower()
        if time_classes:
            invalid = set(time_classes) - VALID_TIME_CLASSES
            if invalid:
                raise ValueError(
                    f"Unknown time_class(es): {invalid}. Valid: {VALID_TIME_CLASSES}"
                )
            time_classes = [t.lower() for t in time_classes]

        archives = self.get_archives(username_lc)
        if not archives:
            log.info("No archives for %s", username_lc)
            return

        yielded = 0
        # Newest months first; within a month newest games first
        for archive_url in reversed(archives):
            if yielded >= max_games:
                break
            month_path = archive_url.replace(BASE, "")
            log.info("Fetching archive %s", month_path)
            try:
                data = self._get(month_path)
            except ChessComError as e:
                log.warning("Skipping archive %s: %s", month_path, e)
                continue

            for g in reversed(data.get("games", [])):
                if yielded >= max_games:
                    break

                tc = (g.get("time_class") or "").lower()
                if time_classes and tc not in time_classes:
                    continue
                if rated_only and not g.get("rated"):
                    continue
                pgn = g.get("pgn")
                if not pgn:
                    continue

                white = g.get("white", {}) or {}
                black = g.get("black", {}) or {}

                yield ArchivedGame(
                    url=g.get("url", ""),
                    pgn=pgn,
                    time_class=tc,
                    time_control=g.get("time_control", ""),
                    end_time=g.get("end_time"),
                    rated=bool(g.get("rated", False)),
                    white_username=white.get("username", ""),
                    black_username=black.get("username", ""),
                    white_rating=white.get("rating"),
                    black_rating=black.get("rating"),
                    result=white.get("result"),
                )
                yielded += 1

            # Tiny pause between archive calls so we never look greedy
            time.sleep(0.3)

        log.info("Yielded %d games for %s", yielded, username_lc)
