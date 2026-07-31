"""Compare a basic chess-rule baseline with a supervised coaching classifier.

This experiment uses cached engine-confirmed observations. It never downloads
games or starts Stockfish, so it can be re-run quickly while iterating on
features and labels.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chess_psych.coaching_experiments import run_taxonomy_experiment
from chess_psych.personal_validation import ErrorObservation


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def played_at(game: Dict[str, Any]) -> str:
    return datetime.fromtimestamp(game["end_time"], timezone.utc).isoformat()


def load_observations(username: str, time_class: str, games: int, min_error_cp: int) -> tuple[List[ErrorObservation], str]:
    slug = username.lower()
    generated = ROOT / "demos" / "generated"
    game_rows = sorted(
        read_json(generated / f"{slug}_{time_class}_{games}_games.json"),
        key=lambda game: game.get("end_time") or 0,
    )
    checkpoint = read_json(generated / f"{slug}_{time_class}_analysis.json")
    observations = [
        ErrorObservation(**item)
        for game in game_rows
        for item in checkpoint["games"].get(game["url"], [])
    ]
    filtered = [
        observation for observation in observations
        if observation.eval_drop_cp >= min_error_cp
        and abs(observation.eval_before_cp) < 9000
        and abs(observation.eval_after_cp) < 9000
    ]
    cutoff = played_at(game_rows[int(len(game_rows) * 0.75)])
    return filtered, cutoff


def build(args: argparse.Namespace) -> Dict[str, Any]:
    observations, cutoff = load_observations(
        args.username, args.time_class, args.games, args.min_error_cp,
    )
    result = run_taxonomy_experiment(observations, cutoff=cutoff)
    result["experiment"] = {
        "username": args.username,
        "time_class": args.time_class,
        "games": args.games,
        "minimum_error_cp": args.min_error_cp,
        "split": "chronological 75% train / 25% holdout",
        "input": "cached public Chess.com games and engine-confirmed errors",
    }
    output = Path(args.output) if args.output else ROOT / "demos" / "coaching_model_experiment.json"
    write_json(output, result)
    print(f"Wrote coaching-model experiment to {output}")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("username", nargs="?", default="MishilT")
    p.add_argument("--time-class", default="bullet", choices=["bullet", "blitz", "rapid"])
    p.add_argument("--games", type=int, default=500)
    p.add_argument("--min-error-cp", type=int, default=250)
    p.add_argument("--output")
    return p


if __name__ == "__main__":
    build(parser().parse_args())
