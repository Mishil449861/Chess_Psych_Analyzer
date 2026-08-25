"""Contract tests for the interactive HDBSCAN report section."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_personal_report import build_html  # noqa: E402


class PersonalReportTests(unittest.TestCase):
    def test_hdbscan_cluster_explorer_is_rendered(self) -> None:
        example = {
            "game_url": "https://www.chess.com/game/live/1",
            "fen_before": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "move": "Nf3",
            "opponent_best_reply": "e5",
            "eval_drop_cp": 240,
        }
        cluster = {
            "cluster_id": 0,
            "name": "Leaves a piece loose",
            "training_occurrences": 6,
            "family_purity": 0.833,
            "median_eval_drop_cp": 240,
            "radius": 0.91,
            "label_evidence": {
                "phase_counts": {"middlegame": 5, "opening": 1},
                "piece_counts": {"knight": 4, "bishop": 2},
                "time_context_counts": {"available": 6},
            },
            "examples": [example],
            "holdout_recurrences": 2,
            "label_validation": {"ready_for_coaching": True},
        }
        evidence = {
            "experiment": {
                "username": "PlayerX",
                "games": 80,
                "time_class": "blitz",
                "allowed_time_controls": ["180", "300"],
            },
            "validation": {
                "clusters": [cluster],
                "holdout_matches": [
                    {"cluster_id": 0, "rule_agrees": True, "game_url": "https://www.chess.com/game/live/2"},
                    {"cluster_id": 0, "rule_agrees": True, "game_url": "https://www.chess.com/game/live/3"},
                ],
                "cluster_count": 1,
                "clustered_training_errors": 6,
                "noise_errors": 3,
                "silhouette_score": 0.42,
                "family_validation": [],
                "game_split": {"earlier_games": 60, "later_games": 20},
            },
        }

        rendered = build_html(evidence, "evidence.json")

        self.assertIn("Explore the model's actual clusters", rendered)
        self.assertIn("Actual HDBSCAN cluster 1", rendered)
        self.assertIn("data-cluster='0'", rendered)
        self.assertEqual(rendered.count("class='square"), 64)


if __name__ == "__main__":
    unittest.main()
