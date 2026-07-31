"""Build a blind player-identification benchmark from cached error data.

The classifier never receives username or rating as a feature. Each sample is
a chronological, non-overlapping block of games summarized by its error mix.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix


PROFILES = [
    {
        "username": "erolmcc", "label": "Weaker player", "bullet_rating": 472,
        "title": None, "games": 200,
    },
    {
        "username": "CampbellShuffle", "label": "Similar rating", "bullet_rating": 1616,
        "title": None, "games": 200,
    },
    {
        "username": "MishilT", "label": "Target profile", "bullet_rating": 1692,
        "title": None, "games": 500,
    },
    {
        "username": "GothamChess", "label": "Titled stronger player", "bullet_rating": 2936,
        "title": "IM", "games": 200,
    },
    {
        "username": "AnnaCramling", "label": "Titled master player", "bullet_rating": 2271,
        "title": "WFM", "games": 200,
    },
    {
        "username": "ChessNetwork", "label": "Titled master player", "bullet_rating": 2739,
        "title": "NM", "games": 200,
    },
    {
        "username": "IMRosen", "label": "Titled stronger player", "bullet_rating": 2778,
        "title": "IM", "games": 200,
    },
    {
        "username": "hikaru", "label": "Titled elite player", "bullet_rating": 3333,
        "title": "GM", "games": 200,
    },
]

FAMILIES = (
    "Delayed recapture", "Leaves a piece loose", "King safety",
    "Material oversight", "Missed tactical capture",
)
PIECES = ("pawn", "knight", "bishop", "rook", "queen", "king")
PHASES = ("opening", "middlegame", "endgame")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def paths_for(profile: Dict[str, Any]) -> Tuple[Path, Path]:
    slug = profile["username"].lower()
    generated = ROOT / "demos" / "generated"
    return (
        generated / f"{slug}_bullet_{profile['games']}_games.json",
        generated / f"{slug}_bullet_analysis.json",
    )


def usable(observation: Dict[str, Any], min_cp: int) -> bool:
    return (
        observation["eval_drop_cp"] >= min_cp
        and abs(observation["eval_before_cp"]) < 9000
        and abs(observation["eval_after_cp"]) < 9000
    )


def window_features(
    game_urls: Sequence[str],
    errors_by_game: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, float]:
    errors = [error for url in game_urls for error in errors_by_game.get(url, [])]
    n = max(len(errors), 1)
    features: Dict[str, float] = {
        "errors_per_game": len(errors) / len(game_urls),
        "mean_eval_drop": float(np.mean([e["eval_drop_cp"] for e in errors])) / 100.0
        if errors else 0.0,
        "median_eval_drop": float(np.median([e["eval_drop_cp"] for e in errors])) / 100.0
        if errors else 0.0,
        "capture_rate": sum(bool(e["features"]["is_capture"]) for e in errors) / n,
        "check_rate": sum(bool(e["features"]["is_check"]) for e in errors) / n,
        "ignored_recapture_rate": sum(bool(e["features"]["ignored_recapture"]) for e in errors) / n,
        "hanging_increase_rate": sum(e["features"]["hanging_increase"] > 0 for e in errors) / n,
        "king_exposure_rate": sum(e["features"]["king_attackers_increase"] > 0 for e in errors) / n,
        "best_capture_rate": sum(bool(e["features"]["best_move_is_capture"]) for e in errors) / n,
    }
    family_counts = Counter(e["features"]["error_family"] for e in errors)
    piece_counts = Counter(e["features"]["piece"] for e in errors)
    phase_counts = Counter(e["features"]["phase"] for e in errors)
    for family in FAMILIES:
        features[f"family:{family}"] = family_counts[family] / n
    for piece in PIECES:
        features[f"piece:{piece}"] = piece_counts[piece] / n
    for phase in PHASES:
        features[f"phase:{phase}"] = phase_counts[phase] / n
    return features


def blocks(values: Sequence[str], size: int) -> List[List[str]]:
    return [list(values[i:i + size]) for i in range(0, len(values) - size + 1, size)]


def wilson_interval(successes: int, total: int, z: float = 1.96) -> List[float]:
    if not total:
        return [0.0, 0.0]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, center - margin), 3), round(min(1.0, center + margin), 3)]


def load_profile(
    profile: Dict[str, Any],
    *,
    block_size: int,
    train_fraction: float,
    min_cp: int,
) -> Dict[str, Any]:
    games_path, analysis_path = paths_for(profile)
    games = sorted(read_json(games_path), key=lambda game: game.get("end_time") or 0)
    analysis = read_json(analysis_path)["games"]
    errors_by_game = {
        url: [error for error in errors if usable(error, min_cp)]
        for url, errors in analysis.items()
    }
    urls = [game["url"] for game in games]
    split = int(len(urls) * train_fraction)
    train_blocks = blocks(urls[:split], block_size)
    test_blocks = blocks(urls[split:], block_size)
    all_errors = [error for url in urls for error in errors_by_game.get(url, [])]
    delayed = [e for e in all_errors if e["features"]["error_family"] == "Delayed recapture"]
    return {
        "profile": profile,
        "train": [window_features(block, errors_by_game) for block in train_blocks],
        "test": [window_features(block, errors_by_game) for block in test_blocks],
        "test_urls": test_blocks,
        "summary": {
            "games": len(urls),
            "severe_errors": len(all_errors),
            "delayed_recaptures": len(delayed),
            "delayed_recaptures_per_100_games": round(len(delayed) / len(urls) * 100, 1),
            "delayed_recapture_share": round(len(delayed) / len(all_errors), 3) if all_errors else 0.0,
        },
    }


def build() -> Dict[str, Any]:
    block_size = 10
    train_fraction = 0.75
    min_cp = 250
    loaded = [
        load_profile(
            profile, block_size=block_size,
            train_fraction=train_fraction,
            min_cp=min_cp,
        )
        for profile in PROFILES
    ]
    min_train = min(len(item["train"]) for item in loaded)
    min_test = min(len(item["test"]) for item in loaded)

    x_train: List[Dict[str, float]] = []
    y_train: List[str] = []
    x_test: List[Dict[str, float]] = []
    y_test: List[str] = []
    test_meta: List[Dict[str, Any]] = []
    for item in loaded:
        username = item["profile"]["username"]
        for features in item["train"][-min_train:]:
            x_train.append(features)
            y_train.append(username)
        for features, urls in zip(item["test"][:min_test], item["test_urls"][:min_test]):
            x_test.append(features)
            y_test.append(username)
            test_meta.append({"actual": username, "game_urls": urls, "features": features})

    vectorizer = DictVectorizer(sparse=False)
    train_matrix = vectorizer.fit_transform(x_train)
    test_matrix = vectorizer.transform(x_test)
    classifier = RandomForestClassifier(
        n_estimators=600,
        max_depth=6,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
    )
    classifier.fit(train_matrix, y_train)
    predicted = classifier.predict(test_matrix)
    probabilities = classifier.predict_proba(test_matrix)
    classes = list(classifier.classes_)

    predictions = []
    for meta, pred, probs in zip(test_meta, predicted, probabilities):
        ranking = sorted(zip(classes, probs), key=lambda item: item[1], reverse=True)
        predictions.append({
            "actual": meta["actual"],
            "predicted": pred,
            "correct": pred == meta["actual"],
            "top_probability": round(float(ranking[0][1]), 3),
            "runner_up": ranking[1][0],
            "runner_up_probability": round(float(ranking[1][1]), 3),
            "game_urls": meta["game_urls"],
        })

    correct = int(sum(p["correct"] for p in predictions))
    labels = [p["username"] for p in PROFILES]
    matrix = confusion_matrix(y_test, predicted, labels=labels).tolist()
    importances = sorted(
        zip(vectorizer.feature_names_, classifier.feature_importances_),
        key=lambda item: item[1],
        reverse=True,
    )[:8]

    # Remove broad skill proxies to test whether tactical composition alone
    # still carries player-specific signal.
    excluded_prefixes = ("phase:",)
    excluded_exact = {"errors_per_game", "mean_eval_drop", "median_eval_drop"}
    pattern_train = [
        {k: v for k, v in row.items() if k not in excluded_exact and not k.startswith(excluded_prefixes)}
        for row in x_train
    ]
    pattern_test = [
        {k: v for k, v in row.items() if k not in excluded_exact and not k.startswith(excluded_prefixes)}
        for row in x_test
    ]
    pattern_vectorizer = DictVectorizer(sparse=False)
    pattern_train_matrix = pattern_vectorizer.fit_transform(pattern_train)
    pattern_test_matrix = pattern_vectorizer.transform(pattern_test)
    pattern_classifier = RandomForestClassifier(
        n_estimators=600,
        max_depth=6,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
    )
    pattern_classifier.fit(pattern_train_matrix, y_train)
    pattern_predicted = pattern_classifier.predict(pattern_test_matrix)
    pattern_correct = int(sum(a == b for a, b in zip(y_test, pattern_predicted)))
    profile_results = []
    for item in loaded:
        username = item["profile"]["username"]
        own = [p for p in predictions if p["actual"].lower() == username.lower()]
        profile_results.append({
            **item["profile"],
            **item["summary"],
            "holdout_windows": len(own),
            "correct_windows": sum(p["correct"] for p in own),
        })

    result = {
        "method": {
            "source": "Chess.com public API",
            "time_class": "bullet",
            "minimum_error_cp": min_cp,
            "block_size_games": block_size,
            "training_fraction": train_fraction,
            "players": len(PROFILES),
            "random_baseline": round(1 / len(PROFILES), 3),
            "leakage_controls": [
                "Chronological split per player",
                "Non-overlapping game windows",
                "Username and rating excluded from model features",
                "Equal training and test windows per player",
            ],
        },
        "result": {
            "training_windows": len(x_train),
            "holdout_windows": len(x_test),
            "correct_windows": correct,
            "accuracy": round(float(accuracy_score(y_test, predicted)), 3),
            "accuracy_95pct_wilson": wilson_interval(correct, len(x_test)),
            "pattern_only_ablation": {
                "removed_features": sorted(excluded_exact) + ["phase:*"],
                "correct_windows": pattern_correct,
                "accuracy": round(float(accuracy_score(y_test, pattern_predicted)), 3),
                "accuracy_95pct_wilson": wilson_interval(pattern_correct, len(x_test)),
            },
            "labels": labels,
            "confusion_matrix": matrix,
            "top_features": [
                {"feature": name, "importance": round(float(value), 4)}
                for name, value in importances
            ],
        },
        "profiles": profile_results,
        "predictions": predictions,
    }
    output = ROOT / "demos" / "cohort_evidence.json"
    write_json(output, result)
    print(json.dumps(result["result"], indent=2))
    print(f"Wrote {output}")
    return result


if __name__ == "__main__":
    build()
