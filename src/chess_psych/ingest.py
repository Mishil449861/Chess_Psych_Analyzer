"""Ingest games into the local database.

Primary path: Chess.com Public API (via chesscom_client.ChessComClient).
Fallback path: Lichess streaming PGN endpoint (no client, just one function).

The Chess.com path is the hero: it surfaces time_class, fetches stats to
populate per-time-class ratings, and respects rate limits via the client.
"""
from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import chess
import chess.pgn
import requests

from .config import config
from .chesscom_client import ChessComClient, PlayerNotFound
from .db import get_conn, get_or_create_user, init_db
from .features import parse_time_control
from .stockfish_pool import StockfishPool

log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    fetched: int = 0
    ingested: int = 0
    skipped_duplicate: int = 0
    skipped_unrecognized: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "ingested": self.ingested,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_unrecognized": self.skipped_unrecognized,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Comment parsers — Lichess `[%eval ...]` and `[%clk ...]` annotations
# ---------------------------------------------------------------------------
_EVAL_RE = re.compile(r"\[%eval\s+([+-]?[\d.]+|#[+-]?\d+)\]")
_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")


def parse_eval_comment(comment: str) -> Optional[int]:
    """Return centipawns (White POV) from a `[%eval ...]` comment, or None."""
    if not comment:
        return None
    m = _EVAL_RE.search(comment)
    if not m:
        return None
    val = m.group(1)
    if val.startswith("#"):
        return 10000 if int(val[1:]) > 0 else -10000
    try:
        return int(float(val) * 100)
    except ValueError:
        return None


def parse_clock_comment(comment: str) -> Optional[float]:
    """Return seconds remaining from a `[%clk H:MM:SS]` comment."""
    if not comment:
        return None
    m = _CLK_RE.search(comment)
    if not m:
        return None
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _safe_int(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, "", "?") else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Per-game ingestion (used by both Chess.com and Lichess paths)
# ---------------------------------------------------------------------------
def ingest_pgn(
    conn,
    user_id: int,
    user_username: str,
    pgn: str,
    *,
    external_id: Optional[str] = None,
    time_class: Optional[str] = None,
    stockfish: Optional[StockfishPool] = None,
    eval_depth: int = 12,
) -> Optional[int]:
    """Parse one PGN, store game + moves. Returns game_id or None on skip.

    Strategy for evals:
      1. Prefer inline `[%eval ...]` comments (free, accurate).
      2. Fall back to Stockfish at `eval_depth` when given.
      3. Leave eval_after NULL otherwise.
    """
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return None

    headers = game.headers
    white = headers.get("White", "")
    black = headers.get("Black", "")

    user_lc = user_username.lower()
    if white.lower() == user_lc:
        user_color = "white"
        user_rating = headers.get("WhiteElo")
        opp_rating = headers.get("BlackElo")
    elif black.lower() == user_lc:
        user_color = "black"
        user_rating = headers.get("BlackElo")
        opp_rating = headers.get("WhiteElo")
    else:
        log.debug("User %s not in game (%s vs %s)", user_username, white, black)
        return None

    if not external_id:
        external_id = "|".join([
            headers.get("Site", ""), headers.get("Date", ""),
            headers.get("Round", ""), white, black,
        ])

    existing = conn.execute(
        "SELECT id FROM games WHERE user_id = ? AND external_id = ?",
        (user_id, external_id),
    ).fetchone()
    if existing:
        return None

    cur = conn.execute(
        """INSERT INTO games
             (user_id, external_id, user_color, result, eco, opening_name,
              user_rating, opponent_rating, time_class, time_control,
              played_at, pgn)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            user_id, external_id, user_color,
            headers.get("Result"),
            headers.get("ECO"),
            headers.get("Opening") or headers.get("OpeningName"),
            _safe_int(user_rating),
            _safe_int(opp_rating),
            time_class,
            headers.get("TimeControl"),
            headers.get("UTCDate") or headers.get("Date"),
            pgn,
        ),
    )
    game_id = cur.lastrowid

    board = game.board()
    node = game
    ply = 0
    last_eval_white = 0
    prev_clk = {"white": None, "black": None}
    initial_seconds, increment_seconds = parse_time_control(headers.get("TimeControl"))

    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        ply += 1
        side = "white" if board.turn == chess.WHITE else "black"

        fen_before = board.fen()
        try:
            san = board.san(move)
        except (AssertionError, ValueError) as e:
            log.warning("Bad SAN at ply %d of game %d: %s", ply, game_id, e)
            break
        uci = move.uci()

        eval_after_white = parse_eval_comment(next_node.comment)
        clk_remaining = parse_clock_comment(next_node.comment)

        board.push(move)
        fen_after = board.fen()

        if eval_after_white is None and stockfish is not None:
            try:
                eval_after_white = stockfish.analyse(board, depth=eval_depth)
            except Exception as e:
                log.warning("Stockfish failed at ply %d: %s", ply, e)
                eval_after_white = None

        time_spent: Optional[float] = None
        if clk_remaining is not None:
            previous_clock = prev_clk[side]
            if previous_clock is None:
                previous_clock = initial_seconds
            if previous_clock is not None:
                ts = previous_clock + increment_seconds - clk_remaining
            else:
                ts = None
            if ts is not None and ts >= 0:
                time_spent = ts
        if clk_remaining is not None:
            prev_clk[side] = clk_remaining

        conn.execute(
            """INSERT INTO moves
                 (game_id, ply, san, uci, fen_before, fen_after,
                  eval_before, eval_after, time_spent, clock_remaining, side)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (game_id, ply, san, uci, fen_before, fen_after,
             last_eval_white, eval_after_white, time_spent, clk_remaining, side),
        )

        if eval_after_white is not None:
            last_eval_white = eval_after_white

        node = next_node

    return game_id


# ---------------------------------------------------------------------------
# Chess.com pipeline (primary)
# ---------------------------------------------------------------------------
def ingest_chesscom_user(
    username: str,
    *,
    max_games: int = 50,
    time_classes: Optional[List[str]] = None,
    rated_only: bool = True,
    use_stockfish: bool = True,
    eval_depth: Optional[int] = None,
    db_path: Optional[Path] = None,
    progress_every: int = 5,
) -> IngestStats:
    """Fetch + ingest Chess.com games for a user.

    Args:
        username: Chess.com handle (case insensitive).
        max_games: cap on games to fetch.
        time_classes: filter, e.g. ["blitz", "rapid"]. None = all.
        rated_only: skip unrated games.
        use_stockfish: if False, only inline evals will be used (Chess.com
                       PGNs usually lack them, so most evals will be NULL).
        eval_depth: Stockfish search depth (defaults to config value).
        db_path: override config DB location (useful for tests).
        progress_every: log every N games fetched.

    Returns:
        IngestStats with counts.
    """
    init_db(db_path)
    stats = IngestStats()
    eval_depth = eval_depth or config.stockfish_depth

    sf: Optional[StockfishPool] = None
    if use_stockfish:
        sf = StockfishPool(
            threads=config.stockfish_threads,
            hash_mb=config.stockfish_hash_mb,
        )

    try:
        if sf:
            sf.start()

        with ChessComClient() as client:
            # Resolve profile + per-time-class ratings up front
            try:
                profile = client.get_profile(username)
                pstats = client.get_stats(username)
            except PlayerNotFound:
                raise ValueError(f"Chess.com user '{username}' not found.")

            best = pstats.best_rating()
            log.info("Chess.com user %s (player_id=%s, best rating=%s)",
                     profile.username, profile.player_id, best)

            with get_conn(db_path) as conn:
                user_id = get_or_create_user(
                    conn, profile.username, "chess.com",
                    rating=best,
                    bullet=pstats.bullet_rating,
                    blitz=pstats.blitz_rating,
                    rapid=pstats.rapid_rating,
                    daily=pstats.daily_rating,
                )

                games_iter = client.iter_games(
                    profile.username,
                    max_games=max_games,
                    time_classes=time_classes,
                    rated_only=rated_only,
                )

                for game in games_iter:
                    stats.fetched += 1
                    try:
                        gid = ingest_pgn(
                            conn, user_id, profile.username, game.pgn,
                            external_id=game.url,
                            time_class=game.time_class,
                            stockfish=sf,
                            eval_depth=eval_depth,
                        )
                        if gid:
                            stats.ingested += 1
                        else:
                            stats.skipped_duplicate += 1

                        # Periodically commit so a crash doesn't lose everything
                        if stats.ingested and stats.ingested % 10 == 0:
                            conn.commit()
                    except Exception as e:
                        stats.errors += 1
                        log.exception("Ingest failed for game %s: %s", game.url, e)

                    if stats.fetched % progress_every == 0:
                        log.info("Progress: fetched=%d ingested=%d skipped=%d errors=%d",
                                 stats.fetched, stats.ingested,
                                 stats.skipped_duplicate, stats.errors)
    finally:
        if sf:
            sf.close()

    log.info("Done. %s", stats.to_dict())
    return stats


# ---------------------------------------------------------------------------
# Lichess pipeline (fallback)
# ---------------------------------------------------------------------------
def _lichess_pgn(username: str, max_games: int) -> str:
    url = f"https://lichess.org/api/games/user/{username}"
    params = {
        "max": max_games, "evals": "true", "clocks": "true",
        "opening": "true", "pgnInJson": "false",
    }
    headers = {
        "Accept": "application/x-chess-pgn",
        "User-Agent": config.chesscom_user_agent,  # same UA convention
    }
    r = requests.get(url, params=params, headers=headers, timeout=120)
    r.raise_for_status()
    return r.text


def ingest_lichess_user(
    username: str,
    *,
    max_games: int = 50,
    use_stockfish: bool = True,
    eval_depth: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> IngestStats:
    """Fallback Lichess ingestion. Lichess PGNs have inline evals so Stockfish
    is often unnecessary."""
    init_db(db_path)
    stats = IngestStats()
    eval_depth = eval_depth or config.stockfish_depth

    sf = StockfishPool() if use_stockfish else None
    try:
        if sf:
            sf.start()

        pgn_text = _lichess_pgn(username, max_games)
        pgn_io = io.StringIO(pgn_text)

        with get_conn(db_path) as conn:
            user_id = get_or_create_user(conn, username, "lichess")
            while True:
                game = chess.pgn.read_game(pgn_io)
                if game is None:
                    break
                stats.fetched += 1
                try:
                    gid = ingest_pgn(
                        conn, user_id, username, str(game),
                        external_id=game.headers.get("Site"),
                        time_class=None,
                        stockfish=sf,
                        eval_depth=eval_depth,
                    )
                    if gid:
                        stats.ingested += 1
                    else:
                        stats.skipped_duplicate += 1
                except Exception as e:
                    stats.errors += 1
                    log.exception("Lichess ingest error: %s", e)
    finally:
        if sf:
            sf.close()

    return stats
