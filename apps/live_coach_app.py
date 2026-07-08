"""Live coaching demo.

Streamlit app where you play against Stockfish while your personalized
LiveCoach watches every move and flags positions that match your
recurring weakness patterns.

Run:
    streamlit run apps/live_coach_app.py

Prerequisite: at least one user already analyzed via the CLI:
    python -m chess_psych.cli analyze YourUsername --max-games 30
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import chess
import streamlit as st
import streamlit.components.v1 as components

from chess_psych.config import config, setup_logging
from chess_psych.db import get_conn
from chess_psych.live_coach import LiveCoach
from chess_psych.stockfish_pool import StockfishPool

setup_logging("WARNING")

st.set_page_config(
    page_title="Chess Psych — Live Coach",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
st.markdown("""
<style>
    .main { background: #0f1218; color: #e5e7eb; }
    section[data-testid="stSidebar"] { background: #11151c; border-right: 1px solid #1f2937; }
    h1, h2, h3 { color: #f3f4f6; }

    .stat-row { display: flex; justify-content: space-between;
                padding: 8px 12px; background: #1a1f2b;
                border-radius: 8px; margin-bottom: 6px; font-size: 0.9rem; }
    .stat-label { color: #9ca3af; }
    .stat-value { color: #f9fafb; font-weight: 600; }

    .pattern-card { background: #1a1f2b; border-left: 3px solid #6366f1;
                    padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; }
    .pattern-name { font-weight: 600; color: #e0e7ff; font-size: 0.9rem; }
    .pattern-desc { color: #9ca3af; font-size: 0.8rem; margin-top: 4px; line-height: 1.4; }
    .pattern-count { float: right; background: #312e81; color: #c7d2fe;
                     padding: 1px 8px; border-radius: 10px; font-size: 0.75rem; }

    .verdict-critical { background: #2a0f12; border-left: 3px solid #ef4444;
                        color: #fca5a5; padding: 12px; border-radius: 6px;
                        margin-bottom: 6px; }
    .verdict-warning  { background: #2a1f0a; border-left: 3px solid #f59e0b;
                        color: #fcd34d; padding: 12px; border-radius: 6px;
                        margin-bottom: 6px; }
    .verdict-info     { background: #0f1f2a; border-left: 3px solid #3b82f6;
                        color: #93c5fd; padding: 12px; border-radius: 6px;
                        margin-bottom: 6px; }
    .verdict-move { font-weight: 600; color: #f9fafb; }
    .verdict-meta { font-size: 0.75rem; opacity: 0.7; }

    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Session-state setup
# ----------------------------------------------------------------------------
def init_state():
    defaults = {
        "username": "",
        "loaded": False,
        "user_row": None,
        "patterns": [],
        "chess_board": chess.Board(),
        "move_history": [],
        "verdicts": [],
        "coach": None,
        "stockfish": None,
        "player_color": "white",
        "last_move_ts": None,
        "game_over": False,
        "game_result": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# ----------------------------------------------------------------------------
# Sidebar — profile loading & display
# ----------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown("## 🎯 Chess Psych")
        st.caption("Personalized live coach")

        with st.form("load_profile_form"):
            username = st.text_input("Chess.com username",
                                     value=st.session_state.username,
                                     placeholder="e.g. magnuscarlsen")
            load = st.form_submit_button("Load profile", use_container_width=True)

        if load and username.strip():
            try:
                load_profile(username.strip())
            except ValueError as e:
                st.error(str(e))

        if st.session_state.loaded:
            render_profile_panel()
            st.divider()
            render_game_controls()


def load_profile(username: str):
    """Pull patterns + profile from the DB and instantiate a coach."""
    # Tear down prior coach/engine if any
    if st.session_state.stockfish is not None:
        try:
            st.session_state.stockfish.close()
        except Exception:
            pass

    sf = StockfishPool()
    sf.start()

    coach = LiveCoach.for_user(username, source="chess.com", stockfish=sf)

    with get_conn() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND source = ?",
            (coach.username, "chess.com"),
        ).fetchone()

    st.session_state.update({
        "username": coach.username,
        "user_row": dict(user) if user else None,
        "patterns": coach.patterns,
        "coach": coach,
        "stockfish": sf,
        "loaded": True,
        "chess_board": chess.Board(),
        "move_history": [],
        "verdicts": [],
        "last_move_ts": None,
        "game_over": False,
        "game_result": "",
    })


def render_profile_panel():
    user = st.session_state.user_row or {}
    st.markdown(f"### {user.get('username', '?')}")

    with get_conn() as conn:
        n_games = conn.execute(
            "SELECT COUNT(*) AS c FROM games WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["c"]
        n_blunders = conn.execute(
            "SELECT COUNT(*) AS c FROM blunders WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["c"]

    cols = st.columns(2)
    cols[0].metric("Rating", user.get("rating") or "—")
    cols[1].metric("Games", n_games)
    cols2 = st.columns(2)
    cols2[0].metric("Blunders", n_blunders)
    cols2[1].metric("Patterns", len(st.session_state.patterns))

    if st.session_state.patterns:
        st.markdown("##### Watching for")
        for p in st.session_state.patterns[:5]:
            st.markdown(f"""
            <div class="pattern-card">
                <span class="pattern-count">{p.size}×</span>
                <div class="pattern-name">{p.name}</div>
                <div class="pattern-desc">{p.description}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No clustered patterns yet. The coach will still flag blunders.")


def render_game_controls():
    st.markdown("##### New game")
    color = st.radio("Play as", ["white", "black"], horizontal=True,
                     key="color_pick")
    if st.button("▶ Start game", use_container_width=True, type="primary"):
        st.session_state.chess_board = chess.Board()
        st.session_state.move_history = []
        st.session_state.verdicts = []
        st.session_state.player_color = color
        st.session_state.last_move_ts = None
        st.session_state.game_over = False
        st.session_state.game_result = ""
        if st.session_state.coach:
            st.session_state.coach.history = []
        # If user is black, engine moves first
        if color == "black":
            engine_first_move()
        st.rerun()


def engine_first_move():
    board = st.session_state.chess_board
    sf = st.session_state.stockfish
    if board.is_game_over():
        return
    result = sf.play(board, depth=config.stockfish_depth)
    if result.move:
        san = board.san(result.move)
        board.push(result.move)
        st.session_state.move_history.append({
            "side": "engine", "san": san, "uci": result.move.uci(),
        })


# ----------------------------------------------------------------------------
# Chess board component (chessboard.js wrapped in a Streamlit component)
# ----------------------------------------------------------------------------
def board_component():
    """Render the interactive board. Returns the user's UCI move when they drop a piece."""
    component_dir = REPO_ROOT / "web_components" / "chessboard"
    component_dir.mkdir(exist_ok=True)
    html_path = component_dir / "index.html"

    if not html_path.exists():
        html_path.write_text(_BOARD_HTML, encoding="utf-8")

    _component = components.declare_component("chess_board", path=str(component_dir))

    fen = st.session_state.chess_board.fen()
    orientation = st.session_state.player_color
    # Pass the move-history length to force the JS side to re-render when
    # the position changes externally (e.g. after the engine replies).
    return _component(
        fen=fen,
        orientation=orientation,
        position_id=len(st.session_state.move_history),
        key="board_widget",
    )


_BOARD_HTML = """<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet"
    href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css">
  <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
  <script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
  <style>
    body { margin: 0; padding: 0; background: transparent; }
    #board { width: 480px; max-width: 100%; }
  </style>
</head>
<body>
  <div id="board"></div>
<script>
let board = null;
let game = null;
let lastPositionId = -1;
let lastOrientation = null;

function send(value) {
  window.parent.postMessage({
    isStreamlitMessage: true,
    type: "streamlit:setComponentValue",
    value: value,
  }, "*");
}

function ready() {
  window.parent.postMessage({
    isStreamlitMessage: true,
    type: "streamlit:componentReady",
    apiVersion: 1,
  }, "*");
  window.parent.postMessage({
    isStreamlitMessage: true,
    type: "streamlit:setFrameHeight",
    height: 500,
  }, "*");
}

function build(fen, orientation) {
  game = new Chess(fen);
  board = Chessboard('board', {
    draggable: true,
    position: fen,
    orientation: orientation,
    pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png',
    onDragStart: function(source, piece) {
      if (game.game_over()) return false;
      // Don't allow dragging the opponent's pieces
      if ((orientation === 'white' && piece.search(/^b/) !== -1) ||
          (orientation === 'black' && piece.search(/^w/) !== -1)) {
        return false;
      }
    },
    onDrop: function(source, target) {
      const move = game.move({from: source, to: target, promotion: 'q'});
      if (move === null) return 'snapback';
      send({move: source + target + (move.promotion || ''), ts: Date.now()});
    },
  });
}

window.addEventListener("message", function(e) {
  if (e.data.type !== "streamlit:render") return;
  const args = e.data.args;
  const fen = args.fen;
  const orientation = args.orientation;
  const positionId = args.position_id;

  if (board === null || orientation !== lastOrientation) {
    lastOrientation = orientation;
    if (board !== null) board.destroy();
    build(fen, orientation);
  } else if (positionId !== lastPositionId) {
    game.load(fen);
    board.position(fen);
  }
  lastPositionId = positionId;
});

ready();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# Move-handling pipeline
# ----------------------------------------------------------------------------
def process_user_move(move_uci: str):
    """User dropped a piece. Validate, push, score, then let the engine reply."""
    board = st.session_state.chess_board
    try:
        # chessboard.js sends 'e2e4' or 'e7e8q' (with promotion suffix)
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        st.warning(f"Bad move format: {move_uci}")
        return

    if move not in board.legal_moves:
        # Try inferring promotion
        if len(move_uci) == 4:
            promo = chess.Move.from_uci(move_uci + "q")
            if promo in board.legal_moves:
                move = promo
            else:
                st.warning(f"Illegal: {move_uci}")
                return
        else:
            st.warning(f"Illegal: {move_uci}")
            return

    # Timing
    now = time.time()
    time_spent = (now - st.session_state.last_move_ts) if st.session_state.last_move_ts else None
    st.session_state.last_move_ts = now

    board_before = board.copy()
    san = board.san(move)
    board.push(move)

    # Coach evaluates BEFORE engine replies (so the eval is from user's POV)
    verdict = st.session_state.coach.evaluate_move(
        board_before=board_before, move=move, board_after=board,
        time_spent=time_spent,
    )
    st.session_state.move_history.append({"side": "user", "san": san, "uci": move.uci()})
    st.session_state.verdicts.append(verdict)

    if board.is_game_over():
        finalize_game(board)
        return

    # Engine replies
    sf = st.session_state.stockfish
    result = sf.play(board, depth=config.stockfish_depth)
    if result.move:
        engine_san = board.san(result.move)
        board.push(result.move)
        st.session_state.move_history.append({
            "side": "engine", "san": engine_san, "uci": result.move.uci(),
        })

    if board.is_game_over():
        finalize_game(board)


def finalize_game(board: chess.Board):
    outcome = board.outcome()
    st.session_state.game_over = True
    if outcome is None or outcome.winner is None:
        st.session_state.game_result = "Draw"
    else:
        winner = "White" if outcome.winner else "Black"
        st.session_state.game_result = f"{winner} wins"


# ----------------------------------------------------------------------------
# Right-rail coaching feed
# ----------------------------------------------------------------------------
def _render_user_verdict_card(verdict, mv, idx):
    """Render one user move + verdict as a card with rich coaching content."""
    cls = f"verdict-{verdict.severity}"

    # Pattern match badge
    pattern_badge = ""
    if verdict.matched_pattern:
        pattern_badge = (
            f'<span style="background:#312e81;color:#c7d2fe;padding:2px 8px;'
            f'border-radius:10px;font-size:0.7rem;margin-left:8px;'
            f'vertical-align:middle;">⚠ {verdict.matched_pattern.name}</span>'
        )

    # Headline strip
    headline_html = (
        f'<div class="verdict-move">▶ You: {mv["san"]}'
        f'<span style="opacity:0.65;font-weight:normal;font-size:0.85rem;'
        f'margin-left:8px;">— {verdict.headline}</span>{pattern_badge}</div>'
    )

    # The main coaching prose — LLM if available, fall back to position state
    if verdict.coach_note:
        body = (
            f'<div style="margin-top:8px;line-height:1.5;">'
            f'{verdict.coach_note}</div>'
        )
    elif verdict.headline == "Best move":
        body = ('<div style="margin-top:6px;opacity:0.85;">'
                'Top engine choice — keep the pressure on.</div>')
    else:
        body = (f'<div style="margin-top:6px;opacity:0.7;">'
                f'Position: {verdict.position_state}.</div>')

    # Supplementary, structured info: best move / threat / hanging
    supp_items = []
    if verdict.best_move_san and verdict.best_move_san != mv["san"]:
        eval_str = ""
        if verdict.best_move_eval_pawns is not None:
            sign = "+" if verdict.best_move_eval_pawns >= 0 else "−"
            eval_str = f" → {sign}{abs(verdict.best_move_eval_pawns):.1f}"
        supp_items.append(
            f'<span style="opacity:0.85;">💡 Best: '
            f'<b>{verdict.best_move_san}</b>{eval_str}</span>'
        )
    if verdict.opponent_plan:
        supp_items.append(
            f'<span style="opacity:0.85;">⚠ Watch for: '
            f'<b>{verdict.opponent_plan}</b></span>'
        )
    if verdict.your_hanging:
        supp_items.append(
            f'<span style="opacity:0.85;">🩸 Undefended: '
            f'<b>{", ".join(verdict.your_hanging)}</b></span>'
        )
    supp_html = ""
    if supp_items:
        supp_html = (
            '<div style="margin-top:10px;font-size:0.82rem;line-height:1.7;'
            'border-top:1px solid rgba(255,255,255,0.08);padding-top:8px;">'
            + "<br>".join(supp_items) +
            '</div>'
        )

    meta = f'<div class="verdict-meta">move {idx + 1}</div>'

    return f'<div class="{cls}">{headline_html}{body}{supp_html}{meta}</div>'


def render_coach_feed():
    st.markdown("### 🧠 Coach")
    if not st.session_state.loaded:
        st.info("Load a profile in the sidebar to start.")
        return
    if not st.session_state.move_history:
        st.caption("Make a move — the coach is watching.")
        return

    if st.session_state.game_over:
        st.success(f"**{st.session_state.game_result}**")
        st.markdown(f"📋 {st.session_state.coach.game_summary()}")
        st.divider()

    # Walk move history and pair user moves with their verdicts.
    verdict_iter = iter(st.session_state.verdicts)
    items = []
    for i, mv in enumerate(st.session_state.move_history):
        if mv["side"] == "user":
            try:
                v = next(verdict_iter)
            except StopIteration:
                v = None
            items.append(("user", i, mv, v))
        else:
            items.append(("engine", i, mv, None))

    # Show newest at top, last 6 entries (cards are bigger now)
    for kind, idx, mv, v in reversed(items[-6:]):
        if kind == "user" and v is not None:
            st.markdown(_render_user_verdict_card(v, mv, idx), unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="opacity: 0.55; padding: 4px 12px; font-size: 0.85rem;
                        color: #9ca3af; margin-bottom: 6px;">
                ◇ Engine: {mv['san']} <span class="verdict-meta">— move {idx + 1}</span>
            </div>
            """, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Main layout
# ----------------------------------------------------------------------------
render_sidebar()

col_board, col_coach = st.columns([1.4, 1])

with col_board:
    st.markdown("## Play")
    if not st.session_state.loaded:
        st.info("👈 Load a profile from the sidebar to begin.")
    else:
        move = board_component()
        if move and isinstance(move, dict) and "move" in move and not st.session_state.game_over:
            last_handled = st.session_state.get("_last_handled_move")
            move_key = (move.get("move"), move.get("ts"))
            if move_key != last_handled:
                st.session_state["_last_handled_move"] = move_key
                with st.spinner("Coach analyzing your move..."):
                    process_user_move(move["move"])
                st.rerun()

        if st.session_state.game_over:
            st.success(f"**Game over — {st.session_state.game_result}**")

with col_coach:
    render_coach_feed()
