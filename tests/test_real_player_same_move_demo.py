"""Build a real-player "same move, different meaning" demo.

This is intentionally opt-in for pytest because it hits the Chess.com public
API and starts Stockfish. Run it directly when you want to refresh the demo:

    python tests/test_real_player_same_move_demo.py

Artifacts written:
    demos/generated/real_player_same_move_demo.json
    demos/generated/real_player_same_move_demo.html
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# This repo has a stale venv on this machine whose interpreter is broken, but
# its site-packages are still usable for local validation.
SITE_PACKAGES = ROOT / "venv" / "Lib" / "site-packages"
if SITE_PACKAGES.exists() and str(SITE_PACKAGES) not in sys.path:
    sys.path.append(str(SITE_PACKAGES))

import chess  # noqa: E402

from chess_psych.blunders import blunder_threshold  # noqa: E402
from chess_psych.stockfish_pool import StockfishPool  # noqa: E402


API_BASE = "https://api.chess.com/pub"
USER_AGENT = "ChessPsych/0.1 real-player-demo"
ARTIFACT_DIR = ROOT / "demos" / "generated"

HIGH_PLAYER = "gothamchess"
LOW_PLAYER = "xqc"

# After: 1. e4 e5 2. Nf3 Nc6 3. Bc4
# Same move for both profiles: 4. g4?
DEMO_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
DEMO_MOVE_UCI = "g2g4"
DEMO_POSITION_NAME = "Italian Game setup after 1.e4 e5 2.Nf3 Nc6 3.Bc4"
ENGINE_DEPTH = 8


@dataclass(frozen=True)
class PlayerSnapshot:
    requested_username: str
    username: str
    name: str
    title: str
    url: str
    followers: Optional[int]
    ratings: dict[str, int]
    best_rating: Optional[int]
    latest_game_date: str
    latest_game_url: str
    latest_archive_url: str


def _json_get(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _stats_ratings(stats: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for public_key, label in [
        ("chess_bullet", "bullet"),
        ("chess_blitz", "blitz"),
        ("chess_rapid", "rapid"),
        ("chess_daily", "daily"),
    ]:
        rating = (((stats.get(public_key) or {}).get("last") or {}).get("rating"))
        if isinstance(rating, int):
            out[label] = rating
    return out


def _date_from_timestamp(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def fetch_player_snapshot(username: str) -> PlayerSnapshot:
    profile = _json_get(f"{API_BASE}/player/{username}")
    canonical = profile.get("username", username)
    stats = _json_get(f"{API_BASE}/player/{canonical}/stats")
    ratings = _stats_ratings(stats)
    best_rating = max(ratings.values()) if ratings else None

    archive_payload = _json_get(f"{API_BASE}/player/{canonical}/games/archives")
    archives = list(archive_payload.get("archives") or [])
    if not archives:
        raise AssertionError(f"No public archives found for {canonical}")

    latest_game = None
    latest_archive = ""
    for archive_url in reversed(archives[-8:]):
        try:
            games_payload = _json_get(archive_url)
        except urllib.error.HTTPError:
            continue
        games = games_payload.get("games") or []
        if not games:
            continue
        latest_game = max(games, key=lambda game: game.get("end_time") or 0)
        latest_archive = archive_url
        break

    if not latest_game or not latest_game.get("end_time"):
        raise AssertionError(f"No dated public games found for {canonical}")

    return PlayerSnapshot(
        requested_username=username,
        username=canonical,
        name=profile.get("name") or canonical,
        title=profile.get("title") or "",
        url=profile.get("url") or f"https://www.chess.com/member/{canonical}",
        followers=profile.get("followers"),
        ratings=ratings,
        best_rating=best_rating,
        latest_game_date=_date_from_timestamp(int(latest_game["end_time"])),
        latest_game_url=latest_game.get("url") or "",
        latest_archive_url=latest_archive,
    )


def _repo_stockfish_path() -> Optional[str]:
    candidates = [
        ROOT / "vendor" / "ChessEngine" / "stockfish-windows-x86-64-sse41-popcnt.exe",
        ROOT / "vendor" / "stockfish" / "stockfish-windows-x86-64-avx2.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def evaluate_demo_move() -> dict[str, Any]:
    board = chess.Board(DEMO_FEN)
    move = chess.Move.from_uci(DEMO_MOVE_UCI)
    if move not in board.legal_moves:
        raise AssertionError(f"{DEMO_MOVE_UCI} is not legal in demo position")

    stockfish_path = os.environ.get("STOCKFISH_PATH") or _repo_stockfish_path()
    sf = StockfishPool(path=stockfish_path) if stockfish_path else StockfishPool()
    sf.start()
    try:
        eval_before = sf.analyse(board, depth=ENGINE_DEPTH)
        san = board.san(move)
        after = board.copy()
        after.push(move)
        eval_after = sf.analyse(after, depth=ENGINE_DEPTH)
    finally:
        sf.close()

    drop = eval_before - eval_after
    if not 100 <= drop <= 300:
        raise AssertionError(
            f"Demo move should be a medium eval drop; got {drop}cp "
            f"(before={eval_before}, after={eval_after})"
        )

    return {
        "position_name": DEMO_POSITION_NAME,
        "fen_before": DEMO_FEN,
        "move_uci": DEMO_MOVE_UCI,
        "move_san": san,
        "engine_depth": ENGINE_DEPTH,
        "eval_before_cp": eval_before,
        "eval_after_cp": eval_after,
        "eval_drop_cp": drop,
    }


def build_verdict(player: PlayerSnapshot, move_eval: dict[str, Any]) -> dict[str, Any]:
    rating = player.best_rating
    threshold = blunder_threshold(rating)
    drop = int(move_eval["eval_drop_cp"])
    is_blunder = drop >= threshold
    if is_blunder:
        severity = "critical"
        headline = f"Blunder for this profile ({drop}cp >= {threshold}cp)"
        body = (
            "At this rating band, a medium evaluation drop is meaningful. "
            "The coach should interrupt and connect the move to any known pattern."
        )
    elif drop >= threshold // 2:
        severity = "warning"
        headline = f"Teachable mistake ({drop}cp below {threshold}cp blunder line)"
        body = (
            "The same move is still worth coaching, but it should not be framed "
            "as a recurring-profile failure for this player."
        )
    else:
        severity = "info"
        headline = f"Minor inaccuracy ({drop}cp below {threshold}cp blunder line)"
        body = "The move is noted quietly to avoid noisy coaching."

    return {
        "username": player.username,
        "rating_used": rating,
        "threshold_cp": threshold,
        "severity": severity,
        "headline": headline,
        "body": body,
    }


def _ratings_text(ratings: dict[str, int]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in ratings.items()) or "none public"


def _board_html(fen: str) -> str:
    placement = fen.split()[0]
    rows = placement.split("/")
    piece_map = {
        "K": "K", "Q": "Q", "R": "R", "B": "B", "N": "N", "P": "P",
        "k": "k", "q": "q", "r": "r", "b": "b", "n": "n", "p": "p",
    }
    cells = []
    for rank_index, row in enumerate(rows):
        file_index = 0
        for char in row:
            if char.isdigit():
                for _ in range(int(char)):
                    light = (rank_index + file_index) % 2 == 0
                    cells.append(f'<div class="sq {"light" if light else "dark"}"></div>')
                    file_index += 1
                continue
            light = (rank_index + file_index) % 2 == 0
            cells.append(
                f'<div class="sq {"light" if light else "dark"}">'
                f"{piece_map.get(char, '')}</div>"
            )
            file_index += 1
    return '<div class="board">' + "".join(cells) + "</div>"


def render_html(data: dict[str, Any]) -> str:
    players = data["players"]
    move_eval = data["move"]
    verdicts = data["verdicts"]

    def card(player_key: str) -> str:
        player = players[player_key]
        verdict = verdicts[player_key]
        title = f"{player.get('title', '')} {player['name']}".strip()
        return f"""
        <section class="card {escape(verdict['severity'])}">
          <div class="eyebrow">{escape(player_key.upper())}</div>
          <h2>{escape(title)}</h2>
          <a href="{escape(player['url'])}">@{escape(player['username'])}</a>
          <dl>
            <div><dt>Ratings</dt><dd>{escape(_ratings_text(player['ratings']))}</dd></div>
            <div><dt>Rating used</dt><dd>{escape(str(verdict['rating_used']))}</dd></div>
            <div><dt>Latest public game</dt><dd>{escape(player['latest_game_date'])}</dd></div>
            <div><dt>Blunder line</dt><dd>{escape(str(verdict['threshold_cp']))}cp</dd></div>
          </dl>
          <div class="verdict">
            <strong>{escape(verdict['headline'])}</strong>
            <p>{escape(verdict['body'])}</p>
          </div>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chess Psych - Same Move, Different Meaning</title>
  <style>
    :root {{
      --ink: #18212f;
      --muted: #657084;
      --paper: #f7f3ea;
      --panel: #ffffff;
      --blue: #2563eb;
      --red: #dc2626;
      --amber: #d97706;
      --green: #047857;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    main {{
      width: min(1180px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 34px 0 44px;
    }}
    header {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 28px;
      align-items: center;
      margin-bottom: 26px;
    }}
    h1 {{
      font-size: 42px;
      line-height: 1.02;
      margin: 0 0 12px;
      letter-spacing: 0;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 18px;
      line-height: 1.45;
      margin: 0;
    }}
    .move-box {{
      background: #111827;
      color: #fff;
      padding: 20px;
      border-radius: 8px;
    }}
    .move-box .san {{
      font-size: 46px;
      font-weight: 800;
      line-height: 1;
    }}
    .move-box p {{
      color: #cbd5e1;
      margin: 10px 0 0;
      line-height: 1.45;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 24px;
      align-items: start;
    }}
    .board-wrap {{
      background: var(--panel);
      border: 1px solid #e5e0d6;
      border-radius: 8px;
      padding: 16px;
    }}
    .board {{
      width: 100%;
      aspect-ratio: 1;
      display: grid;
      grid-template-columns: repeat(8, 1fr);
      border: 2px solid #2f3542;
    }}
    .sq {{
      display: grid;
      place-items: center;
      font-size: 24px;
      font-weight: 800;
      font-family: Georgia, serif;
    }}
    .light {{ background: #f0d9b5; color: #1f2937; }}
    .dark {{ background: #b58863; color: #111827; }}
    .engine {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid #e5e0d6;
      border-top: 5px solid var(--blue);
      border-radius: 8px;
      padding: 20px;
      min-height: 420px;
    }}
    .card.critical {{ border-top-color: var(--red); }}
    .card.warning {{ border-top-color: var(--amber); }}
    .card.info {{ border-top-color: var(--green); }}
    .eyebrow {{
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
      font-weight: 800;
    }}
    h2 {{
      margin: 8px 0 4px;
      font-size: 24px;
      line-height: 1.15;
    }}
    a {{ color: var(--blue); text-decoration: none; font-weight: 700; }}
    dl {{ margin: 20px 0; display: grid; gap: 10px; }}
    dl div {{
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid #ece7dc;
    }}
    dt {{ color: var(--muted); font-size: 13px; }}
    dd {{ margin: 0; font-weight: 700; }}
    .verdict {{
      background: #f8fafc;
      border-left: 4px solid currentColor;
      border-radius: 6px;
      padding: 14px;
      line-height: 1.45;
    }}
    .critical .verdict {{ color: var(--red); }}
    .warning .verdict {{ color: var(--amber); }}
    .info .verdict {{ color: var(--green); }}
    .verdict p {{ color: var(--ink); margin: 8px 0 0; }}
    footer {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 22px;
      line-height: 1.5;
    }}
    @media (max-width: 900px) {{
      header, .layout, .cards {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Same Move. Different Meaning.</h1>
        <p class="subtitle">Chess Psych applies the same engine fact to two real Chess.com profiles, then changes the coaching threshold based on the player.</p>
      </div>
      <div class="move-box">
        <div class="san">{escape(move_eval['move_san'])}</div>
        <p>{escape(move_eval['position_name'])}</p>
      </div>
    </header>
    <section class="layout">
      <div class="board-wrap">
        {_board_html(move_eval['fen_before'])}
        <div class="engine">
          Stockfish depth {escape(str(move_eval['engine_depth']))}: before {escape(str(move_eval['eval_before_cp']))}cp,
          after {escape(str(move_eval['eval_after_cp']))}cp,
          drop {escape(str(move_eval['eval_drop_cp']))}cp.
        </div>
      </div>
      <div class="cards">
        {card('high')}
        {card('low')}
      </div>
    </section>
    <footer>
      Data fetched from the Chess.com public API at {escape(data['fetched_at_utc'])}.
      Latest-game dates are the newest public archive games found for each account.
      Source game links: <a href="{escape(players['high']['latest_game_url'])}">{escape(players['high']['username'])}</a>
      and <a href="{escape(players['low']['latest_game_url'])}">{escape(players['low']['username'])}</a>.
    </footer>
  </main>
</body>
</html>
"""


def build_demo() -> dict[str, Any]:
    high = fetch_player_snapshot(HIGH_PLAYER)
    low = fetch_player_snapshot(LOW_PLAYER)

    if high.best_rating is None or low.best_rating is None:
        raise AssertionError("Both demo players need public ratings")
    if high.best_rating < 2000:
        raise AssertionError(f"{high.username} should be the high-rated profile")
    if low.best_rating >= 1200:
        raise AssertionError(f"{low.username} should remain under 1200 for contrast")

    move_eval = evaluate_demo_move()
    data = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "players": {
            "high": high.__dict__,
            "low": low.__dict__,
        },
        "move": move_eval,
        "verdicts": {
            "high": build_verdict(high, move_eval),
            "low": build_verdict(low, move_eval),
        },
    }

    ARTIFACT_DIR.mkdir(exist_ok=True)
    json_path = ARTIFACT_DIR / "real_player_same_move_demo.json"
    html_path = ARTIFACT_DIR / "real_player_same_move_demo.html"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")
    data["artifact_json"] = str(json_path)
    data["artifact_html"] = str(html_path)
    return data


def test_real_player_same_move_demo() -> None:
    if os.environ.get("RUN_REAL_PLAYER_DEMO") != "1":
        return
    build_demo()


if __name__ == "__main__":
    result = build_demo()
    high = result["players"]["high"]
    low = result["players"]["low"]
    move = result["move"]
    print("Real-player same-move demo built.")
    print(f"  High profile: @{high['username']} ({high['best_rating']}) latest {high['latest_game_date']}")
    print(f"  Low profile : @{low['username']} ({low['best_rating']}) latest {low['latest_game_date']}")
    print(f"  Move        : {move['move_san']} drop={move['eval_drop_cp']}cp")
    print(f"  HTML        : {result['artifact_html']}")
    print(f"  JSON        : {result['artifact_json']}")
