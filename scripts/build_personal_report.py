"""Create a small file:// report for a single personal-pattern run."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Dict


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_cluster(validation: Dict[str, Any]) -> Dict[str, Any] | None:
    clusters = validation.get("clusters", [])
    if not clusters:
        return None
    return max(
        clusters,
        key=lambda item: (
            item["holdout_recurrences"],
            item["family_purity"],
            item["training_occurrences"],
        ),
    )


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def metrics(cluster: Dict[str, Any], validation: Dict[str, Any]) -> list[tuple[str, str]]:
    matches = [
        item for item in validation["holdout_matches"]
        if item["cluster_id"] == cluster["cluster_id"]
    ]
    agreements = sum(bool(item["rule_agrees"]) for item in matches)
    precision = agreements / len(matches) if matches else None
    return [
        (str(validation["training_errors"]), "training engine flags"),
        (str(cluster["training_occurrences"]), "examples in this cluster"),
        (percent(cluster["family_purity"]), "training rule consistency"),
        (f"{agreements}/{len(matches)}", "later rule agreement"),
        (percent(precision), "selected-cluster precision"),
        (str(validation["noise_errors"]), "training flags left unclustered"),
    ]


def build_html(evidence: Dict[str, Any], source_name: str) -> str:
    experiment = evidence["experiment"]
    validation = evidence["validation"]
    cluster = selected_cluster(validation)
    username = html.escape(experiment["username"])
    if cluster is None:
        body = "<h2>No stable pattern yet</h2><p>The run kept all results as noise rather than inventing a coaching claim. Collect more games and run it again.</p>"
    else:
        label = html.escape(cluster["name"])
        cards = "".join(
            f"<div class='metric'><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span></div>"
            for value, label in metrics(cluster, validation)
        )
        evidence_counts = cluster["label_evidence"]
        phase = ", ".join(f"{html.escape(name)} {count}" for name, count in evidence_counts["phase_counts"].items())
        clock = ", ".join(f"{html.escape(name)} {count}" for name, count in evidence_counts["time_context_counts"].items())
        matches = [item for item in validation["holdout_matches"] if item["cluster_id"] == cluster["cluster_id"]]
        example = next((item for item in matches if item["rule_agrees"]), matches[0] if matches else None)
        game_link = (
            f"<a href='{html.escape(example['game_url'])}' target='_blank' rel='noreferrer'>Open featured public game</a>"
            if example else ""
        )
        body = f"""
        <div class='eyebrow'>Top validated cluster</div>
        <h2>{label}</h2>
        <div class='grid'>{cards}</div>
        <div class='split'><section><h3>Cluster phase</h3><p>{phase or 'No phase data'}</p></section><section><h3>Clock context</h3><p>{clock or 'No clock data'}</p></section></div>
        <p class='boundary'>HDBSCAN grouped board and clock context. Stockfish marked errors first; later games were held out from fitting. This is a coaching hypothesis, not a personality claim.</p>
        <div class='links'>{game_link}<a href='{html.escape(source_name)}' target='_blank'>Open raw evidence JSON</a></div>
        """
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Chess Psych - {username}</title><style>
:root{{--ink:#14213d;--muted:#596579;--paper:#f5f7fa;--line:#d8e0ea;--navy:#174477;--panel:#fff}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Segoe UI,Arial,sans-serif}}main{{width:min(900px,calc(100vw - 32px));margin:0 auto;padding:42px 0}}.eyebrow{{color:var(--muted);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}h1{{margin:8px 0 3px;font-size:38px}}h2{{margin:7px 0 18px;font-size:30px}}.sub{{margin:0 0 25px;color:var(--muted)}}.panel{{padding:24px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}.metric{{min-height:83px;padding:12px;border:1px solid var(--line);border-radius:6px;background:#fbfcfe}}.metric strong{{display:block;color:var(--navy);font-size:22px}}.metric span{{display:block;margin-top:7px;color:var(--muted);font-size:12px;line-height:1.3}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:15px}}.split section{{padding:14px;border-left:4px solid var(--navy);background:#f4f8fc}}.split h3{{margin:0;font-size:13px;text-transform:uppercase;letter-spacing:.06em}}.split p{{margin:7px 0 0;color:var(--muted)}}.boundary{{margin:18px 0 0;color:var(--muted);line-height:1.5}}.links{{display:flex;flex-wrap:wrap;gap:14px;margin-top:17px}}a{{color:var(--navy);font-weight:750;text-decoration:none}}a:hover{{text-decoration:underline}}@media(max-width:600px){{main{{width:calc(100vw - 20px);padding-top:22px}}.grid,.split{{grid-template-columns:1fr}}h1{{font-size:31px}}}}
</style></head><body><main><div class='eyebrow'>Chess Psych personal report</div><h1>{username}</h1><p class='sub'>{experiment['games']} public exact 3/5-minute blitz games. HDBSCAN with a chronological holdout.</p><article class='panel'>{body}</article></main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a file:// report from a personal evidence JSON.")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = read_json(args.evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(evidence, args.evidence.name), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
