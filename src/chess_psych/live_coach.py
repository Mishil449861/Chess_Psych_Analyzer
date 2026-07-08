"""Live coaching engine.

Reads:
  - The user's known patterns (from offline `analyze` pipeline)
  - The current position (FEN)
  - Stockfish's evaluation and top candidate moves
  - The structural facts about the resulting position (hanging pieces,
    opponent's best reply, etc.)

Produces:
  - A verdict per move with concrete, position-specific guidance.
  - LLM-generated coaching prose grounded in the facts above (so it can't
    hallucinate "the bishop on g4" when there's no bishop on g4 — every
    fact in the prompt comes from Stockfish or python-chess directly).

Design notes:
  - LLM is only called on coachable moments (blunders, mistakes, hanging
    pieces, pattern matches). Solid moves get a fast, factual headline.
  - Stockfish's multipv gives us both the best move and the eval in one
    call, saving a network roundtrip vs. two separate analyses.
  - "Recent failure" flag stops us from re-spamming Ollama if it's down.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import chess
import numpy as np
from sklearn.preprocessing import StandardScaler

from .blunders import blunder_threshold
from .config import config
from .db import get_conn
from .features import extract_move_features, hanging_pieces
from .llm_summary import ollama_complete
from .patterns import features_to_vector
from .stockfish_pool import StockfishPool

log = logging.getLogger(__name__)


PIECE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}


@dataclass
class Pattern:
    """One of the user's learned recurring weaknesses."""
    pattern_id: int
    cluster_id: int
    name: str
    description: str
    size: int
    centroid: np.ndarray


@dataclass
class CoachVerdict:
    """The coach's read on the move that was just played."""
    # Classification
    is_blunder: bool
    eval_drop_cp: int
    severity: str            # 'info' | 'warning' | 'critical'
    headline: str            # "Best move" / "Solid" / "Mistake (−180cp)" / "Blunder — Hanging knight..."

    # Pattern match (only set when blunder + similar to a known weakness)
    matched_pattern: Optional[Pattern]
    similarity: float

    # Concrete board state after the move
    position_state: str       # "even" / "winning (+2.1)" / "losing (−4.2)"
    your_hanging: List[str] = field(default_factory=list)

    # What they should have played (from Stockfish multipv)
    best_move_san: Optional[str] = None
    best_move_eval_pawns: Optional[float] = None

    # What opponent will likely do next (from Stockfish on the resulting position)
    opponent_plan: Optional[str] = None

    # Multi-sentence LLM coach note — present only on coachable moments
    coach_note: Optional[str] = None


class LiveCoach:
    """Stateful coach for one player during a live game."""

    MATCH_THRESHOLD = 0.70

    def __init__(
        self,
        user_id: int,
        username: str,
        rating: Optional[int],
        patterns: List[Pattern],
        scaler: Optional[StandardScaler],
        stockfish: StockfishPool,
        eval_depth: Optional[int] = None,
        use_llm: bool = True,
    ):
        self.user_id = user_id
        self.username = username
        self.rating = rating
        self.patterns = patterns
        self.scaler = scaler
        self.stockfish = stockfish
        self.eval_depth = eval_depth or config.stockfish_depth
        self.threshold = blunder_threshold(rating)
        self.use_llm = use_llm
        self.history: List[CoachVerdict] = []
        self._llm_recent_failure = False

    # ---------- construction ----------
    @classmethod
    def for_user(
        cls,
        username: str,
        source: str = "chess.com",
        stockfish: Optional[StockfishPool] = None,
        db_path: Optional[Path] = None,
        use_llm: bool = True,
    ) -> "LiveCoach":
        with get_conn(db_path) as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ? AND source = ?",
                (username, source),
            ).fetchone()
            if not user:
                raise ValueError(
                    f"No profile found for '{username}' on {source}. "
                    f"Run `python -m chess_psych.cli analyze {username}` first."
                )

            pattern_rows = conn.execute(
                """SELECT id, cluster_id, name, description, size,
                          example_blunder_ids
                   FROM patterns WHERE user_id = ? ORDER BY size DESC""",
                (user["id"],),
            ).fetchall()

            blunder_rows = conn.execute(
                """SELECT cluster_id, features_json FROM blunders
                   WHERE user_id = ? AND cluster_id IS NOT NULL""",
                (user["id"],),
            ).fetchall()

        if blunder_rows:
            X = np.vstack([
                features_to_vector(json.loads(r["features_json"]))
                for r in blunder_rows
            ])
            scaler = StandardScaler().fit(X)
            X_scaled = scaler.transform(X)
            centroids: Dict[int, List[np.ndarray]] = {}
            for row, x in zip(blunder_rows, X_scaled):
                centroids.setdefault(row["cluster_id"], []).append(x)
            patterns = []
            for p in pattern_rows:
                cid = p["cluster_id"]
                if cid not in centroids:
                    continue
                patterns.append(Pattern(
                    pattern_id=p["id"], cluster_id=cid,
                    name=p["name"] or f"Pattern {cid}",
                    description=p["description"] or "",
                    size=p["size"],
                    centroid=np.mean(centroids[cid], axis=0),
                ))
        else:
            scaler = None
            patterns = []

        sf = stockfish or StockfishPool()
        if stockfish is None:
            sf.start()

        coach = cls(
            user_id=user["id"], username=user["username"],
            rating=user["rating"], patterns=patterns, scaler=scaler,
            stockfish=sf, use_llm=use_llm,
        )
        log.info("Loaded coach for %s (%d patterns, rating=%s, threshold=%dcp)",
                 username, len(patterns), user["rating"], coach.threshold)
        return coach

    # ---------- pattern matching ----------
    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def _match_pattern(self, feature_vec: np.ndarray) -> Tuple[Optional[Pattern], float]:
        if self.scaler is None or not self.patterns:
            return None, 0.0
        x = self.scaler.transform(feature_vec.reshape(1, -1))[0]
        best, best_sim = None, -1.0
        for p in self.patterns:
            sim = self._cosine_similarity(x, p.centroid)
            if sim > best_sim:
                best_sim, best = sim, p
        return (best, best_sim) if best_sim >= self.MATCH_THRESHOLD else (None, best_sim)

    # ---------- position description helpers ----------
    @staticmethod
    def _position_state_string(eval_user_pov_cp: int) -> str:
        abs_pawns = abs(eval_user_pov_cp) / 100.0
        if eval_user_pov_cp >= 9000:
            return "mate is forced for you"
        if eval_user_pov_cp <= -9000:
            return "mate threat against you"
        if eval_user_pov_cp > 300:
            return f"winning (+{abs_pawns:.1f})"
        if eval_user_pov_cp > 100:
            return f"better (+{abs_pawns:.1f})"
        if eval_user_pov_cp > -100:
            return "even"
        if eval_user_pov_cp > -300:
            return f"worse (−{abs_pawns:.1f})"
        return f"losing (−{abs_pawns:.1f})"

    def _describe_opponent_threat(self, board_after: chess.Board) -> Optional[str]:
        """One-line description of what the opponent will likely play next."""
        try:
            results = self.stockfish.analyse_with_pv(
                board_after, depth=max(self.eval_depth - 2, 6), multipv=1,
            )
        except Exception:
            return None
        if not results:
            return None
        opp_move = results[0]["move"]
        try:
            opp_san = board_after.san(opp_move)
        except (AssertionError, ValueError):
            return None

        # Describe in plain English: capture? check? quiet?
        if board_after.is_capture(opp_move):
            captured = board_after.piece_at(opp_move.to_square)
            # En passant: the piece sits behind the destination square
            if captured is None and board_after.is_en_passant(opp_move):
                cap_name, sq = "pawn", chess.square_name(opp_move.to_square)
                return f"{opp_san} (en passant on {sq})"
            if captured:
                cap_name = PIECE_NAMES.get(captured.piece_type, "piece")
                sq = chess.square_name(opp_move.to_square)
                return f"{opp_san} (captures your {cap_name} on {sq})"

        # Check detection
        b = board_after.copy()
        b.push(opp_move)
        if b.is_checkmate():
            return f"{opp_san}# (checkmate!)"
        if b.is_check():
            return f"{opp_san}+ (check)"
        return opp_san

    # ---------- LLM coaching ----------
    def _llm_coach_note(
        self,
        *,
        board_before: chess.Board,
        played_san: str,
        best_san: Optional[str],
        drop_cp: int,
        hanging_squares: List[str],
        opponent_plan: Optional[str],
        pattern: Optional[Pattern],
        side: str,
    ) -> Optional[str]:
        """Generate concrete, grounded coaching prose for one move."""
        if self._llm_recent_failure or not self.use_llm:
            return None

        pattern_line = ""
        if pattern:
            pattern_line = (
                f"\nThis matches their known weakness: "
                f"{pattern.name} — {pattern.description}"
            )
        hanging_line = (
            f"\nUndefended pieces after the move: {', '.join(hanging_squares)}"
            if hanging_squares else ""
        )
        threat_line = (
            f"\nOpponent's likely reply: {opponent_plan}" if opponent_plan else ""
        )
        best_line = (
            f"\nBest move was: {best_san}"
            if best_san and best_san != played_san else ""
        )

        prompt = f"""You are an experienced chess coach giving live, concrete feedback to a {self.rating or 'unrated'} student.

Student is playing as {side}.
Position FEN: {board_before.fen()}
Student just played: {played_san}
Eval dropped {drop_cp} centipawns.{best_line}{hanging_line}{threat_line}{pattern_line}

Respond in EXACTLY this format, two short sentences:
WHY: <concretely what was wrong with {played_san}, naming specific squares and/or pieces from the FACTS above>
INSTEAD: <what {best_san or "a better move"} would accomplish, naming specific squares and/or pieces>

Strict rules:
- Use ONLY facts present in the data above. Do not invent pieces or squares.
- No fluff. No "good question", "great game", "important to think about".
- No generic advice. No "look at the whole board", "calculate variations".
- Each sentence must be under 25 words.
- If you cannot say something specific from the data, output:
  WHY: This move loses tempo or material.
  INSTEAD: Look for active piece play and avoid hanging material.
"""
        text = ollama_complete(prompt, temperature=0.3, max_tokens=180)
        if not text:
            self._llm_recent_failure = True
            return None

        why, instead = None, None
        for line in text.splitlines():
            line = line.strip().lstrip("*").lstrip("-").strip()
            up = line.upper()
            if up.startswith("WHY:"):
                why = line.split(":", 1)[1].strip()
            elif up.startswith("INSTEAD:"):
                instead = line.split(":", 1)[1].strip()

        parts = [p for p in (why, instead) if p]
        return " ".join(parts) if parts else None

    # ---------- public API ----------
    def evaluate_move(
        self,
        board_before: chess.Board,
        move: chess.Move,
        board_after: chess.Board,
        time_spent: Optional[float] = None,
        eval_before: Optional[int] = None,
    ) -> CoachVerdict:
        side = "white" if board_before.turn == chess.WHITE else "black"
        user_color = chess.WHITE if side == "white" else chess.BLACK
        try:
            played_san = board_before.san(move)
        except (AssertionError, ValueError):
            played_san = move.uci()

        # Top moves AND eval_before in a single multipv call
        best_move_san: Optional[str] = None
        best_move_eval_pawns: Optional[float] = None
        try:
            pv_results = self.stockfish.analyse_with_pv(
                board_before, depth=self.eval_depth, multipv=3,
            )
        except Exception as e:
            log.warning("multipv failed: %s", e)
            pv_results = []

        if pv_results:
            if eval_before is None:
                eval_before = pv_results[0]["eval_cp"]
            try:
                best_move_san = board_before.san(pv_results[0]["move"])
                best_eval_w = pv_results[0]["eval_cp"]
                best_move_eval_pawns = (
                    best_eval_w if side == "white" else -best_eval_w
                ) / 100.0
            except Exception:
                pass
        elif eval_before is None:
            eval_before = self.stockfish.analyse(board_before, depth=self.eval_depth)

        # Eval of the resulting position
        eval_after = self.stockfish.analyse(board_after, depth=self.eval_depth)

        # Drop in user POV
        if side == "white":
            drop = eval_before - eval_after
            eval_user_pov = eval_after
        else:
            drop = eval_after - eval_before
            eval_user_pov = -eval_after

        is_blunder = drop >= self.threshold
        position_state = self._position_state_string(eval_user_pov)

        # Structural facts in the resulting position
        hanging_sqs = hanging_pieces(board_after, user_color)
        hanging_names = [chess.square_name(s) for s in hanging_sqs]

        opponent_plan = self._describe_opponent_threat(board_after)

        # Pattern match (only consider on actual blunders)
        feats = extract_move_features(
            fen_before=board_before.fen(),
            fen_after=board_after.fen(),
            san=played_san, uci=move.uci(),
            time_spent=time_spent,
            eval_before=eval_before, eval_after=eval_after,
            side=side,
        )
        vec = features_to_vector(feats)
        matched, sim = (None, 0.0)
        if is_blunder:
            matched, sim = self._match_pattern(vec)

        # Severity and headline
        played_was_best = (best_move_san is not None and best_move_san == played_san)
        if is_blunder and matched:
            severity = "critical"
            headline = f"Blunder — '{matched.name}'"
        elif is_blunder:
            severity = "critical"
            headline = f"Blunder (−{drop}cp)"
        elif drop > self.threshold // 2:
            severity = "warning"
            headline = f"Mistake (−{drop}cp)"
        elif drop > self.threshold // 4:
            severity = "info"
            headline = f"Inaccuracy (−{drop}cp)"
        elif played_was_best:
            severity = "info"
            headline = "Best move"
        else:
            severity = "info"
            headline = "Solid move"

        # LLM coaching — only when there's something concrete to teach
        needs_coaching = (
            is_blunder
            or drop > self.threshold // 2
            or len(hanging_names) > 0
            or matched is not None
        )
        coach_note = None
        if needs_coaching:
            coach_note = self._llm_coach_note(
                board_before=board_before,
                played_san=played_san,
                best_san=best_move_san,
                drop_cp=int(drop),
                hanging_squares=hanging_names,
                opponent_plan=opponent_plan,
                pattern=matched,
                side=side,
            )

        verdict = CoachVerdict(
            is_blunder=is_blunder,
            eval_drop_cp=int(drop),
            severity=severity,
            headline=headline,
            matched_pattern=matched,
            similarity=sim,
            position_state=position_state,
            your_hanging=hanging_names,
            best_move_san=best_move_san,
            best_move_eval_pawns=best_move_eval_pawns,
            opponent_plan=opponent_plan,
            coach_note=coach_note,
        )
        self.history.append(verdict)
        return verdict

    # ---------- end-of-game ----------
    def game_summary(self) -> str:
        if not self.history:
            return "No moves played yet."
        n_blunders = sum(1 for v in self.history if v.is_blunder)
        n_mistakes = sum(1 for v in self.history if not v.is_blunder
                         and v.eval_drop_cp > self.threshold // 2)
        patterns_hit = sorted({
            v.matched_pattern.name for v in self.history if v.matched_pattern
        })

        bits = [
            f"You made {len(self.history)} moves, "
            f"with {n_blunders} blunder{'s' if n_blunders != 1 else ''} "
            f"and {n_mistakes} mistake{'s' if n_mistakes != 1 else ''}.",
        ]
        if patterns_hit:
            bits.append(
                f"You fell into {len(patterns_hit)} known pattern"
                f"{'s' if len(patterns_hit) != 1 else ''}: "
                + ", ".join(patterns_hit) + "."
            )
        else:
            bits.append("You avoided every one of your known patterns.")
        return " ".join(bits)
