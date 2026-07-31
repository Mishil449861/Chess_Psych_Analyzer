"""Measure whether global chess data improves a player's later-game taxonomy model.

The comparison intentionally excludes player identity. All variants are
evaluated only on MishilT's future games, using the same non-leaky feature
set as experiment_coaching_models.py.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chess_psych.coaching_experiments import run_taxonomy_classifier
from chess_psych.personal_validation import ErrorObservation


PROFILES = {
    "erolmcc": 200,
    "campbellshuffle": 200,
    "mishilt": 500,
    "gothamchess": 200,
    "annacramling": 200,
    "chessnetwork": 200,
    "imrosen": 200,
    "hikaru": 200,
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def playable_time(game: Dict[str, Any]) -> str:
    return datetime.fromtimestamp(game["end_time"], timezone.utc).isoformat()


def observations_for(username: str, games: int, min_error_cp: int) -> tuple[List[ErrorObservation], List[Dict[str, Any]]]:
    generated = ROOT / "demos" / "generated"
    game_rows = sorted(
        read_json(generated / f"{username}_bullet_{games}_games.json"),
        key=lambda game: game.get("end_time") or 0,
    )
    checkpoint = read_json(generated / f"{username}_bullet_analysis.json")
    observations = [
        ErrorObservation(**item)
        for game in game_rows
        for item in checkpoint["games"].get(game["url"], [])
    ]
    return [
        o for o in observations
        if o.eval_drop_cp >= min_error_cp
        and abs(o.eval_before_cp) < 9000
        and abs(o.eval_after_cp) < 9000
    ], game_rows


def compact(result: Dict[str, Any]) -> Dict[str, Any]:
    forest = result["random_forest"]
    return {
        "training_errors": result["training_errors"],
        "holdout_errors": result["holdout_errors"],
        "baseline_macro_f1": result["baseline_most_frequent"]["macro_f1"],
        "random_forest_macro_f1": forest["macro_f1"],
        "random_forest_balanced_accuracy": forest["balanced_accuracy"],
        "high_confidence": forest["confidence"],
    }


def build(min_error_cp: int = 250) -> Dict[str, Any]:
    all_observations: Dict[str, List[ErrorObservation]] = {}
    game_rows: Dict[str, List[Dict[str, Any]]] = {}
    for username, games in PROFILES.items():
        all_observations[username], game_rows[username] = observations_for(
            username, games, min_error_cp,
        )

    target = "mishilt"
    target_games = game_rows[target]
    cutoff = playable_time(target_games[int(len(target_games) * 0.75)])
    target_train = [o for o in all_observations[target] if o.played_at < cutoff]
    target_holdout = [o for o in all_observations[target] if o.played_at >= cutoff]
    global_train = [
        observation
        for username, observations in all_observations.items()
        if username != target
        for observation in observations
        if observation.played_at < cutoff
    ]

    personal = run_taxonomy_classifier(target_train, target_holdout, random_state=42)
    global_only = run_taxonomy_classifier(global_train, target_holdout, random_state=43)
    global_plus_personal = run_taxonomy_classifier(
        global_train + target_train, target_holdout, random_state=44,
    )
    return {
        "experiment": {
            "target": "MishilT",
            "time_class": "bullet",
            "minimum_error_cp": min_error_cp,
            "cutoff": cutoff,
            "split": "target player's chronological 75% train / 25% holdout",
            "global_data": "Other public-player errors before the same cutoff; player identity is excluded.",
        },
        "training_sizes": {
            "personal": len(target_train),
            "global_other_players": len(global_train),
            "holdout": len(target_holdout),
        },
        "results": {
            "personal_only": compact(personal),
            "global_only": compact(global_only),
            "global_plus_personal": compact(global_plus_personal),
        },
        "limitations": [
            "Targets are strict rule-derived categories, not independently human-labelled annotations.",
            "This tests broad post-game taxonomy transfer, not player identification or pre-move blunder prediction.",
            "A model is only useful to the product when its individual pattern claim also passes recurrence and evidence gates.",
        ],
    }


if __name__ == "__main__":
    result = build()
    output = ROOT / "demos" / "personalization_model_experiment.json"
    write_json(output, result)
    print(f"Wrote personalization experiment to {output}")
