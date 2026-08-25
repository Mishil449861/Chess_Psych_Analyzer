"""Precompute the three public profiles used by the local presentation app."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from build_personal_pattern_demo import build, parser


PROFILES = (
    ("mishilt", "MishilT"),
    ("player_x", "erolmcc"),
    ("gm_reference", "hikaru"),
)


def main() -> int:
    for identifier, username in PROFILES:
        print(f"\n=== Precomputing {identifier} ({username}) ===")
        args = parser().parse_args([
            username,
            "--time-class", "blitz",
            "--allowed-time-controls", "180,300",
            "--max-games", "120",
            "--screen-depth", "8",
            "--confirm-depth", "14",
            "--threads", "1",
            "--hash-mb", "16",
            "--refresh-games",
            "--skip-ai-labels",
            "--output", str(ROOT / "demos" / f"presentation_{identifier}_evidence.json"),
        ])
        build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
