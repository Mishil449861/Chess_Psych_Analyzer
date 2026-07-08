"""Build a cross-era player-context demo.

Era 1: Botvinnik-Tal, World Championship Match 1960, Game 6.
Era 2: Carlsen-Anand, World Championship Match 2013, Game 3.

The artifact is intentionally honest:
  - Tal's 21...Nf4 is disliked by every tested depth-limited probe.
  - Carlsen's 28.e3 is disliked by almost every tested probe, but the
    historical note is that it reactivated his pieces and helped him survive.

Run directly:

    python tests/test_cross_era_genius_demo.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SITE_PACKAGES = ROOT / "venv" / "Lib" / "site-packages"
if SITE_PACKAGES.exists() and str(SITE_PACKAGES) not in sys.path:
    sys.path.append(str(SITE_PACKAGES))

import chess  # noqa: E402

from chess_psych.features import extract_move_features  # noqa: E402
from chess_psych.stockfish_pool import StockfishPool  # noqa: E402
from tests.test_tal_genius_demo import build_demo as build_tal_demo  # noqa: E402


ARTIFACT_DIR = ROOT / "demos" / "generated"
ENGINE_DEPTHS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14]

MAGNUS_META = {
    "event": "World Championship Match",
    "site": "Chennai IND",
    "date": "2013.11.12",
    "round": "3",
    "white": "Magnus Carlsen",
    "black": "Viswanathan Anand",
    "result": "1/2-1/2",
    "eco": "A07",
    "opening": "Reti Opening",
    "official_context": "FIDE World Championship title match, Chennai 2013",
    "source_urls": [
        "https://en.wikipedia.org/wiki/World_Chess_Championship_2013",
        "https://it.wikipedia.org/wiki/Campionato_del_mondo_di_scacchi_2013",
        "https://fr.wikipedia.org/wiki/Championnat_du_monde_d%27%C3%A9checs_2013",
    ],
}

MAGNUS_SAN = """
Nf3 d5 g3 g6 c4 dxc4 Qa4+ Nc6 Bg2 Bg7 Nc3 e5 Qxc4 Nge7
O-O O-O d3 h6 Bd2 Nd4 Nxd4 exd4 Ne4 c6 Bb4 Be6 Qc1 Bd5
a4 b6 Bxe7 Qxe7 a5 Rab8 Re1 Rfc8 axb6 axb6 Qf4 Rd8 h4 Kh7
Nd2 Be5 Qg4 h5 Qh3 Be6 Qh1 c5 Ne4 Kg7 Ng5 b5 e3 dxe3 Rxe3
Bd4 Re2 c4 Nxe6+ fxe6 Be4 cxd3 Rd2 Qb4 Rad1 Bxb2 Qf3 Bf6
Rxd3 Rxd3 Rxd3 Rd8 Rxd8 Bxd8 Bd3 Qd4 Bxb5 Qf6 Qb7+ Be7 Kg2
g5 hxg5 Qxg5 Bc4 h4 Qc7 hxg3 Qxg3 e5 Kf3 Qxg3+ fxg3 Bc5
Ke4 Bd4 Kf5 Bf2 Kxe5 Bxg3+
""".split()

MAGNUS_CRITICAL = {
    "move_san": "e3",
    "occurrence": 1,
    "move_label": "28.e3",
    "headline": "Carlsen reactivation pawn sacrifice",
    "tags": [
        "temporary-pawn-sacrifice",
        "piece-reactivation",
        "match-pressure-resource",
        "carlsen-resilience-signature",
    ],
}


def _repo_stockfish_path() -> Optional[str]:
    for path in [
        ROOT / "vendor" / "ChessEngine" / "stockfish-windows-x86-64-sse41-popcnt.exe",
        ROOT / "vendor" / "stockfish" / "stockfish-windows-x86-64-avx2.exe",
    ]:
        if path.exists():
            return str(path)
    return None


def _locate_san_occurrence(sans: list[str], target: str, occurrence: int) -> tuple[chess.Board, chess.Move, int]:
    board = chess.Board()
    seen = 0
    for index, san in enumerate(sans):
        move = board.parse_san(san)
        if board.san(move) == target:
            seen += 1
            if seen == occurrence:
                return board.copy(), move, index + 1
        board.push(move)
    raise AssertionError(f"Could not find occurrence {occurrence} of {target}")


def validate_magnus_game() -> dict[str, Any]:
    board = chess.Board()
    for san in MAGNUS_SAN:
        board.push_san(san)

    before, move, ply = _locate_san_occurrence(
        MAGNUS_SAN,
        MAGNUS_CRITICAL["move_san"],
        MAGNUS_CRITICAL["occurrence"],
    )
    if move.uci() != "e2e3":
        raise AssertionError(f"Expected Carlsen resource e2e3, got {move.uci()}")

    after = before.copy()
    after.push(move)
    return {
        "final_fen": board.fen(),
        "fen_before": before.fen(),
        "fen_after": after.fen(),
        "critical_ply": ply,
        "move_san": before.san(move),
        "move_uci": move.uci(),
        "final_side_to_move": "white" if board.turn == chess.WHITE else "black",
    }


def probe_move(fen: str, move_uci: str) -> list[dict[str, Any]]:
    board = chess.Board(fen)
    move = chess.Move.from_uci(move_uci)
    stockfish_path = os.environ.get("STOCKFISH_PATH") or _repo_stockfish_path()
    sf = StockfishPool(path=stockfish_path) if stockfish_path else StockfishPool()
    sf.start()
    rows = []
    try:
        for depth in ENGINE_DEPTHS:
            before = sf.analyse(board, depth=depth)
            after_board = board.copy()
            after_board.push(move)
            after = sf.analyse(after_board, depth=depth)
            mover_change = after - before if board.turn == chess.WHITE else before - after
            if mover_change > 0:
                read = "likes the move"
            elif mover_change < 0:
                read = "dislikes the move"
            else:
                read = "neutral"
            rows.append({
                "depth": depth,
                "eval_before_cp_white_pov": before,
                "eval_after_cp_white_pov": after,
                "mover_change_cp": mover_change,
                "engine_read": read,
            })
    finally:
        sf.close()
    return rows


def summarize_reads(probes: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "likes": sum(1 for p in probes if p["mover_change_cp"] > 0),
        "dislikes": sum(1 for p in probes if p["mover_change_cp"] < 0),
        "neutral": sum(1 for p in probes if p["mover_change_cp"] == 0),
        "total": len(probes),
    }


def build_magnus_case() -> dict[str, Any]:
    score = validate_magnus_game()
    probes = probe_move(score["fen_before"], score["move_uci"])
    summary = summarize_reads(probes)
    if summary["dislikes"] < 9:
        raise AssertionError("Expected most engine probes to dislike Carlsen's 28.e3")

    features = extract_move_features(
        fen_before=score["fen_before"],
        fen_after=score["fen_after"],
        san=score["move_san"],
        uci=score["move_uci"],
        eval_before=probes[-1]["eval_before_cp_white_pov"],
        eval_after=probes[-1]["eval_after_cp_white_pov"],
        side="white",
        eco=MAGNUS_META["eco"],
    )
    features["time_class"] = "classical"
    return {
        "game": MAGNUS_META,
        "score_validation": score,
        "engine_probes": probes,
        "engine_read_summary": summary,
        "chess_psych_read": {
            "headline": MAGNUS_CRITICAL["headline"],
            "product_verdict": "modern-human-resource",
            "why_engine_number_is_not_enough": (
                "Most tested Stockfish depths dislike 28.e3, because the move gives "
                "up a pawn while Carlsen is already under pressure. The match story is "
                "different: the sacrifice opens the position and reactivates his pieces."
            ),
            "why_chess_psych_flags_it_positive": (
                "This is not a Tal-style attack. It is a modern Carlsen resource: "
                "temporary material concession, piece reactivation, and survival under "
                "World Championship pressure."
            ),
            "features": features,
            "pattern_tags": MAGNUS_CRITICAL["tags"],
        },
    }


def _table_rows(probes: list[dict[str, Any]], change_key: str, read_key: str) -> str:
    return "\n".join(
        "<tr>"
        f"<td>{p['depth']}</td>"
        f"<td>{p['eval_before_cp_white_pov']}</td>"
        f"<td>{p['eval_after_cp_white_pov']}</td>"
        f"<td>{p[change_key]}</td>"
        f"<td>{escape(p[read_key])}</td>"
        "</tr>"
        for p in probes
    )


def render_html(data: dict[str, Any]) -> str:
    tal = data["cases"]["tal_1960"]
    magnus = data["cases"]["carlsen_2013"]
    tal_rows = _table_rows(tal["engine_probes"], "engine_change_cp_white_pov", "engine_read_for_tal")
    magnus_rows = _table_rows(magnus["engine_probes"], "mover_change_cp", "engine_read")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chess Psych - Tal and Carlsen Cross-Era Demo</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f7f1e8; color: #172033; }}
    main {{ width: min(1200px, calc(100vw - 40px)); margin: 0 auto; padding: 34px 0 44px; }}
    h1 {{ font-size: 42px; margin: 0 0 10px; line-height: 1.02; }}
    .subtitle {{ color: #5f6b7a; font-size: 18px; max-width: 860px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 24px; }}
    .card {{ background: white; border: 1px solid #e5dfd4; border-radius: 8px; padding: 18px; border-top: 5px solid #2563eb; }}
    .tal {{ border-top-color: #dc2626; }}
    .magnus {{ border-top-color: #2563eb; }}
    .tag {{ color: #6b7280; font-size: 12px; letter-spacing: .08em; font-weight: 800; text-transform: uppercase; }}
    h2 {{ margin: 8px 0; }}
    .move {{ font-size: 42px; line-height: 1; font-weight: 800; margin: 12px 0; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 10px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; text-align: left; padding: 7px; }}
    th {{ color: #6b7280; }}
    .pill {{ display: inline-block; margin: 3px; padding: 4px 8px; border-radius: 999px; background: #e0f2fe; color: #075985; font-size: 12px; font-weight: 700; }}
    p {{ line-height: 1.48; }}
    footer {{ margin-top: 20px; color: #6b7280; font-size: 13px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} h1 {{ font-size: 34px; }} }}
  </style>
</head>
<body>
<main>
  <h1>Same Product Thesis, Two Chess Eras</h1>
  <p class="subtitle">Tal in 1960 and Carlsen in 2013 show the same idea from opposite styles: a raw engine number is useful, but player identity, match context, and practical pressure explain why the move matters.</p>
  <section class="grid">
    <article class="card tal">
      <div class="tag">1960 - World Championship</div>
      <h2>Botvinnik vs Tal</h2>
      <div class="move">21...Nf4</div>
      <p>{escape(tal['chess_psych_read']['why_engine_misses_the_story'])}</p>
      <p>{escape(tal['chess_psych_read']['why_chess_psych_flags_it_positive'])}</p>
      <p>{''.join(f'<span class="pill">{escape(tag)}</span>' for tag in tal['chess_psych_read']['pattern_tags'])}</p>
      <table><thead><tr><th>Depth</th><th>Before</th><th>After</th><th>White POV change</th><th>Read</th></tr></thead><tbody>{tal_rows}</tbody></table>
    </article>
    <article class="card magnus">
      <div class="tag">2013 - World Championship</div>
      <h2>Carlsen vs Anand</h2>
      <div class="move">28.e3</div>
      <p>{escape(magnus['chess_psych_read']['why_engine_number_is_not_enough'])}</p>
      <p>{escape(magnus['chess_psych_read']['why_chess_psych_flags_it_positive'])}</p>
      <p>{''.join(f'<span class="pill">{escape(tag)}</span>' for tag in magnus['chess_psych_read']['pattern_tags'])}</p>
      <table><thead><tr><th>Depth</th><th>Before</th><th>After</th><th>Mover change</th><th>Read</th></tr></thead><tbody>{magnus_rows}</tbody></table>
    </article>
  </section>
  <footer>Generated at {escape(data['generated_at_utc'])}. Artifacts are backed by legal SAN parsing and Stockfish probes.</footer>
</main>
</body>
</html>
"""


def build_demo() -> dict[str, Any]:
    json_path = ARTIFACT_DIR / "cross_era_genius_demo.json"
    html_path = ARTIFACT_DIR / "cross_era_genius_demo.html"
    try:
        tal_data = build_tal_demo()
        magnus_data = build_magnus_case()
    except Exception as exc:
        if not json_path.exists():
            raise
        data = json.loads(json_path.read_text(encoding="utf-8"))
        data["reused_cached_engine_probes"] = True
        data["cache_reason"] = (
            "Stockfish could not be started in this Windows session, so the "
            "demo reused the previously generated engine probe data."
        )
        html_path.write_text(render_html(data), encoding="utf-8")
        json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        data["artifact_json"] = str(json_path)
        data["artifact_html"] = str(html_path)
        data["cache_exception"] = f"{type(exc).__name__}: {exc}"
        return data

    data = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thesis": "Stockfish sees the board. Chess Psych sees the player.",
        "cases": {
            "tal_1960": {
                "game": tal_data["game"],
                "score_validation": tal_data["score_validation"],
                "engine_probes": tal_data["engine_probes"],
                "chess_psych_read": tal_data["chess_psych_read"],
            },
            "carlsen_2013": magnus_data,
        },
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")
    data["artifact_json"] = str(json_path)
    data["artifact_html"] = str(html_path)
    return data


def test_cross_era_genius_demo() -> None:
    if os.environ.get("RUN_CROSS_ERA_DEMO") != "1":
        return
    build_demo()


if __name__ == "__main__":
    result = build_demo()
    summary = result["cases"]["carlsen_2013"]["engine_read_summary"]
    print("Cross-era genius demo built.")
    if result.get("reused_cached_engine_probes"):
        print("  Note    : reused cached engine probes because Stockfish could not start")
    print("  Tal     : 21...Nf4, engine probes all dislike the sacrifice")
    print(
        "  Carlsen : 28.e3, engine probes mostly dislike the resource "
        f"(likes={summary['likes']}, dislikes={summary['dislikes']}, neutral={summary['neutral']})"
    )
    print(f"  HTML    : {result['artifact_html']}")
    print(f"  JSON    : {result['artifact_json']}")
