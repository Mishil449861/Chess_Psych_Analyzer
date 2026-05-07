import streamlit as st
import streamlit.components.v1 as components
import chess
import time
import os
from engine import PersistentEngine
from pattern_engine import get_player_profile

st.set_page_config(layout="wide", page_title="Chess Psych")

# --- CSS STYLING ---
st.markdown("""
<style>
.glass-card { background: white; border-radius: 12px; padding: 16px; border: 1px solid #E5E7EB; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin-bottom: 16px; }
.insight-card { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px; padding: 12px; margin-bottom: 10px; border-left: 4px solid #3730A3;}
.insight-text { font-size: 0.9rem; color: #374151; }
.persona-card { background: linear-gradient(135deg, #1E1B4B, #312E81); color: white; border-radius: 16px; padding: 30px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.2); margin-top: 20px;}
.persona-title { font-size: 2.5rem; font-weight: 800; margin-bottom: 5px; color: #E0E7FF;}
.persona-stat { font-size: 1.2rem; color: #A5B4FC; margin-bottom: 20px;}
</style>
""", unsafe_allow_html=True)

# --- CHESSBOARD COMPONENT ---
COMPONENT_DIR = "custom_chess"
html_code = f"""
<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css">
<script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
<script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
</head><body style="margin:0;padding:0;overflow:hidden;">
<div id="board" style="width:450px;margin:5px;"></div>
<script>
let board = null; let game = null;
function send(msg) {{ window.parent.postMessage({{ isStreamlitMessage: true, ...msg }}, "*"); }}
window.addEventListener("message", function(e) {{
    if (e.data.type === "streamlit:render") {{
        let fen = e.data.args.fen;
        if (!board) {{
            game = new Chess(fen);
            board = Chessboard('board', {{
                draggable: true, position: fen, orientation: 'white',
                pieceTheme: function(piece) {{ return 'https://chessboardjs.com/img/chesspieces/wikipedia/' + piece + '.png'; }},
                onDrop: function(s, t) {{
                    let move = game.move({{from: s, to: t, promotion: 'q'}});
                    if (!move) return 'snapback';
                    send({{ type: "streamlit:setComponentValue", value: s + t }});
                }}
            }});
            send({{ type: "streamlit:setFrameHeight", height: 480 }});
        }} else {{ game.load(fen); board.position(fen); }}
    }}
}});
send({{ type: "streamlit:componentReady", apiVersion: 1 }});
</script></body></html>
"""
os.makedirs(COMPONENT_DIR, exist_ok=True)
with open(os.path.join(COMPONENT_DIR, "index.html"), "w", encoding="utf-8") as f: f.write(html_code)
st_board = components.declare_component("board", path=COMPONENT_DIR)

# --- SESSION STATE ---
if "chess_engine" not in st.session_state: st.session_state.chess_engine = PersistentEngine()
if "profile" not in st.session_state: st.session_state.profile = None
if "fen" not in st.session_state: st.session_state.fen = chess.STARTING_FEN
if "game_over" not in st.session_state: st.session_state.game_over = False
if "last_eval" not in st.session_state: st.session_state.last_eval = 0
if "last_msg" not in st.session_state: st.session_state.last_msg = ""

# --- SIDEBAR & SETUP ---
with st.sidebar:
    st.title("Player Setup")
    target_user = st.text_input("Lichess Username", value="EricRosen")
    if st.button("Load Profile & Play", use_container_width=True):
        with st.spinner(f"Analyzing {target_user}'s brain with Qwen..."):
            st.session_state.profile = get_player_profile(target_user)
            st.session_state.fen = chess.STARTING_FEN
            st.session_state.game_over = False
        st.rerun()

# --- MAIN UI ---
st.title("Chess Psych: Live Coaching")

if not st.session_state.profile:
    st.info("👈 Enter a username in the sidebar and click 'Load Profile' to begin.")
    st.stop()

if "error" in st.session_state.profile:
    st.error(st.session_state.profile["error"])
    st.stop()

col1, col2 = st.columns([1.3, 1])

with col1:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    move = st_board(fen=st.session_state.fen, key="board")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("### Known Threat Profiles")
    for insight in st.session_state.profile["insights"]:
        st.markdown(f"""
        <div class="insight-card">
            <b>Target Piece: {insight['piece']}</b><br>
            <span class="insight-text">{insight['text']}</span>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- PHASE 4: END GAME PERSONA CARD ---
if st.session_state.game_over:
    st.markdown(f"""
    <div class="persona-card">
        <div>YOUR CHESS PERSONA</div>
        <div class="persona-title">"{st.session_state.profile['persona_title'].strip('"')}"</div>
        <div class="persona-stat">Based on {st.session_state.profile['total_blunders']} historical blunders</div>
        <p>I watched your game closely. You played better this time, but your core habits remain.</p>
    </div>
    """, unsafe_allow_html=True)

# --- MOVE PROCESSING & PHASE 3 COACHING ---
if move and move != st.session_state.last_msg and not st.session_state.game_over:
    st.session_state.last_msg = move
    board = chess.Board(st.session_state.fen)
    mv = chess.Move.from_uci(move)

    if mv in board.legal_moves:
        piece_moved = board.piece_at(mv.from_square).symbol().upper() if board.piece_at(mv.from_square) else 'P'
        board.push(mv)
        
        # Check user blunder for live coaching
        eval_after_user = st.session_state.chess_engine.evaluate_position(board)
        delta = eval_after_user - st.session_state.last_eval
        
        if delta < -100: 
            for insight in st.session_state.profile["insights"]:
                if insight["piece"] == piece_moved:
                    st.toast(f"🚨 COACH ALERT: That {piece_moved} move matches your historical blindspot! {insight['text']}", icon="⚠️")
        
        if board.is_game_over():
            st.session_state.fen = board.fen()
            st.session_state.game_over = True
            st.rerun()

        # Engine replies
        result = st.session_state.chess_engine.engine.play(board, chess.engine.Limit(time=0.1))
        board.push(result.move)
        st.session_state.last_eval = st.session_state.chess_engine.evaluate_position(board)
        
        if board.is_game_over():
            st.session_state.game_over = True

        st.session_state.fen = board.fen()
        st.rerun()