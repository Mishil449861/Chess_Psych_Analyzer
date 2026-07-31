"""Honest baseline experiments for chess-coaching pattern models.

The target taxonomy comes from strict chess rules, but the classifier is not
given the rule-defining fields. This makes it a useful post-game categorizer
baseline, not a claim that it predicts a blunder before the move is played.
"""
from __future__ import annotations

from collections import Counter
import math
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    precision_recall_fscore_support,
)

from .personal_validation import ErrorObservation


LABELS = (
    "Delayed recapture",
    "Leaves a piece loose",
    "King safety",
    "Material oversight",
    "Missed tactical capture",
    "Other",
)

# These omit the exact conditions that define the labels below. The model can
# learn context around a type of mistake, but cannot simply replay the rule.
NON_LEAKY_FIELDS = (
    "phase",
    "piece",
    "best_piece",
    "time_class",
    "time_context",
    "is_capture",
    "is_check",
    "same_piece_as_best",
    "moved_piece_attacked",
    "moved_piece_defended",
    "hanging_before",
    "moved_piece_value",
    "eval_drop_pawns",
)


def basic_chess_label(features: Dict[str, Any]) -> str:
    """Assign a strict, explainable coaching label from board-rule evidence."""
    if features.get("ignored_recapture"):
        return "Delayed recapture"
    if (features.get("hanging_increase") or 0) > 0:
        return "Leaves a piece loose"
    if (features.get("king_attackers_increase") or 0) >= 2:
        return "King safety"
    if (features.get("material_delta") or 0) <= -3:
        return "Material oversight"
    if features.get("best_move_is_capture") and not features.get("is_capture"):
        return "Missed tactical capture"
    return "Other"


def non_leaky_features(observation: ErrorObservation) -> Dict[str, Any]:
    """Return post-error context without the fields that define its label."""
    return {
        field: observation.features.get(field, "unknown")
        if observation.features.get(field) is not None else "unknown"
        for field in NON_LEAKY_FIELDS
    }


def _scores(y_true: Sequence[str], y_pred: Sequence[str]) -> Dict[str, Any]:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=list(LABELS),
        zero_division=0,
    )
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 3),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 3),
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 3),
        "weighted_f1": round(float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 3),
        "per_label": [
            {
                "label": label,
                "precision": round(float(p), 3),
                "recall": round(float(r), 3),
                "f1": round(float(score), 3),
                "support": int(n),
            }
            for label, p, r, score, n in zip(LABELS, precision, recall, f1, support)
        ],
    }


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> List[float]:
    if not total:
        return [0.0, 0.0]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, center - margin), 3), round(min(1.0, center + margin), 3)]


def _confidence_rows(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    probabilities: np.ndarray,
) -> List[Dict[str, Any]]:
    confidences = probabilities.max(axis=1)
    rows: List[Dict[str, Any]] = []
    for threshold in (0.60, 0.75, 0.90):
        indexes = confidences >= threshold
        coverage = int(indexes.sum())
        correct = int((np.asarray(y_true)[indexes] == np.asarray(y_pred)[indexes]).sum()) if coverage else 0
        rows.append({
            "threshold": threshold,
            "coverage": coverage,
            "coverage_rate": round(float(coverage / len(y_true)), 3) if y_true else 0.0,
            "correct": correct,
            "precision": round(correct / coverage, 3) if coverage else None,
            "precision_ci95": _wilson_interval(correct, coverage) if coverage else None,
        })
    return rows


def run_taxonomy_classifier(
    train: Sequence[ErrorObservation],
    holdout: Sequence[ErrorObservation],
    *,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Fit the taxonomy classifier on an explicit train/holdout split."""
    if not train or not holdout:
        raise ValueError("Need non-empty training and holdout sets.")

    x_train_dict = [non_leaky_features(o) for o in train]
    x_holdout_dict = [non_leaky_features(o) for o in holdout]
    y_train = [basic_chess_label(o.features) for o in train]
    y_holdout = [basic_chess_label(o.features) for o in holdout]

    vectorizer = DictVectorizer(sparse=True)
    x_train = vectorizer.fit_transform(x_train_dict)
    x_holdout = vectorizer.transform(x_holdout_dict)

    baseline = DummyClassifier(strategy="most_frequent")
    baseline.fit(x_train, y_train)
    baseline_predictions = baseline.predict(x_holdout)

    model = RandomForestClassifier(
        n_estimators=400,
        class_weight="balanced_subsample",
        min_samples_leaf=4,
        max_features="sqrt",
        n_jobs=-1,
        random_state=random_state,
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_holdout)
    probabilities = model.predict_proba(x_holdout)

    feature_importance = sorted(
        zip(vectorizer.get_feature_names_out(), model.feature_importances_),
        key=lambda item: item[1],
        reverse=True,
    )[:15]
    return {
        "task": "Post-game broad error taxonomy classification",
        "training_errors": len(train),
        "holdout_errors": len(holdout),
        "labels": list(LABELS),
        "training_label_counts": dict(sorted(Counter(y_train).items())),
        "holdout_label_counts": dict(sorted(Counter(y_holdout).items())),
        "baseline_most_frequent": _scores(y_holdout, baseline_predictions),
        "random_forest": {
            **_scores(y_holdout, predictions),
            "confidence": _confidence_rows(y_holdout, predictions, probabilities),
            "top_features": [
                {"feature": name, "importance": round(float(value), 4)}
                for name, value in feature_importance
            ],
        },
        "limitations": [
            "Labels are strict rule-derived coaching categories, not independent human annotations.",
            "Rule-defining fields are excluded from model inputs, but this is still a post-game categorizer, not a pre-move blunder predictor.",
            "Use this experiment to decide whether labelled human review is worth the next training phase, not as a product accuracy claim.",
        ],
    }


def run_taxonomy_experiment(
    observations: Iterable[ErrorObservation],
    *,
    cutoff: str,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Train on older errors and evaluate taxonomy classification on later ones."""
    observations = list(observations)
    result = run_taxonomy_classifier(
        [o for o in observations if o.played_at < cutoff],
        [o for o in observations if o.played_at >= cutoff],
        random_state=random_state,
    )
    result["cutoff"] = cutoff
    return result
