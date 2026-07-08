"""Build the Tal "engine blind spot vs attacking identity" demo.

This uses Botvinnik-Tal, World Championship Match 1960, Game 6.
The critical move is Tal's famous 21...Nf4 knight sacrifice.

Run directly:

    python tests/test_tal_genius_demo.py

Artifacts written:
    demos/generated/tal_genius_demo.json
    demos/generated/tal_genius_demo.html
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
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SITE_PACKAGES = ROOT / "venv" / "Lib" / "site-packages"
if SITE_PACKAGES.exists() and str(SITE_PACKAGES) not in sys.path:
    sys.path.append(str(SITE_PACKAGES))

import chess  # noqa: E402

from chess_psych.features import extract_move_features  # noqa: E402
from chess_psych.stockfish_pool import StockfishPool  # noqa: E402


ARTIFACT_DIR = ROOT / "demos" / "generated"
ENGINE_DEPTHS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14]

GAME_META = {
    "event": "World Championship Match",
    "site": "Moscow URS",
    "date": "1960.03.26",
    "round": "6",
    "white": "Mikhail Botvinnik",
    "black": "Mikhail Tal",
    "result": "0-1",
    "eco": "E69",
    "opening": "King's Indian Defence, Fianchetto Variation",
    "official_context": "FIDE World Championship title match, Moscow 1960",
    "source_urls": [
        "https://en.wikipedia.org/wiki/World_Chess_Championship_1960",
        "https://fr.wikipedia.org/wiki/Championnat_du_monde_d%27%C3%A9checs_1960",
        "https://www.theguardian.com/sport/2024/nov/24/greatest-chess-games-world-championship-history",
    ],
}

GAME_SAN = """
c4 Nf6 Nf3 g6 g3 Bg7 Bg2 O-O d4 d6 Nc3 Nbd7 O-O e5 e4 c6
h3 Qb6 d5 cxd5 cxd5 Nc5 Ne1 Bd7 Nd3 Nxd3 Qxd3 Rfc8 Rb1 Nh5
Be3 Qb4 Qe2 Rc4 Rfc1 Rac8 Kh2 f5 exf5 Bxf5 Ra1 Nf4 gxf4
exf4 Bd2 Qxb2 Rab1 f3 Rxb2 fxe2 Rb3 Rd4 Be1 Be5+ Kg1 Bf4
Nxe2 Rxc1 Nxd4 Rxe1+ Bf1 Be4 Ne2 Be5 f4 Bf6 Rxb7 Bxd5 Rc7
Bxa2 Rxa7 Bc4 Ra8+ Kf7 Ra7+ Ke6 Ra3 d5 Kf2 Bh4+ Kg2 Kd6
Ng3 Bxg3 Bxc4 dxc4 Kxg3 Kd5 Ra7 c3 Rc7 Kd4 Rd7+
""".split()

PREFIX_BEFORE_TAL_MOVE = """
c4 Nf6 Nf3 g6 g3 Bg7 Bg2 O-O d4 d6 Nc3 Nbd7 O-O e5 e4 c6
h3 Qb6 d5 cxd5 cxd5 Nc5 Ne1 Bd7 Nd3 Nxd3 Qxd3 Rfc8 Rb1 Nh5
Be3 Qb4 Qe2 Rc4 Rfc1 Rac8 Kh2 f5 exf5 Bxf5 Ra1
""".split()

TAL_MOVE_SAN = "Nf4"
ACCEPTANCE_LINE_SAN = ["gxf4", "exf4", "Bd2", "Qxb2", "Rab1", "f3"]


def _repo_stockfish_path() -> Optional[str]:
    candidates = [
        ROOT / "vendor" / "ChessEngine" / "stockfish-windows-x86-64-sse41-popcnt.exe",
        ROOT / "vendor" / "stockfish" / "stockfish-windows-x86-64-avx2.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _push_san_sequence(board: chess.Board, sans: list[str]) -> None:
    for san in sans:
        board.push_san(san)


def validate_game_score() -> dict[str, Any]:
    board = chess.Board()
    _push_san_sequence(board, GAME_SAN)

    before = chess.Board()
    _push_san_sequence(before, PREFIX_BEFORE_TAL_MOVE)
    tal_move = before.parse_san(TAL_MOVE_SAN)
    if tal_move.uci() != "h5f4":
        raise AssertionError(f"Expected Tal move h5f4, got {tal_move.uci()}")

    after = before.copy()
    after.push(tal_move)

    accepted = after.copy()
    _push_san_sequence(accepted, ACCEPTANCE_LINE_SAN)

    return {
        "final_fen": board.fen(),
        "final_side_to_move": "black" if board.turn == chess.BLACK else "white",
        "final_position_in_check": board.is_check(),
        "fen_before": before.fen(),
        "fen_after": after.fen(),
        "tal_move_uci": tal_move.uci(),
        "tal_move_san": before.san(tal_move),
        "accepted_line_fen": accepted.fen(),
        "accepted_line_san": " ".join(ACCEPTANCE_LINE_SAN),
    }


def evaluate_tal_move(fen_before: str, tal_move_uci: str) -> list[dict[str, Any]]:
    board = chess.Board(fen_before)
    move = chess.Move.from_uci(tal_move_uci)
    stockfish_path = os.environ.get("STOCKFISH_PATH") or _repo_stockfish_path()
    sf = StockfishPool(path=stockfish_path) if stockfish_path else StockfishPool()
    sf.start()
    rows = []
    try:
        for depth in ENGINE_DEPTHS:
            eval_before = sf.analyse(board, depth=depth)
            after = board.copy()
            after.push(move)
            eval_after = sf.analyse(after, depth=depth)
            rows.append({
                "depth": depth,
                "eval_before_cp_white_pov": eval_before,
                "eval_after_cp_white_pov": eval_after,
                "engine_change_cp_white_pov": eval_after - eval_before,
                "engine_read_for_tal": (
                    "dislikes Tal's move"
                    if eval_after > eval_before
                    else "likes Tal's move"
                ),
            })
    finally:
        sf.close()
    return rows


def build_chess_psych_read(score: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    features = extract_move_features(
        fen_before=score["fen_before"],
        fen_after=score["fen_after"],
        san=score["tal_move_san"],
        uci=score["tal_move_uci"],
        time_spent=None,
        eval_before=probes[-1]["eval_before_cp_white_pov"],
        eval_after=probes[-1]["eval_after_cp_white_pov"],
        side="black",
        eco=GAME_META["eco"],
    )
    features["time_class"] = "classical"
    disliked_count = sum(1 for p in probes if p["engine_change_cp_white_pov"] > 0)

    return {
        "headline": "Tal-style initiative sacrifice",
        "product_verdict": "human-genius",
        "why_engine_misses_the_story": (
            "The engine probe treats 21...Nf4 as worsening Black at every tested "
            "depth, but the move creates a forcing attacking problem that Botvinnik "
            "failed to solve over the board."
        ),
        "why_chess_psych_flags_it_positive": (
            "The move is a knight sacrifice by a known attacking player in a world "
            "championship game. It gives material for initiative, opens forcing lines, "
            "and matches Tal's historical identity: practical pressure over static material."
        ),
        "tested_depths_disliking_tal_move": disliked_count,
        "tested_depth_count": len(probes),
        "features": features,
        "pattern_tags": [
            "sacrifice-for-initiative",
            "forcing-complications",
            "king-pressure",
            "tal-attacking-signature",
        ],
    }


def _board_html(fen: str) -> str:
    rows = fen.split()[0].split("/")
    symbols = {
        "K": "K", "Q": "Q", "R": "R", "B": "B", "N": "N", "P": "P",
        "k": "k", "q": "q", "r": "r", "b": "b", "n": "n", "p": "p",
    }
    cells = []
    for rank, row in enumerate(rows):
        file_index = 0
        for char in row:
            if char.isdigit():
                for _ in range(int(char)):
                    color = "light" if (rank + file_index) % 2 == 0 else "dark"
                    cells.append(f'<div class="sq {color}"></div>')
                    file_index += 1
            else:
                color = "light" if (rank + file_index) % 2 == 0 else "dark"
                cells.append(f'<div class="sq {color}">{symbols[char]}</div>')
                file_index += 1
    return '<div class="board">' + "".join(cells) + "</div>"


def render_html(data: dict[str, Any]) -> str:
    score = data["score_validation"]
    psych = data["chess_psych_read"]
    rows = "\n".join(
        "<tr>"
        f"<td>{p['depth']}</td>"
        f"<td>{p['eval_before_cp_white_pov']}</td>"
        f"<td>{p['eval_after_cp_white_pov']}</td>"
        f"<td>+{p['engine_change_cp_white_pov']}</td>"
        f"<td>{escape(p['engine_read_for_tal'])}</td>"
        "</tr>"
        for p in data["engine_probes"]
    )
    source_links = " ".join(
        f'<a href="{escape(url)}">source {i}</a>'
        for i, url in enumerate(data["game"]["source_urls"], 1)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chess Psych - Tal Genius Demo</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f6f1e8; color: #172033; }}
    main {{ width: min(1180px, calc(100vw - 40px)); margin: 0 auto; padding: 34px 0 46px; }}
    header {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 24px; align-items: end; margin-bottom: 24px; }}
    h1 {{ font-size: 42px; line-height: 1.02; margin: 0 0 12px; }}
    h2 {{ margin: 0 0 10px; }}
    p {{ line-height: 1.48; }}
    .tag {{ color: #6b7280; font-weight: 800; letter-spacing: .08em; font-size: 12px; text-transform: uppercase; }}
    .move {{ background: #111827; color: white; border-radius: 8px; padding: 22px; }}
    .move strong {{ font-size: 54px; display: block; line-height: 1; }}
    .grid {{ display: grid; grid-template-columns: 330px 1fr; gap: 22px; align-items: start; }}
    .panel {{ background: white; border: 1px solid #e5dfd4; border-radius: 8px; padding: 18px; }}
    .board {{ display: grid; grid-template-columns: repeat(8, 1fr); border: 2px solid #293142; aspect-ratio: 1; }}
    .sq {{ display: grid; place-items: center; font-family: Georgia, serif; font-size: 25px; font-weight: 800; }}
    .light {{ background: #f0d9b5; }}
    .dark {{ background: #b58863; }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .engine {{ border-top: 5px solid #dc2626; }}
    .psych {{ border-top: 5px solid #2563eb; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 8px; }}
    th {{ color: #6b7280; }}
    .pill {{ display: inline-block; background: #e0f2fe; color: #075985; padding: 4px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; margin: 3px; }}
    footer {{ color: #6b7280; font-size: 13px; margin-top: 22px; }}
    @media (max-width: 900px) {{ header, .grid, .split {{ grid-template-columns: 1fr; }} h1 {{ font-size: 34px; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="tag">Official world championship game</div>
        <h1>Tal's Sacrifice: Engine Doubt, Human Genius</h1>
        <p>{escape(data['game']['white'])} vs {escape(data['game']['black'])}, {escape(data['game']['event'])} Game {escape(data['game']['round'])}, Moscow 1960. The critical move is Tal's 21...Nf4.</p>
      </div>
      <div class="move">
        <div class="tag">Critical move</div>
        <strong>{escape(score['tal_move_san'])}</strong>
        <p>{escape(psych['headline'])}</p>
      </div>
    </header>
    <section class="grid">
      <div class="panel">
        {_board_html(score['fen_before'])}
        <p><strong>Position before 21...Nf4</strong><br>{escape(score['fen_before'])}</p>
      </div>
      <div class="split">
        <div class="panel engine">
          <h2>Engine-only read</h2>
          <p>{escape(psych['why_engine_misses_the_story'])}</p>
          <table>
            <thead><tr><th>Depth</th><th>Before</th><th>After</th><th>White POV change</th><th>Read</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        <div class="panel psych">
          <h2>Chess Psych read</h2>
          <p>{escape(psych['why_chess_psych_flags_it_positive'])}</p>
          <p><strong>Pattern tags</strong></p>
          <p>{''.join(f'<span class="pill">{escape(tag)}</span>' for tag in psych['pattern_tags'])}</p>
          <p><strong>Published continuation if accepted:</strong><br>{escape(score['accepted_line_san'])}</p>
          <p><strong>Game result:</strong> {escape(data['game']['result'])}</p>
        </div>
      </div>
    </section>
    <footer>
      Built at {escape(data['generated_at_utc'])}. Sources: {source_links}
    </footer>
  </main>
</body>
</html>
"""


def build_demo() -> dict[str, Any]:
    score = validate_game_score()
    probes = evaluate_tal_move(score["fen_before"], score["tal_move_uci"])
    if not all(p["engine_change_cp_white_pov"] > 0 for p in probes):
        raise AssertionError("Expected every tested depth to dislike Tal's move")
    psych = build_chess_psych_read(score, probes)
    data = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "game": GAME_META,
        "score_validation": score,
        "engine_probes": probes,
        "chess_psych_read": psych,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / "tal_genius_demo.json"
    html_path = ARTIFACT_DIR / "tal_genius_demo.html"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")
    data["artifact_json"] = str(json_path)
    data["artifact_html"] = str(html_path)
    return data


def test_tal_genius_demo() -> None:
    if os.environ.get("RUN_TAL_GENIUS_DEMO") != "1":
        return
    build_demo()


if __name__ == "__main__":
    result = build_demo()
    probes = result["engine_probes"]
    print("Tal genius demo built.")
    print(f"  Game : {result['game']['white']} vs {result['game']['black']}, {result['game']['event']} Game {result['game']['round']}")
    print(f"  Move : {result['score_validation']['tal_move_san']} ({result['score_validation']['tal_move_uci']})")
    print(f"  Probe: {len(probes)}/{len(probes)} tested depths disliked the sacrifice")
    print(f"  HTML : {result['artifact_html']}")
    print(f"  JSON : {result['artifact_json']}")
