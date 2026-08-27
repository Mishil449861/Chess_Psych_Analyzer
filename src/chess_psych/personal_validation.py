"""Chronological validation for a player's recurring error patterns.

This module is deliberately separate from the presentation layer. It turns
engine-confirmed mistakes into structured observations, learns patterns only
from older games, and measures whether those patterns recur in newer games.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence

import chess
import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from .features import (
    PIECE_NAMES,
    PIECE_VALUES,
    clock_context,
    hanging_pieces,
    king_zone_attackers,
    material_balance,
    parse_time_control,
    phase_of,
)


# These are concrete board facts, not broad move-context descriptions. A
# player-facing pattern must be one of these and pass the chronological checks
# below; "Other confirmed error" is intentionally never coaching advice.
LABELABLE_ERROR_FAMILIES = frozenset({
    "Delayed recapture",
    "Leaves a piece loose",
    "King safety",
    "Material oversight",
    "Missed tactical capture",
    "Missed checking move",
    "Allows a new capture",
    "Allows a new check",
})
MIN_LABEL_PURITY = 0.75
MIN_LABEL_HOLDOUT_MATCHES = 2
MIN_LABEL_HOLDOUT_AGREEMENT = 0.70
MIN_FAMILY_PATTERN_TRAINING_OCCURRENCES = 8
MIN_FAMILY_PATTERN_HOLDOUT_OCCURRENCES = 2
MIN_RISK_TRAINING_DECISIONS = 8
MIN_RISK_HOLDOUT_DECISIONS = 4
MIN_RISK_TRAINING_ERRORS = 3
MIN_RISK_HOLDOUT_ERRORS = 2
MIN_RISK_FAMILY_PURITY = 0.60
MIN_RISK_LIFT = 1.15
# These fields describe the situation around an engine-confirmed error.  They
# are separate from the HDBSCAN inputs: we use them only to make a displayed
# coaching cue more specific after it has repeated in chronological holdout.
CONTEXT_FIELDS = (
    "phase",
    "piece",
    "time_context",
    "opponent_reply_capture_piece",
    "opponent_reply_captures_moved_piece",
    "moved_piece_started_safe",
    "moved_piece_moved_into_attack",
    "moved_piece_unprotected_after",
)
RISK_CONTEXT_FIELDS = (
    ("phase",),
    ("piece",),
    ("time_context",),
    ("phase", "piece"),
    ("phase", "time_context"),
    ("piece", "time_context"),
)


@dataclass
class ErrorObservation:
    game_url: str
    played_at: str
    time_class: str
    user_color: str
    user_rating: Optional[int]
    opponent: str
    ply: int
    move_number: int
    san: str
    uci: str
    fen_before: str
    fen_after: str
    eval_before_cp: int
    eval_after_cp: int
    eval_drop_cp: int
    threshold_cp: int
    best_move_san: str
    best_move_uci: str
    features: Dict[str, Any]
    opponent_best_reply_san: Optional[str] = None
    opponent_best_reply_uci: Optional[str] = None
    clock_remaining_seconds: Optional[float] = None
    time_spent_seconds: Optional[float] = None
    initial_seconds: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def error_threshold(rating: Optional[int]) -> int:
    """A conservative per-game threshold for demo-quality errors."""
    if rating is None:
        return 200
    if rating < 1200:
        return 250
    if rating < 1600:
        return 180
    if rating < 2000:
        return 150
    return 120


def user_eval_drop(before: int, after: int, color: chess.Color) -> int:
    return before - after if color == chess.WHITE else after - before


def _piece_name(piece: Optional[chess.Piece]) -> str:
    return PIECE_NAMES.get(piece.piece_type, "unknown") if piece else "unknown"


def _material_delta(before: chess.Board, after: chess.Board, color: chess.Color) -> int:
    delta = material_balance(after) - material_balance(before)
    return delta if color == chess.WHITE else -delta


def _family(features: Dict[str, Any]) -> str:
    """Return an explanation-only chess rule label.

    These rule-defining fields are deliberately excluded from HDBSCAN's model
    features below. A cluster can therefore be evaluated against this label
    without merely reproducing the inputs that formed it.
    """
    if features["ignored_recapture"]:
        return "Delayed recapture"
    if features["opens_new_capture"]:
        return "Allows a new capture"
    if features["opens_new_check"]:
        return "Allows a new check"
    if features["hanging_increase"] > 0:
        return "Leaves a piece loose"
    if features["king_attackers_increase"] >= 2:
        return "King safety"
    if features["material_delta"] <= -3:
        return "Material oversight"
    if features["best_move_is_capture"] and not features["is_capture"]:
        return "Missed tactical capture"
    if features["best_move_is_check"] and not features["is_check"]:
        return "Missed checking move"
    return "Other confirmed error"


def extract_error_features(
    board_before: chess.Board,
    board_after: chess.Board,
    played_move: chess.Move,
    best_move: chess.Move,
    *,
    previous_move: Optional[chess.Move],
    previous_was_capture: bool,
    eval_drop_cp: int,
    time_class: str,
    clock_remaining: Optional[float] = None,
    time_spent: Optional[float] = None,
    time_control: Optional[str] = None,
    opponent_best_reply: Optional[chess.Move] = None,
) -> Dict[str, Any]:
    """Extract interpretable features used by the personal-pattern model."""
    color = board_before.turn
    piece = board_before.piece_at(played_move.from_square)
    best_piece = board_before.piece_at(best_move.from_square)
    is_capture = board_before.is_capture(played_move)
    best_is_capture = board_before.is_capture(best_move)
    previous_square = previous_move.to_square if previous_move else None

    hanging_before = len(hanging_pieces(board_before, color))
    hanging_after = len(hanging_pieces(board_after, color))
    king_before = king_zone_attackers(board_before, color)
    king_after = king_zone_attackers(board_after, color)

    ignored_recapture = bool(
        previous_was_capture
        and previous_square is not None
        and not (is_capture and played_move.to_square == previous_square)
        and best_is_capture
        and best_move.to_square == previous_square
    )

    moved_after = board_after.piece_at(played_move.to_square)
    moved_piece_attacked = bool(
        moved_after and board_after.is_attacked_by(not color, played_move.to_square)
    )
    moved_piece_defended = bool(
        moved_after and board_after.is_attacked_by(color, played_move.to_square)
    )
    moved_piece_started_safe = not board_before.is_attacked_by(not color, played_move.from_square)
    moved_piece_moved_into_attack = moved_piece_started_safe and moved_piece_attacked
    opponent_reply_is_capture = bool(
        opponent_best_reply and board_after.is_capture(opponent_best_reply)
    )
    opponent_reply_is_check = bool(
        opponent_best_reply and board_after.gives_check(opponent_best_reply)
    )
    reply_captured_piece = None
    reply_piece = None
    reply_captures_moved_piece = False
    if opponent_best_reply:
        reply_piece = board_after.piece_at(opponent_best_reply.from_square)
        if opponent_reply_is_capture:
            # En passant is the only capture where the victim is not on the
            # destination square.  It is rare in the data, but should not be
            # reported as an unknown target.
            captured_square = opponent_best_reply.to_square
            if board_after.is_en_passant(opponent_best_reply):
                captured_square += -8 if board_after.turn == chess.WHITE else 8
            reply_captured_piece = board_after.piece_at(captured_square)
            reply_captures_moved_piece = captured_square == played_move.to_square
    reply_was_already_capture = False
    reply_was_already_check = False
    if opponent_best_reply:
        # Check whether the engine reply was already a capture/check before
        # the move. The same destination can be reachable when empty, then
        # become a materially meaningful capture after the player moves.
        before_opponent_turn = board_before.copy(stack=False)
        before_opponent_turn.turn = not color
        if opponent_best_reply in before_opponent_turn.legal_moves:
            reply_was_already_capture = before_opponent_turn.is_capture(opponent_best_reply)
            reply_was_already_check = before_opponent_turn.gives_check(opponent_best_reply)

    initial_seconds, _ = parse_time_control(time_control)
    clock_value = float(clock_remaining) if clock_remaining is not None else None
    spent_value = float(time_spent) if time_spent is not None else None
    features: Dict[str, Any] = {
        "phase": phase_of(board_before),
        "piece": _piece_name(piece),
        "best_piece": _piece_name(best_piece),
        "time_class": time_class or "unknown",
        "time_context": clock_context(clock_value, initial_seconds, spent_value),
        "clock_remaining_seconds": clock_value,
        "clock_fraction_remaining": (
            round(clock_value / initial_seconds, 4)
            if clock_value is not None and initial_seconds else None
        ),
        "time_spent_seconds": spent_value,
        "is_capture": is_capture,
        "is_check": board_after.is_check(),
        "best_move_is_capture": best_is_capture,
        "best_move_is_check": board_before.gives_check(best_move),
        "opponent_best_reply_is_capture": opponent_reply_is_capture,
        "opponent_best_reply_is_check": opponent_reply_is_check,
        "opponent_reply_piece": _piece_name(reply_piece),
        "opponent_reply_capture_piece": _piece_name(reply_captured_piece),
        "opponent_reply_captures_moved_piece": reply_captures_moved_piece,
        "opens_new_capture": opponent_reply_is_capture and not reply_was_already_capture,
        "opens_new_check": opponent_reply_is_check and not reply_was_already_check,
        "ignored_recapture": ignored_recapture,
        "previous_move_was_capture": previous_was_capture,
        "same_piece_as_best": played_move.from_square == best_move.from_square,
        "moved_piece_attacked": moved_piece_attacked,
        "moved_piece_defended": moved_piece_defended,
        "moved_piece_started_safe": moved_piece_started_safe,
        "moved_piece_moved_into_attack": moved_piece_moved_into_attack,
        "moved_piece_unprotected_after": bool(moved_after and not moved_piece_defended),
        "moved_piece_attackers_after": len(board_after.attackers(not color, played_move.to_square)),
        "moved_piece_defenders_after": len(board_after.attackers(color, played_move.to_square)),
        "hanging_before": hanging_before,
        "hanging_after": hanging_after,
        "hanging_increase": hanging_after - hanging_before,
        "king_attackers_increase": king_after - king_before,
        "material_delta": _material_delta(board_before, board_after, color),
        "moved_piece_value": PIECE_VALUES.get(piece.piece_type, 0) if piece else 0,
        "eval_drop_pawns": min(eval_drop_cp, 1500) / 100.0,
    }
    features["error_family"] = _family(features)
    return features


MODEL_FIELDS = (
    "phase", "piece", "best_piece", "time_class", "time_context", "is_capture", "is_check",
    "best_move_is_check", "previous_move_was_capture", "same_piece_as_best", "moved_piece_attacked",
    "moved_piece_defended", "hanging_before",
    "moved_piece_value", "eval_drop_pawns",
)


def _model_features(obs: ErrorObservation) -> Dict[str, Any]:
    return {key: obs.features.get(key) for key in MODEL_FIELDS}


def _mode(values: Iterable[str]) -> str:
    counts = Counter(values)
    return counts.most_common(1)[0][0] if counts else "Unclassified error"


def _example(obs: ErrorObservation) -> Dict[str, Any]:
    return {
        "game_url": obs.game_url,
        "played_at": obs.played_at,
        "opponent": obs.opponent,
        "move": obs.san,
        "ply": obs.ply,
        "fen_before": obs.fen_before,
        "fen_after": obs.fen_after,
        "eval_drop_cp": obs.eval_drop_cp,
        "best_move": obs.best_move_san,
        "opponent_best_reply": obs.opponent_best_reply_san,
        "rule_label": obs.features["error_family"],
        "phase": obs.features.get("phase", "unknown"),
        "piece": obs.features.get("piece", "unknown"),
        "time_context": obs.features.get("time_context", "unknown"),
        "clock_remaining_seconds": obs.clock_remaining_seconds,
        "time_spent_seconds": obs.time_spent_seconds,
        "initial_seconds": obs.initial_seconds,
    }


def _label_evidence(members: Sequence[ErrorObservation]) -> Dict[str, Any]:
    """Build a compact, factual packet for the local LLM label manager."""
    count = len(members)
    known_clocks = [m.clock_remaining_seconds for m in members if m.clock_remaining_seconds is not None]
    known_spent = [m.time_spent_seconds for m in members if m.time_spent_seconds is not None]
    return {
        "members": count,
        "phase_counts": dict(Counter(m.features.get("phase", "unknown") for m in members)),
        "piece_counts": dict(Counter(m.features.get("piece", "unknown") for m in members)),
        "time_context_counts": dict(Counter(m.features.get("time_context", "unknown") for m in members)),
        "rule_label_counts": dict(Counter(m.features["error_family"] for m in members)),
        "opponent_reply_capture_count": sum(bool(m.features.get("opponent_best_reply_is_capture")) for m in members),
        "opponent_reply_check_count": sum(bool(m.features.get("opponent_best_reply_is_check")) for m in members),
        "median_clock_remaining_seconds": round(float(np.median(known_clocks)), 1) if known_clocks else None,
        "median_time_spent_seconds": round(float(np.median(known_spent)), 1) if known_spent else None,
    }


def _dominant_evidence_value(evidence: Dict[str, Any], key: str, fallback: str) -> str:
    counts = evidence.get(key, {})
    if not counts:
        return fallback
    return max(counts, key=lambda value: (counts[value], value))


def decision_context_from_cluster(cluster: Dict[str, Any]) -> Dict[str, str]:
    """Turn a cluster's measured context into a bounded player-facing read.

    This is not a second classifier and never upgrades a cluster to a validated
    coaching claim. It explains either a concrete repeated mechanism or, when
    the mechanism is mixed, the decision moment that deserves attention.
    """
    evidence = cluster.get("label_evidence", {})
    family = cluster.get("name", "Other confirmed error")
    phase = _dominant_evidence_value(evidence, "phase_counts", "middle-game")
    piece = _dominant_evidence_value(evidence, "piece_counts", "piece")
    clock = _dominant_evidence_value(evidence, "time_context_counts", "available")
    clock_remaining = evidence.get("median_clock_remaining_seconds")
    low_clock = clock == "critical" or (
        isinstance(clock_remaining, (int, float)) and clock_remaining <= 60
    )
    phase_label = {
        "middlegame": "middlegame",
        "endgame": "endgame",
        "opening": "opening",
    }.get(phase, phase)

    if family == "Allows a new capture":
        return {
            "kind": "practice cue",
            "title": f"{phase_label.title()} {piece} moves give away a capture",
            "why": (
                f"This player's {piece} moves in the {phase_label} repeatedly gave the "
                "opponent a capture that was not there before."
            ),
            "action": (
                f"Before moving a {piece}, trace its destination square: what attacks it, "
                "and what protects it?"
            ),
        }
    if family == "Allows a new check":
        return {
            "kind": "practice cue",
            "title": f"{phase_label.title()} king moves open checks",
            "why": (
                "These errors group around king moves where the opponent gains a forcing "
                "check on the next move."
            ),
            "action": "Before moving the king, name the opponent's checking move after it.",
        }
    if family == "Missed tactical capture":
        return {
            "kind": "practice cue",
            "title": f"{phase_label.title()} {piece} decisions miss a capture",
            "why": (
                f"In these {phase_label} positions, the player chose a {piece} move while "
                "a tactical capture was available."
            ),
            "action": "Before a quiet move, list the immediate captures for both sides.",
        }
    if family == "Leaves a piece loose":
        return {
            "kind": "practice cue",
            "title": f"{phase_label.title()} {piece} moves leave something loose",
            "why": "The move repeatedly increased what the opponent could win immediately.",
            "action": "After choosing a move, ask which of your pieces became unprotected.",
        }
    if low_clock:
        return {
            "kind": "watchpoint",
            "title": f"Low-clock {piece} {phase_label} decisions",
            "why": (
                f"The engine flags gather around {piece} decisions in the {phase_label} "
                "when the clock is low. The tactics vary, so this is a decision moment to "
                "watch, not a simple flaw label."
            ),
            "action": (
                f"With little time in the {phase_label}, make one forcing-reply scan before "
                f"a {piece} move: their checks, then their captures."
            ),
        }
    return {
        "kind": "watchpoint",
        "title": f"{phase_label.title()} {piece} decisions",
        "why": (
            f"The model groups these {phase_label} {piece} decisions by board shape, but "
            "the exact tactical cause varies."
        ),
        "action": f"Before committing a {piece} move, take one forcing-reply scan: checks and captures.",
    }


def _risk_context_label(conditions: Dict[str, Any]) -> str:
    """Describe a measured decision context without pretending it is a tactic."""
    phase = conditions.get("phase")
    piece = conditions.get("piece")
    clock = conditions.get("time_context")
    parts: List[str] = []
    if clock == "quick":
        parts.append("quick")
    elif clock in {"low", "critical"}:
        parts.append("low-clock")
    if phase:
        parts.append(str(phase))
    if piece:
        parts.append(f"{piece} moves")
    return " ".join(parts).capitalize() or "Decision context"


def _pressure_story(conditions: Dict[str, Any]) -> Dict[str, str]:
    """Describe a repeatable risk context when tactics are intentionally mixed."""
    label = _risk_context_label(conditions)
    phase = conditions.get("phase", "position")
    piece = conditions.get("piece")
    clock = conditions.get("time_context")
    if clock in {"low", "critical"}:
        action = "With little time, name the opponent's forcing move before you commit."
    elif piece:
        action = f"Before a {piece} move here, pause for one checks-and-captures scan."
    else:
        action = f"In this {phase}, make one forcing-reply scan before committing."
    return {
        "kind": "pressure profile",
        "title": f"Higher-risk {label.lower()}",
        "why": (
            "The engine errors share this decision context, but their tactical causes are "
            "mixed. This is a measured pressure point to review, not a claim about one flaw."
        ),
        "action": action,
    }


def adaptive_risk_patterns(
    observations: Sequence[ErrorObservation],
    decisions: Sequence[Dict[str, Any]],
    *,
    cutoff: str,
) -> List[Dict[str, Any]]:
    """Find repeatable high-risk contexts using all decisions as a denominator.

    HDBSCAN is deliberately conservative: some players, especially at the
    extremes of the rating range, have no dense, mechanism-pure cluster. This
    companion analysis asks a different, checkable question: is a concrete
    decision context more error-prone than *this player's* usual decision in
    both the older training period and the later holdout? It never compares a
    player's raw error count with another player's.
    """
    error_by_key = {
        (observation.game_url, observation.ply): observation
        for observation in observations
    }
    decision_rows = [
        row for row in decisions
        if row.get("played_at") and row.get("game_url") and row.get("ply")
    ]
    train_decisions = [row for row in decision_rows if row["played_at"] < cutoff]
    holdout_decisions = [row for row in decision_rows if row["played_at"] >= cutoff]
    if not train_decisions or not holdout_decisions:
        return []

    def is_error(row: Dict[str, Any]) -> bool:
        return (row["game_url"], row["ply"]) in error_by_key

    train_baseline = sum(is_error(row) for row in train_decisions) / len(train_decisions)
    holdout_baseline = sum(is_error(row) for row in holdout_decisions) / len(holdout_decisions)
    if not train_baseline or not holdout_baseline:
        return []

    candidates: List[Dict[str, Any]] = []
    for fields in RISK_CONTEXT_FIELDS:
        values = {
            tuple(observation.features.get(field, "unknown") for field in fields)
            for observation in observations
            if observation.played_at < cutoff
        }
        for values_tuple in values:
            if "unknown" in values_tuple:
                continue
            conditions = dict(zip(fields, values_tuple))

            def matches(row: Dict[str, Any]) -> bool:
                features = row.get("features", {})
                return all(features.get(field) == value for field, value in conditions.items())

            train_rows = [row for row in train_decisions if matches(row)]
            holdout_rows = [row for row in holdout_decisions if matches(row)]
            train_errors = [error_by_key[(row["game_url"], row["ply"])] for row in train_rows if is_error(row)]
            holdout_errors = [error_by_key[(row["game_url"], row["ply"])] for row in holdout_rows if is_error(row)]
            if (
                len(train_rows) < MIN_RISK_TRAINING_DECISIONS
                or len(holdout_rows) < MIN_RISK_HOLDOUT_DECISIONS
                or len(train_errors) < MIN_RISK_TRAINING_ERRORS
                or len(holdout_errors) < MIN_RISK_HOLDOUT_ERRORS
            ):
                continue

            family = _mode(error.features["error_family"] for error in train_errors)
            family_purity = sum(
                error.features["error_family"] == family for error in train_errors
            ) / len(train_errors)
            later_family_share = sum(
                error.features["error_family"] == family for error in holdout_errors
            ) / len(holdout_errors)
            train_rate = len(train_errors) / len(train_rows)
            holdout_rate = len(holdout_errors) / len(holdout_rows)
            train_lift = train_rate / train_baseline
            holdout_lift = holdout_rate / holdout_baseline
            if train_lift < MIN_RISK_LIFT or holdout_lift < MIN_RISK_LIFT:
                continue

            has_single_mechanism = bool(
                family in LABELABLE_ERROR_FAMILIES
                and family_purity >= MIN_RISK_FAMILY_PURITY
                and later_family_share >= MIN_RISK_FAMILY_PURITY
            )

            cluster_like = {
                "name": family,
                "label_evidence": _label_evidence(train_errors),
            }
            candidates.append({
                "kind": "risk_context" if has_single_mechanism else "pressure_profile",
                "conditions": conditions,
                "title": _risk_context_label(conditions),
                "family": family,
                "training_decisions": len(train_rows),
                "holdout_decisions": len(holdout_rows),
                "training_errors": len(train_errors),
                "holdout_errors": len(holdout_errors),
                "training_rate": round(train_rate, 3),
                "holdout_rate": round(holdout_rate, 3),
                "training_lift": round(train_lift, 2),
                "holdout_lift": round(holdout_lift, 2),
                "family_purity": round(family_purity, 3),
                "later_family_agreement": round(later_family_share, 3),
                # Keep these only while selecting patterns. Different feature
                # combinations can identify the exact same decisions, which
                # would otherwise produce redundant player-facing labels.
                "_training_decision_keys": frozenset(
                    (row["game_url"], row["ply"]) for row in train_rows
                ),
                "_holdout_decision_keys": frozenset(
                    (row["game_url"], row["ply"]) for row in holdout_rows
                ),
                "story": (
                    decision_context_from_cluster(cluster_like)
                    if has_single_mechanism else _pressure_story(conditions)
                ),
                "examples": [
                    _example(error)
                    for error in sorted(train_errors, key=lambda error: -error.eval_drop_cp)[:3]
                ],
            })

    # A narrower context is more useful only when it has at least as much
    # support; this removes duplicate "middlegame" and "middlegame bishop"
    # versions of the same finding.
    candidates.sort(
        key=lambda item: (
            len(item["conditions"]),
            "time_context" in item["conditions"],
            "piece" in item["conditions"],
            item["training_lift"] + item["holdout_lift"],
            item["training_errors"] + item["holdout_errors"],
        ),
        reverse=True,
    )
    selected: List[Dict[str, Any]] = []
    for candidate in candidates:
        if any(
            candidate["_training_decision_keys"] == chosen["_training_decision_keys"]
            and candidate["_holdout_decision_keys"] == chosen["_holdout_decision_keys"]
            for chosen in selected
        ):
            continue
        if any(
            candidate["conditions"].items() <= chosen["conditions"].items()
            for chosen in selected
        ):
            continue
        selected.append(candidate)
    for candidate in selected:
        candidate.pop("_training_decision_keys")
        candidate.pop("_holdout_decision_keys")
    return selected


def _stable_context(
    train: Sequence[ErrorObservation],
    holdout: Sequence[ErrorObservation],
) -> Optional[Dict[str, Any]]:
    """Find a compact context that remains common in the later games.

    This is deliberately a prevalence check, not a label generated by the
    clusterer. A context needs at least two later examples and 45% share in
    both periods; otherwise it is too easy to tell a compelling story from a
    small historical slice.
    """
    if not train or not holdout:
        return None
    candidates = []
    for size in range(1, len(CONTEXT_FIELDS) + 1):
        for fields in combinations(CONTEXT_FIELDS, size):
            values = {
                tuple(observation.features.get(field, "unknown") for field in fields)
                for observation in train
            }
            for value in values:
                conditions = dict(zip(fields, value))
                # Do not manufacture specificity from a missing tactical
                # detail.  These fields are only meaningful when the reply
                # really is a capture, or when it really takes the moved
                # piece.
                if (
                    conditions.get("opponent_reply_capture_piece") == "unknown"
                    or conditions.get("opponent_reply_captures_moved_piece") is False
                    or conditions.get("moved_piece_started_safe") is False
                    or conditions.get("moved_piece_moved_into_attack") is False
                    or conditions.get("moved_piece_unprotected_after") is False
                ):
                    continue
                train_matches = [
                    observation for observation in train
                    if tuple(observation.features.get(field, "unknown") for field in fields) == value
                ]
                holdout_matches = [
                    observation for observation in holdout
                    if tuple(observation.features.get(field, "unknown") for field in fields) == value
                ]
                train_share = len(train_matches) / len(train)
                holdout_share = len(holdout_matches) / len(holdout)
                if len(holdout_matches) < 2 or train_share < 0.45 or holdout_share < 0.45:
                    continue
                candidates.append({
                    "conditions": conditions,
                    "training_occurrences": len(train_matches),
                    "holdout_occurrences": len(holdout_matches),
                    "training_share": round(train_share, 3),
                    "holdout_share": round(holdout_share, 3),
                    "evidence": _label_evidence(train_matches + holdout_matches),
                })
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            len(item["conditions"]),
            min(item["training_share"], item["holdout_share"]),
            item["holdout_occurrences"],
        ),
    )


def validate_patterns(
    observations: Sequence[ErrorObservation],
    *,
    cutoff: str,
    min_cluster_size: int = 4,
    focus_rule_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Train on errors before ``cutoff`` and evaluate later errors.

    The result avoids calling unsupervised clustering "accuracy". It reports
    cluster cohesion, independent rule agreement, and temporal recurrence.
    """
    train_all = [o for o in observations if o.played_at < cutoff]
    holdout = [o for o in observations if o.played_at >= cutoff]
    train = [
        observation for observation in train_all
        if focus_rule_label is None or observation.features["error_family"] == focus_rule_label
    ]
    if len(train) < max(min_cluster_size * 2, 8):
        raise ValueError(f"Need more training errors (have {len(train)}).")

    vectorizer = DictVectorizer(sparse=False)
    scaler = StandardScaler()
    x_train = scaler.fit_transform(vectorizer.fit_transform([_model_features(o) for o in train]))
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=max(2, min_cluster_size // 2),
        cluster_selection_method="leaf",
        copy=True,
    )
    labels = model.fit_predict(x_train)

    cluster_ids = sorted(int(v) for v in set(labels) if v != -1)
    if not cluster_ids:
        return {
            "cutoff": cutoff,
            "training_errors": len(train),
            "training_errors_before_focus": len(train_all),
            "holdout_errors": len(holdout),
            "focus_rule_label": focus_rule_label,
            "clusters": [],
            "holdout_matches": [],
            "noise_errors": int((labels == -1).sum()),
            "message": "No stable clusters found.",
        }

    silhouette = None
    clustered_mask = labels != -1
    clustered_labels = labels[clustered_mask]
    if len(set(clustered_labels)) > 1 and clustered_mask.sum() > len(set(clustered_labels)):
        silhouette = float(silhouette_score(x_train[clustered_mask], clustered_labels))

    cluster_models: Dict[int, Dict[str, Any]] = {}
    clusters: List[Dict[str, Any]] = []
    for cid in cluster_ids:
        indexes = np.where(labels == cid)[0]
        points = x_train[indexes]
        centroid = points.mean(axis=0)
        distances = np.linalg.norm(points - centroid, axis=1)
        radius = float(max(np.percentile(distances, 95), 0.75))
        members = [train[i] for i in indexes]
        family = _mode(o.features["error_family"] for o in members)
        family_count = sum(o.features["error_family"] == family for o in members)
        cluster_models[cid] = {
            "centroid": centroid,
            "radius": radius,
            "family": family,
        }
        clusters.append({
            "cluster_id": cid,
            "name": family,
            "training_occurrences": len(members),
            "family_purity": round(family_count / len(members), 3),
            "median_eval_drop_cp": int(np.median([o.eval_drop_cp for o in members])),
            "radius": round(radius, 3),
            "label_evidence": _label_evidence(members),
            "examples": [_example(o) for o in sorted(members, key=lambda x: -x.eval_drop_cp)[:3]],
        })
        clusters[-1]["decision_context"] = decision_context_from_cluster(clusters[-1])

    matches: List[Dict[str, Any]] = []
    if holdout:
        x_holdout = scaler.transform(vectorizer.transform([_model_features(o) for o in holdout]))
        for obs, point in zip(holdout, x_holdout):
            ranked = sorted(
                (
                    float(np.linalg.norm(point - cm["centroid"])) / cm["radius"],
                    cid,
                )
                for cid, cm in cluster_models.items()
            )
            normalized_distance, cid = ranked[0]
            if normalized_distance > 1.0:
                continue
            expected_family = cluster_models[cid]["family"]
            matches.append({
                **_example(obs),
                "cluster_id": cid,
                "pattern": expected_family,
                "normalized_distance": round(normalized_distance, 3),
                "rule_agrees": obs.features["error_family"] == expected_family,
            })

    by_cluster = Counter(m["cluster_id"] for m in matches)
    for cluster in clusters:
        cluster_matches = [m for m in matches if m["cluster_id"] == cluster["cluster_id"]]
        later_agreements = sum(bool(m["rule_agrees"]) for m in cluster_matches)
        later_agreement = (
            later_agreements / len(cluster_matches)
            if cluster_matches else None
        )
        cluster["holdout_recurrences"] = by_cluster[cluster["cluster_id"]]
        cluster["label_validation"] = {
            "specific_chess_cause": cluster["name"] in LABELABLE_ERROR_FAMILIES,
            "training_rule_consistency": cluster["family_purity"],
            "later_matches": len(cluster_matches),
            "later_rule_agreement": round(later_agreement, 3) if later_agreement is not None else None,
            "ready_for_coaching": bool(
                cluster["name"] in LABELABLE_ERROR_FAMILIES
                and cluster["family_purity"] >= MIN_LABEL_PURITY
                and len(cluster_matches) >= MIN_LABEL_HOLDOUT_MATCHES
                and later_agreement is not None
                and later_agreement >= MIN_LABEL_HOLDOUT_AGREEMENT
            ),
        }

    agreement = (
        sum(bool(m["rule_agrees"]) for m in matches) / len(matches)
        if matches else None
    )
    clusters.sort(
        key=lambda c: (c["holdout_recurrences"], c["family_purity"], c["training_occurrences"]),
        reverse=True,
    )
    matches.sort(key=lambda m: (not m["rule_agrees"], m["normalized_distance"]))

    family_rows = []
    families = sorted({o.features["error_family"] for o in train})
    for family in families:
        training_actual = sum(o.features["error_family"] == family for o in train)
        holdout_actual = sum(o.features["error_family"] == family for o in holdout)
        family_observations = [o for o in observations if o.features["error_family"] == family]
        family_train = [o for o in train if o.features["error_family"] == family]
        family_holdout = [o for o in holdout if o.features["error_family"] == family]
        predictions = [m for m in matches if m["pattern"] == family]
        true_positives = sum(bool(m["rule_agrees"]) for m in predictions)
        family_rows.append({
            "family": family,
            "total_occurrences": len(family_observations),
            "training_occurrences": training_actual,
            "holdout_occurrences": holdout_actual,
            "predicted_holdout_matches": len(predictions),
            "true_positive_matches": true_positives,
            "precision": round(true_positives / len(predictions), 3) if predictions else None,
            "recall": round(true_positives / holdout_actual, 3) if holdout_actual else None,
            "cluster_count": sum(c["name"] == family for c in clusters),
            "ready_as_repeat_error": bool(
                family in LABELABLE_ERROR_FAMILIES
                and training_actual >= MIN_FAMILY_PATTERN_TRAINING_OCCURRENCES
                and holdout_actual >= MIN_FAMILY_PATTERN_HOLDOUT_OCCURRENCES
            ),
            "evidence": _label_evidence(family_observations),
            "stable_context": _stable_context(family_train, family_holdout),
            "examples": [
                _example(observation)
                for observation in sorted(family_observations, key=lambda x: -x.eval_drop_cp)[:2]
            ],
        })
    family_rows.sort(
        key=lambda row: (row["true_positive_matches"], row["training_occurrences"]),
        reverse=True,
    )
    return {
        "cutoff": cutoff,
        "training_errors": len(train),
        "training_errors_before_focus": len(train_all),
        "holdout_errors": len(holdout),
        "focus_rule_label": focus_rule_label,
        "clustered_training_errors": int(clustered_mask.sum()),
        "noise_errors": int((labels == -1).sum()),
        "cluster_count": len(clusters),
        "silhouette_score": round(silhouette, 3) if silhouette is not None else None,
        "holdout_match_count": len(matches),
        "holdout_recurrence_rate": round(len(matches) / len(holdout), 3) if holdout else None,
        "holdout_rule_agreement": round(agreement, 3) if agreement is not None else None,
        "clusters": clusters,
        "holdout_matches": matches,
        "family_validation": family_rows,
    }
