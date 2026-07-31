"""Scan conservative HDBSCAN settings against cached player-error observations.

This is an experiment report, not a model-training command: it reuses the
engine-confirmed observations in demos/generated and keeps the chronological
holdout fixed while comparing clustering settings.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chess_psych.personal_validation import ErrorObservation, validate_patterns


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def played_at(game: dict[str, Any]) -> str:
    return datetime.fromtimestamp(game["end_time"], timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--time-class", default="blitz")
    parser.add_argument("--max-games", type=int, default=500)
    parser.add_argument("--output", default="demos/recent_pattern_experiment.json")
    args = parser.parse_args()

    slug = args.username.lower()
    generated = ROOT / "demos" / "generated"
    games = read_json(generated / f"{slug}_{args.time_class}_{args.max_games}_games.json")
    checkpoint = read_json(generated / f"{slug}_{args.time_class}_analysis.json")
    games = sorted(games, key=lambda item: item.get("end_time", 0))
    cutoff = played_at(games[int(len(games) * 0.75)])

    observations = [
        ErrorObservation(**raw)
        for game in games
        for raw in checkpoint["games"].get(game.get("url") or str(game.get("end_time")), [])
        if abs(raw["eval_before_cp"]) < 9000 and abs(raw["eval_after_cp"]) < 9000
    ]
    runs = []
    for minimum_error_cp in (250, 300, 350, 400):
        selected = [item for item in observations if item.eval_drop_cp >= minimum_error_cp]
        for min_cluster_size in (4, 5, 6, 8, 10):
            if sum(item.played_at < cutoff for item in selected) < min_cluster_size * 2:
                continue
            result = validate_patterns(
                selected, cutoff=cutoff, min_cluster_size=min_cluster_size,
            )
            qualifying = [
                cluster for cluster in result.get("clusters", [])
                if cluster["training_occurrences"] >= 5
                and cluster["family_purity"] >= 0.8
                and cluster["holdout_recurrences"] >= 2
            ]
            runs.append({
                "minimum_error_cp": minimum_error_cp,
                "min_cluster_size": min_cluster_size,
                "cluster_count": result.get("cluster_count", 0),
                "silhouette_score": result.get("silhouette_score"),
                "holdout_matches": result.get("holdout_match_count", 0),
                "holdout_rule_agreement": result.get("holdout_rule_agreement"),
                "qualifying_clusters": qualifying,
            })

    payload = {
        "player": args.username,
        "game_count": len(games),
        "date_range": {"start": played_at(games[0]), "end": played_at(games[-1])},
        "cutoff": cutoff,
        "gates": {
            "minimum_training_occurrences": 5,
            "minimum_family_purity": 0.8,
            "minimum_holdout_recurrences": 2,
        },
        "runs": runs,
    }
    output = ROOT / args.output
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    for run in runs:
        if run["qualifying_clusters"]:
            print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
