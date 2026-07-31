"""Chronological validation for a player's recurring error patterns.

This module is deliberately separate from the presentation layer. It turns
engine-confirmed mistakes into structured observations, learns patterns only
from older games, and measures whether those patterns recur in newer games.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
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
    if features["hanging_increase"] > 0:
        return "Leaves a piece loose"
    if features["king_attackers_increase"] >= 2:
        return "King safety"
    if features["material_delta"] <= -3:
        return "Material oversight"
    if features["best_move_is_capture"] and not features["is_capture"]:
        return "Missed tactical capture"
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
        "ignored_recapture": ignored_recapture,
        "previous_move_was_capture": previous_was_capture,
        "same_piece_as_best": played_move.from_square == best_move.from_square,
        "moved_piece_attacked": moved_piece_attacked,
        "moved_piece_defended": moved_piece_defended,
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
        "median_clock_remaining_seconds": round(float(np.median(known_clocks)), 1) if known_clocks else None,
        "median_time_spent_seconds": round(float(np.median(known_spent)), 1) if known_spent else None,
    }


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
        cluster["holdout_recurrences"] = by_cluster[cluster["cluster_id"]]

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
        predictions = [m for m in matches if m["pattern"] == family]
        true_positives = sum(bool(m["rule_agrees"]) for m in predictions)
        family_rows.append({
            "family": family,
            "training_occurrences": training_actual,
            "holdout_occurrences": holdout_actual,
            "predicted_holdout_matches": len(predictions),
            "true_positive_matches": true_positives,
            "precision": round(true_positives / len(predictions), 3) if predictions else None,
            "recall": round(true_positives / holdout_actual, 3) if holdout_actual else None,
            "cluster_count": sum(c["name"] == family for c in clusters),
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
