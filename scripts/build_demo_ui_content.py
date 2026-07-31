"""Materialize the lightweight, file://-friendly demo content bundle."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def profile(player: Dict[str, Any]) -> Dict[str, Any]:
    cluster = player["selected_cluster"]
    method = player["method"]
    return {
        "name": player["display_name"],
        "rating": player["rating"],
        "band": player["band"],
        "label": player.get("display_label", player["ai_label"]["evidence_label"]),
        "recommendation": player["recommendation"],
        "facts": [
            {"value": method["games"], "label": "public 3/5-minute games"},
            {"value": cluster["training_occurrences"], "label": "older similar errors found"},
            {
                "value": f"{method['holdout_rule_agreements']}/{method['holdout_predictions']}",
                "label": f"later matches agreed; {method['holdout_errors']} later flags scanned",
            },
        ],
        "clusters": player["cluster_table"],
    }


def build() -> None:
    cohort = read_json(ROOT / "demos" / "same_mistake_cohort_evidence.json")
    benchmark_source = cohort["shared_benchmark"]["source_player"]
    benchmark_match = benchmark_source["representative_holdout_match"]
    data = {
        "title": cohort["title"],
        "subtitle": "One fixed reference move. Three evidence-backed coaching reads.",
        "claim_boundary": cohort["claim_boundary"],
        "benchmark": {
            "source_name": benchmark_source["display_name"],
            "move": benchmark_match["move"],
            "best_move": benchmark_match["best_move"],
            "eval_drop_cp": benchmark_match["eval_drop_cp"],
            "replay": benchmark_source["replay"],
            "game_url": benchmark_match["game_url"],
            "scope": cohort["shared_benchmark"]["scope"],
        },
        "trust_controls": cohort["trust_controls"],
        "players": [profile(player) for player in cohort["players"]],
    }
    output = ROOT / "demos" / "demo_content.js"
    output.write_text(
        "window.CHESS_PSYCH_DEMO = " + json.dumps(data, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    build()
