"""Unit tests for pure functions — no Stockfish, no HTTP, no LLM.

Run with:
    pytest tests/ -v
"""
import json
import sys
from pathlib import Path

import chess
import numpy as np
import pytest

# Make project root importable when running pytest from anywhere
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chess_psych.blunders import blunder_threshold
from chess_psych.features import (
    extract_move_features, hanging_pieces, king_zone_attackers,
    material_balance, phase_of,
)
from chess_psych.ingest import parse_clock_comment, parse_eval_comment
from chess_psych.patterns import features_to_vector, summarize_cluster


# ---------------------------------------------------------------------------
# features.py
# ---------------------------------------------------------------------------
class TestPhase:
    def test_starting_position_is_opening(self):
        assert phase_of(chess.Board()) == "opening"

    def test_late_middlegame(self):
        # Manually place a thinned-out position
        b = chess.Board("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 25")
        assert phase_of(b) == "endgame"


class TestHangingPieces:
    def test_undefended_attacked_piece_is_hanging(self):
        # White queen on d4 attacked by black knight on c6, no defenders
        b = chess.Board("4k3/8/2n5/8/3Q4/8/8/4K3 w - - 0 1")
        hanging = hanging_pieces(b, chess.WHITE)
        assert chess.D4 in hanging

    def test_defended_piece_with_equal_or_stronger_defender_not_hanging(self):
        # White pawn on d4 defended by pawn on c3, attacked by black pawn on e5.
        # Attacker (pawn=1) == piece (pawn=1), so even trade — not hanging.
        b = chess.Board("4k3/8/8/4p3/3P4/2P5/8/4K3 w - - 0 1")
        assert chess.D4 not in hanging_pieces(b, chess.WHITE)

    def test_queen_defended_only_by_rook_against_knight_is_still_hanging(self):
        # Queen defended by rook attacked by knight: Nxd4 Rxd4 loses queen for knight.
        # This is correctly flagged as hanging by our cheapest-attacker heuristic.
        b = chess.Board("4k3/8/2n5/8/3Q4/8/8/3RK3 w - - 0 1")
        assert chess.D4 in hanging_pieces(b, chess.WHITE)

    def test_king_never_hanging(self):
        b = chess.Board()
        assert chess.E1 not in hanging_pieces(b, chess.WHITE)


class TestMaterialBalance:
    def test_starting_position_balanced(self):
        assert material_balance(chess.Board()) == 0

    def test_minus_one_pawn(self):
        # White minus a pawn
        b = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR w KQkq - 0 1")
        assert material_balance(b) == -1


class TestKingZone:
    def test_unattacked_king_zero(self):
        assert king_zone_attackers(chess.Board(), chess.WHITE) == 0


class TestExtractMoveFeatures:
    def test_basic_e4(self):
        b = chess.Board()
        move = chess.Move.from_uci("e2e4")
        san, uci = b.san(move), move.uci()
        fb = b.fen()
        b.push(move)
        feats = extract_move_features(
            fen_before=fb, fen_after=b.fen(),
            san=san, uci=uci,
            time_spent=2.0, eval_before=20, eval_after=30,
            side="white", eco="C20",
        )
        assert feats["piece"] == "pawn"
        assert feats["phase"] == "opening"
        assert feats["is_capture"] is False
        assert feats["eco"] == "C20"

    def test_eval_drop_user_pov_white(self):
        b = chess.Board()
        move = chess.Move.from_uci("e2e4")
        b.push(move)
        feats = extract_move_features(
            fen_before=chess.STARTING_FEN, fen_after=b.fen(),
            san="e4", uci="e2e4",
            eval_before=20, eval_after=-180,
            side="white",
        )
        assert feats["eval_drop_cp"] == 200  # 20 - (-180)

    def test_eval_drop_user_pov_black(self):
        b = chess.Board()
        b.push_san("e4")
        fen_before = b.fen()
        b.push_san("e5")
        # Black: eval went from -20 (good for black) to +180 (bad for black) — drop 200
        feats = extract_move_features(
            fen_before=fen_before, fen_after=b.fen(),
            san="e5", uci="e7e5",
            eval_before=-20, eval_after=180,
            side="black",
        )
        assert feats["eval_drop_cp"] == 200


# ---------------------------------------------------------------------------
# blunders.py
# ---------------------------------------------------------------------------
class TestBlunderThreshold:
    def test_higher_rating_means_lower_threshold(self):
        assert blunder_threshold(2200) < blunder_threshold(1000)

    def test_monotonic(self):
        ts = [blunder_threshold(r) for r in (1000, 1300, 1700, 2100)]
        # Non-increasing across bands
        assert all(a >= b for a, b in zip(ts, ts[1:]))

    def test_handles_none(self):
        assert blunder_threshold(None) > 0


# ---------------------------------------------------------------------------
# ingest.py — parsers
# ---------------------------------------------------------------------------
class TestParseEval:
    def test_centipawn(self):
        assert parse_eval_comment("[%eval 1.23]") == 123

    def test_negative(self):
        assert parse_eval_comment("[%eval -0.5]") == -50

    def test_mate_for_white(self):
        assert parse_eval_comment("[%eval #5]") == 10000

    def test_mate_for_black(self):
        assert parse_eval_comment("[%eval #-3]") == -10000

    def test_absent(self):
        assert parse_eval_comment("") is None
        assert parse_eval_comment("just some text") is None


class TestParseClock:
    def test_normal(self):
        assert parse_clock_comment("[%clk 0:01:30]") == 90.0

    def test_with_fraction(self):
        assert parse_clock_comment("[%clk 0:00:05.5]") == 5.5

    def test_absent(self):
        assert parse_clock_comment("") is None


# ---------------------------------------------------------------------------
# patterns.py
# ---------------------------------------------------------------------------
class TestVectorization:
    def test_fixed_length(self):
        f1 = {"piece": "knight", "phase": "middlegame", "eco": "C50",
              "time_class": "blitz", "is_capture": False, "is_check": False,
              "time_spent": 5, "hanging_increase": 1, "king_attackers_increase": 0,
              "material_delta": -3, "eval_drop_cp": 250}
        f2 = {"piece": "queen", "phase": "endgame", "eco": "B20",
              "time_class": "rapid", "is_capture": True, "is_check": True,
              "time_spent": 60, "hanging_increase": 0, "king_attackers_increase": 2,
              "material_delta": 0, "eval_drop_cp": 400}
        v1 = features_to_vector(f1)
        v2 = features_to_vector(f2)
        assert v1.shape == v2.shape
        assert len(v1) > 10

    def test_missing_fields_dont_crash(self):
        v = features_to_vector({})
        assert isinstance(v, np.ndarray)
        assert not np.any(np.isnan(v))


class TestSummarizeCluster:
    def test_returns_expected_keys(self):
        members = [{"features": {
            "piece": "knight", "phase": "middlegame", "eco": "C50",
            "time_class": "blitz", "is_capture": False,
            "time_spent": 2, "hanging_increase": 1,
            "king_attackers_increase": 0, "eval_drop_cp": 200,
        }} for _ in range(4)]
        s = summarize_cluster(members)
        assert s["piece"] == "knight"
        assert s["phase"] == "middlegame"
        assert s["size"] == 4
        assert 0 <= s["capture_rate"] <= 1
        assert "name" in s and "description" in s
