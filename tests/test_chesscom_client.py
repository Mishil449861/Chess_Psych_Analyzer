"""Integration tests for ChessComClient.

These tests stub out `requests.Session` so we don't hit the real API.
That's the right boundary: we want to test our retry, rate-limit, and
parsing logic, not Chess.com's uptime.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chess_psych.chesscom_client import (
    BASE, ArchivedGame, ChessComClient, ChessComError, PlayerNotFound,
)


def _mock_response(status: int = 200, json_data=None, headers=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.ok = 200 <= status < 300
    r.json.return_value = json_data or {}
    r.headers = headers or {}
    r.text = str(json_data) if json_data else ""
    return r


class TestRequestLayer:
    def test_404_raises_player_not_found(self):
        session = MagicMock()
        session.get.return_value = _mock_response(404)
        client = ChessComClient(session=session)
        with pytest.raises(PlayerNotFound):
            client.get_profile("nobody-here-12345")

    def test_retries_on_500_then_succeeds(self):
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(500),
            _mock_response(500),
            _mock_response(200, {"player_id": 42, "username": "ok"}),
        ]
        client = ChessComClient(session=session, retry_max=3, retry_backoff=1.0)
        with patch("time.sleep"):  # don't actually sleep in tests
            profile = client.get_profile("ok")
        assert profile.player_id == 42
        assert session.get.call_count == 3

    def test_429_uses_retry_after_header(self):
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(429, headers={"Retry-After": "0.1"}),
            _mock_response(200, {"username": "ok"}),
        ]
        client = ChessComClient(session=session, retry_max=2)
        with patch("time.sleep") as mock_sleep:
            client.get_profile("ok")
        # First sleep call should be the retry-after value
        first_sleep = mock_sleep.call_args_list[0]
        assert first_sleep.args[0] == 0.1

    def test_eventually_gives_up(self):
        session = MagicMock()
        session.get.return_value = _mock_response(500)
        client = ChessComClient(session=session, retry_max=1, retry_backoff=1.0)
        with patch("time.sleep"), pytest.raises(ChessComError):
            client.get_profile("flaky")

    def test_network_error_retries(self):
        session = MagicMock()
        session.get.side_effect = [
            requests.ConnectionError("boom"),
            _mock_response(200, {"username": "ok"}),
        ]
        client = ChessComClient(session=session, retry_max=2, retry_backoff=1.0)
        with patch("time.sleep"):
            client.get_profile("ok")
        assert session.get.call_count == 2

    def test_user_agent_header_is_set(self):
        client = ChessComClient(user_agent="MyUA/1.0")
        assert client.session.headers["User-Agent"] == "MyUA/1.0"


class TestGetStats:
    def test_picks_best_rating(self):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {
            "chess_bullet": {"last": {"rating": 1500}},
            "chess_blitz":  {"last": {"rating": 1800}},
            "chess_rapid":  {"last": {"rating": 1750}},
            "chess_daily":  {"last": {"rating": 1400}},
        })
        client = ChessComClient(session=session)
        stats = client.get_stats("user")
        assert stats.best_rating() == 1800

    def test_missing_classes_handled(self):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {
            "chess_blitz": {"last": {"rating": 1600}},
        })
        client = ChessComClient(session=session)
        stats = client.get_stats("user")
        assert stats.blitz_rating == 1600
        assert stats.bullet_rating is None
        assert stats.best_rating() == 1600

    def test_no_ratings_returns_none(self):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {})
        client = ChessComClient(session=session)
        assert client.get_stats("user").best_rating() is None


class TestIterGames:
    def _setup(self):
        session = MagicMock()
        archives = [f"{BASE}/player/x/games/2024/01", f"{BASE}/player/x/games/2024/02"]
        month1_games = [
            {"url": "g1", "pgn": "pgn1", "time_class": "blitz",
             "time_control": "300", "rated": True,
             "white": {"username": "x", "rating": 1500, "result": "win"},
             "black": {"username": "y", "rating": 1500, "result": "loss"}},
            {"url": "g2", "pgn": "pgn2", "time_class": "bullet",
             "time_control": "60", "rated": True,
             "white": {"username": "y", "rating": 1500},
             "black": {"username": "x", "rating": 1500}},
        ]
        month2_games = [
            {"url": "g3", "pgn": "pgn3", "time_class": "rapid",
             "time_control": "600", "rated": False,
             "white": {"username": "x"}, "black": {"username": "z"}},
        ]
        def get_side_effect(url, timeout):
            if url.endswith("/archives"):
                return _mock_response(200, {"archives": archives})
            if url.endswith("/2024/01"):
                return _mock_response(200, {"games": month1_games})
            if url.endswith("/2024/02"):
                return _mock_response(200, {"games": month2_games})
            return _mock_response(404)
        session.get.side_effect = get_side_effect
        return session

    def test_yields_newest_first(self):
        session = self._setup()
        with patch("time.sleep"):
            client = ChessComClient(session=session)
            games = list(client.iter_games("x", max_games=10))
        # Month 02 should come before month 01 (newest first)
        assert games[0].url == "g3"

    def test_max_games_respected(self):
        session = self._setup()
        with patch("time.sleep"):
            client = ChessComClient(session=session)
            games = list(client.iter_games("x", max_games=2))
        assert len(games) == 2

    def test_time_class_filter(self):
        session = self._setup()
        with patch("time.sleep"):
            client = ChessComClient(session=session)
            games = list(client.iter_games("x", max_games=10, time_classes=["bullet"]))
        assert len(games) == 1
        assert games[0].time_class == "bullet"

    def test_rated_only_filter(self):
        session = self._setup()
        with patch("time.sleep"):
            client = ChessComClient(session=session)
            games = list(client.iter_games("x", max_games=10, rated_only=True))
        # g3 was unrated
        assert all(g.rated for g in games)
        assert len(games) == 2

    def test_invalid_time_class_rejected(self):
        client = ChessComClient(session=MagicMock())
        with pytest.raises(ValueError):
            list(client.iter_games("x", time_classes=["nonsense"]))
