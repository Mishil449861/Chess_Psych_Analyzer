import streamlit as st

# MUST BE FIRST
st.set_page_config(layout="wide", page_title="Chess Psych")

# =======================
# CLEAN LIGHT UI
# =======================
st.markdown("""
<style>
header {visibility: hidden;}
footer {visibility: hidden;}

.stApp {
    background-color: #F7F8FA;
    color: #1F2937;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.block-container { padding: 1.5rem 3rem; }

h1 {
    font-size: 1.8rem;
    font-weight: 600;
    color: #111827;
}

.glass-card {
    background: white;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid #E5E7EB;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    margin-bottom: 16px;
}

.clock {
    font-size: 1.5rem;
    font-weight: 600;
    text-align: center;
    padding: 12px;
    border-radius: 10px;
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
}

.clock-label {
    font-size: 0.75rem;
    color: #6B7280;
    text-align: center;
    margin-bottom: 4px;
}

section[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
}

.stButton button {
    background: #2563EB;
    border-radius: 8px;
    color: white;
    font-weight: 600;
    border: none;
}
.stButton button:hover { background: #1D4ED8; }

.insight-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 12px;
    margin-bottom: 10px;
}

.insight-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
}

.insight-move { font-weight: 600; }

.insight-tag {
    font-size: 0.7rem;
    background: #EEF2FF;
    color: #3730A3;
    padding: 3px 6px;
    border-radius: 6px;
}

.insight-text { font-size: 0.9rem; color: #374151; }

.game-over-banner {
    background: #FEF2F2;
    border: 1px solid #FECACA;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
    font-size: 1.1rem;
    font-weight: 600;
    color: #991B1B;
    margin-bottom: 16px;
}
</style>
""", unsafe_allow_html=True)

# =======================
# IMPORTS
# =======================
import streamlit.components.v1 as components
import chess
import time
import os
from engine import analyze_and_respond, quick_evaluate
from psychology import detect_psychology
from llm import generate_explanation

# =======================
# SESSION STATE
# =======================
def _reset_game(time_seconds: int, color: str):
    st.session_state.fen          = chess.STARTING_FEN
    st.session_state.logs         = []
    st.session_state.user_time    = time_seconds
    st.session_state.cpu_time     = time_seconds
    st.session_state.player_color = color
    st.session_state.last_msg     = ""
    st.session_state.prev_deltas  = []
    st.session_state.move_number  = 0
    st.session_state.last_eval    = 0          # centipawns, White's POV, seeded at start
    st.session_state.last_move_ts = None       # timestamp of last move
    st.session_state.game_over    = False
    st.session_state.game_result  = ""

for key, default in [
    ("fen",          chess.STARTING_FEN),
    ("logs",         []),
    ("user_time",    300),
    ("cpu_time",     300),
    ("player_color", "White"),
    ("last_msg",     ""),
    ("prev_deltas",  []),
    ("move_number",  0),
    ("last_eval",    0),
    ("last_move_ts", None),
    ("game_over",    False),
    ("game_result",  ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

def format_time(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"

# =======================
# SIDEBAR
# =======================
with st.sidebar:
    st.title("Match Setup")
    time_control = st.radio("Game Duration", ["1 Min", "3 Min", "5 Min"], index=2)
    time_map     = {"1 Min": 60, "3 Min": 180, "5 Min": 300}
    color_choice = st.radio("Play as", ["White", "Black"])

    if st.button("Start New Game", use_container_width=True):
        _reset_game(time_map[time_control], color_choice)
        st.rerun()

# =======================
# CHESS BOARD COMPONENT
# =======================
COMPONENT_DIR = "custom_chess"
os.makedirs(COMPONENT_DIR, exist_ok=True)

html_code = f"""
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet"
  href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css">
<script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
<script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
</head>
<body style="margin:0;padding:0;overflow:hidden;">
<div id="board" style="width:450px;margin:5px;"></div>
<script>
let board = null;
let game  = null;

function send(msg) {{
    window.parent.postMessage({{ isStreamlitMessage: true, ...msg }}, "*");
}}

window.addEventListener("message", function(e) {{
    if (e.data.type === "streamlit:render") {{
        let fen = e.data.args.fen;
        if (!board) {{
            game = new Chess(fen);
            board = Chessboard('board', {{
                draggable: true,
                position: fen,
                orientation: '{st.session_state.player_color.lower()}',
                pieceTheme: function(piece) {{
                    return 'https://chessboardjs.com/img/chesspieces/wikipedia/' + piece + '.png';
                }},
                onDrop: function(s, t) {{
                    let move = game.move({{from: s, to: t, promotion: 'q'}});
                    if (!move) return 'snapback';
                    send({{ type: "streamlit:setComponentValue", value: s + t }});
                }}
            }});
            send({{ type: "streamlit:setFrameHeight", height: 480 }});
        }} else {{
            game.load(fen);
            board.position(fen);
        }}
    }}
}});

send({{ type: "streamlit:componentReady", apiVersion: 1 }});
</script>
</body>
</html>
"""

with open(os.path.join(COMPONENT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(html_code)

st_board = components.declare_component("board", path=COMPONENT_DIR)

# =======================
# MAIN LAYOUT
# =======================
st.title("Chess Psych")
col1, col2 = st.columns([1.3, 1])

with col1:
    c1, c2 = st.columns(2)
    c1.markdown(f"""
    <div class="glass-card">
        <div class="clock-label">CPU</div>
        <div class="clock">{format_time(st.session_state.cpu_time)}</div>
    </div>""", unsafe_allow_html=True)
    c2.markdown(f"""
    <div class="glass-card">
        <div class="clock-label">YOU</div>
        <div class="clock">{format_time(st.session_state.user_time)}</div>
    </div>""", unsafe_allow_html=True)

    st.caption("Clocks start on first move")

    # Game-over banner
    if st.session_state.game_over:
        st.markdown(f"""
        <div class="game-over-banner">{st.session_state.game_result}</div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    move = st_board(fen=st.session_state.fen, key="board")
    st.markdown('</div>', unsafe_allow_html=True)

# =======================
# MOVE PROCESSING
# =======================
if move and move != st.session_state.last_msg and not st.session_state.game_over:
    st.session_state.last_msg = move

    try:
        board = chess.Board(st.session_state.fen)
        mv    = chess.Move.from_uci(move)

        if mv not in board.legal_moves:
            st.warning("Illegal move received — try again.")
        else:
            # --- Timing ---
            now = time.time()
            move_time = (now - st.session_state.last_move_ts) if st.session_state.last_move_ts else 0.0
            st.session_state.last_move_ts = now

            # --- Push user's move ---
            board.push(mv)
            st.session_state.move_number += 1

            # --- Check for game over after user's move ---
            if board.is_game_over():
                st.session_state.fen       = board.fen()
                st.session_state.game_over = True
                outcome = board.outcome()
                if outcome and outcome.winner is not None:
                    winner = "White" if outcome.winner else "Black"
                    st.session_state.game_result = f"Game Over — {winner} wins!"
                else:
                    st.session_state.game_result = "Game Over — Draw!"
                st.rerun()

            # --- Engine reply + evaluation in ONE Stockfish session ---
            engine_move, eval_mid, eval_final = analyze_and_respond(board, depth=5, skill_level=10)

            if engine_move:
                move_san = board.san(engine_move)
                board.push(engine_move)

                # delta = net centipawn change this full turn (White's POV)
                delta = eval_final - st.session_state.last_eval
                st.session_state.last_eval = eval_final

                # --- Psychology detection (actually called now) ---
                tag, phase = detect_psychology(
                    delta        = delta,
                    prev_deltas  = st.session_state.prev_deltas,
                    move_time    = move_time,
                    move_number  = st.session_state.move_number,
                )
                st.session_state.prev_deltas.append(delta)

                # --- Build complete log entry (all fields populated) ---
                cpu_color = "Black" if st.session_state.player_color == "White" else "White"
                log_data  = {
                    "move":          move_san,
                    "tag":           tag,
                    "phase":         phase,
                    "tactics":       tag,          # psychology tag doubles as tactics label
                    "delta":         delta,
                    "absolute_eval": eval_final,   # centipawns, White's POV
                    "cpu_color":     cpu_color,
                }

                # LLM explanation (all fields now exist)
                log_data["explanation"] = generate_explanation(log_data)
                st.session_state.logs.append(log_data)

                # --- Check game over after engine's move ---
                if board.is_game_over():
                    st.session_state.game_over = True
                    outcome = board.outcome()
                    if outcome and outcome.winner is not None:
                        winner = "White" if outcome.winner else "Black"
                        st.session_state.game_result = f"Game Over — {winner} wins!"
                    else:
                        st.session_state.game_result = "Game Over — Draw!"

            st.session_state.fen = board.fen()
            st.rerun()

    except Exception as e:
        st.error(f"Error processing move: {e}")

# =======================
# THREAT PROFILES PANEL
# =======================
with col2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("### Threat Profiles")

    if not st.session_state.logs:
        st.caption("No analysis yet — make your first move.")
    else:
        for log in reversed(st.session_state.logs[-4:]):
            st.markdown(f"""
            <div class="insight-card">
                <div class="insight-header">
                    <div class="insight-move">{log['move']}</div>
                    <div class="insight-tag">{log['tag']}</div>
                </div>
                <div class="insight-text">{log.get('explanation', '')}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
