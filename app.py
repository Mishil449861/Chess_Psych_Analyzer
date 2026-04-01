import streamlit as st

# MUST BE FIRST
st.set_page_config(layout="wide", page_title="Chess Psych")

# =======================
# 1. CUSTOM CSS (The "Beautiful UI" Upgrade)
# =======================
st.markdown("""
<style>
    /* Hide top header and footer for a cleaner app feel */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Sleek Digital Chess Clocks */
    .chess-clock {
        font-family: 'Courier New', Courier, monospace;
        font-size: 1.8rem;
        font-weight: 900;
        background-color: #1E1E1E;
        color: #00FFAA;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        border: 2px solid #333;
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
        margin-bottom: 20px;
    }
    .clock-title {
        font-size: 0.9rem;
        color: #AAAAAA;
        font-family: sans-serif;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 5px;
    }

    /* Psychological Threat Cards */
    .insight-card {
        background-color: #1a1c23;
        border-left: 5px solid #FF4B4B;
        padding: 15px 20px;
        border-radius: 8px;
        margin-bottom: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s ease-in-out;
    }
    .insight-card:hover {
        transform: translateX(5px);
    }
    .insight-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #333;
        padding-bottom: 8px;
        margin-bottom: 10px;
    }
    .insight-move { 
        font-weight: 800; 
        color: #FFFFFF; 
        font-size: 1.2em; 
    }
    .insight-tag { 
        font-size: 0.85em; 
        color: #FF4B4B; 
        background: rgba(255, 75, 75, 0.1);
        padding: 4px 8px;
        border-radius: 12px;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .insight-text { 
        font-size: 1.05em; 
        line-height: 1.5; 
        color: #D3D3D3; 
    }
    
    /* Eval Bar Styling */
    .stProgress > div > div > div > div {
        background-color: #00FFAA;
    }
</style>
""", unsafe_allow_html=True)

# 2. All other imports
import streamlit.components.v1 as components
import chess
import time
import os
from engine import evaluate, get_engine_move
from psychology import detect_psychology
from llm_async import generate_explanation

# =======================
# 3. INIT STATE
# =======================
if "fen" not in st.session_state: st.session_state.fen = chess.STARTING_FEN
if "logs" not in st.session_state: st.session_state.logs = []
if "eval" not in st.session_state: st.session_state.eval = 0
if "user_time" not in st.session_state: st.session_state.user_time = 300 
if "cpu_time" not in st.session_state: st.session_state.cpu_time = 300
if "last_timestamp" not in st.session_state: st.session_state.last_timestamp = time.time()
if "last_msg" not in st.session_state: st.session_state.last_msg = ""
if "player_color" not in st.session_state: st.session_state.player_color = "White"
if "game_started" not in st.session_state: st.session_state.game_started = False

# Helper function for clock formatting
def format_time(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"

# =======================
# 4. SIDEBAR & SETTINGS
# =======================
with st.sidebar:
    st.title("Match Setup")
    st.markdown("---")
    
    time_control = st.radio("Game Duration", ["1 Min", "3 Min", "5 Min"], index=2)
    time_map = {"1 Min": 60, "3 Min": 180, "5 Min": 300}
    
    color_choice = st.radio("Play as", ["White", "Black"])
    difficulty = st.select_slider("CPU Difficulty", options=["Easy", "Medium", "Hard", "GM"], value="Medium")
    depth_map = {"Easy": 1, "Medium": 5, "Hard": 12, "GM": 20}
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Start New Game", use_container_width=True, type="primary"):
        st.session_state.fen = chess.STARTING_FEN
        st.session_state.logs = []
        st.session_state.eval = 0
        st.session_state.user_time = time_map[time_control]
        st.session_state.cpu_time = time_map[time_control]
        st.session_state.last_timestamp = time.time()
        st.session_state.last_msg = ""
        st.session_state.player_color = color_choice
        st.session_state.game_started = False 
        st.rerun()

# =======================
# 5. AUTO-BUILD COMPONENT
# =======================
COMPONENT_DIR = "custom_chess"
os.makedirs(COMPONENT_DIR, exist_ok=True)

html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js"></script>
    <style> body {{ margin: 0; padding: 0; background-color: transparent; }} </style>
</head>
<body>
    <div id="myBoard" style="width: 500px;"></div>
    <script>
        let board = null;
        let game = null;

        function sendToStreamlit(type, data) {{
            window.parent.postMessage({{ isStreamlitMessage: true, type: type, ...data }}, "*");
        }}

        function setHeight() {{ sendToStreamlit("streamlit:setFrameHeight", {{height: 550}}); }}

        window.addEventListener("message", function(event) {{
            if (event.data.type === "streamlit:render") {{
                let fen = event.data.args.fen;
                
                if (board === null) {{
                    game = new Chess(fen);
                    board = Chessboard('myBoard', {{
                        draggable: true,
                        position: fen,
                        orientation: '{st.session_state.player_color.lower()}',
                        pieceTheme: 'https://cdn.jsdelivr.net/gh/oakmac/chessboardjs@1.0.0/website/img/chesspieces/wikipedia/{{piece}}.png',
                        onDragStart: function(source, piece) {{
                            if (game.game_over()) return false;
                            let playerColor = '{st.session_state.player_color.lower()}';
                            if (playerColor === 'white' && piece.search(/^b/) !== -1) return false;
                            if (playerColor === 'black' && piece.search(/^w/) !== -1) return false;
                        }},
                        onDrop: function(source, target) {{
                            let move = game.move({{from: source, to: target, promotion: 'q'}});
                            if (move === null) return 'snapback';
                            sendToStreamlit("streamlit:setComponentValue", {{value: source + target + "-" + Date.now()}});
                        }},
                        onSnapEnd: function() {{ board.position(game.fen()); }}
                    }});
                    setHeight();
                }} else {{
                    game.load(fen);
                    board.position(fen);
                }}
            }}
        }});
        sendToStreamlit("streamlit:componentReady", {{apiVersion: 1}});
        setHeight();
    </script>
</body>
</html>
"""
with open(os.path.join(COMPONENT_DIR, "index.html"), "w") as f:
    f.write(html_code)

st_chess_board = components.declare_component("st_chess_board", path=COMPONENT_DIR)

# =======================
# 6. ENGINE AUTO-MOVE (If Black)
# =======================
board = chess.Board(st.session_state.fen)
if not st.session_state.game_started and st.session_state.player_color == "Black" and board.turn == chess.WHITE:
    with st.spinner("Computer is opening..."):
        engine_move = get_engine_move(board, depth=depth_map[difficulty])
        board.push(engine_move)
        st.session_state.fen = board.fen()
        st.session_state.eval = evaluate(board)
        st.rerun()

# =======================
# 7. MAIN LAYOUT
# =======================
st.title("Chess Psych Analyzer")

col1, col2 = st.columns([1.2, 1], gap="large")

with col1:
    # Beautiful Digital Clocks
    c_cpu, c_user = st.columns(2)
    c_cpu.markdown(f'<div class="chess-clock"><div class="clock-title">CPU</div>{format_time(st.session_state.cpu_time)}</div>', unsafe_allow_html=True)
    c_user.markdown(f'<div class="chess-clock"><div class="clock-title">YOU ({st.session_state.player_color})</div>{format_time(st.session_state.user_time)}</div>', unsafe_allow_html=True)
    
    if not st.session_state.game_started:
        st.info("Clocks will start when you make your first move.")
        
    user_move_payload = st_chess_board(fen=st.session_state.fen, key="main_board")

    if user_move_payload and user_move_payload != st.session_state.last_msg:
        st.session_state.last_msg = user_move_payload
        move_uci = str(user_move_payload).split('-')[0]
        
        try:
            move = chess.Move.from_uci(move_uci)
            if move in board.legal_moves:
                if not st.session_state.game_started:
                    st.session_state.game_started = True
                    st.session_state.last_timestamp = time.time()
                else:
                    now = time.time()
                    st.session_state.user_time -= (now - st.session_state.last_timestamp)
                
                board.push(move)
                st.session_state.eval = evaluate(board)
                
                if not board.is_game_over() and st.session_state.user_time > 0:
                    with st.spinner("CPU is calculating..."):
                        cpu_start = time.time()
                        eval_before_cpu = st.session_state.eval
                        
                        engine_move = get_engine_move(board, depth=depth_map[difficulty])
                        
                        if engine_move:
                            is_capture = board.is_capture(engine_move)
                            is_castling = board.is_castling(engine_move)
                            
                            san_move = board.san(engine_move) 
                            board.push(engine_move)
                            
                            is_check = board.is_check()
                            cpu_elapsed = time.time() - cpu_start
                            st.session_state.cpu_time -= cpu_elapsed
                            
                            new_eval = evaluate(board)
                            st.session_state.eval = new_eval
                            
                            if st.session_state.player_color == "White": 
                                cpu_delta = eval_before_cpu - new_eval 
                            else: 
                                cpu_delta = new_eval - eval_before_cpu

                            prev_deltas = [l.get('delta', 0) for l in st.session_state.logs]
                            move_number = len(board.move_stack)
                            tag = detect_psychology(cpu_delta, prev_deltas, cpu_elapsed, move_number)
                            phase = "Opening" if move_number < 10 else "Middlegame" if move_number < 30 else "Endgame"
                            
                            tactics = []
                            if is_capture: tactics.append("Capture/Trading material")
                            if is_check: tactics.append("Attacking the King (Check)")
                            if is_castling: tactics.append("Defensive Castling/Securing King")
                            if not tactics: tactics.append("Positional Maneuvering/Developing")
                            
                            # Determine the CPU's color
                            cpu_color = "Black" if st.session_state.player_color == "White" else "White"
                            
                            log = {
                                "move": san_move,
                                "tag": tag,
                                "delta": cpu_delta,
                                "duration": round(cpu_elapsed, 2),
                                "phase": phase,
                                "tactics": ", ".join(tactics), 
                                "absolute_eval": new_eval,     
                                "cpu_color": cpu_color,  # <--- NEW: Give the AI the color!
                                "explanation": ""
                            }
                            
                            log["explanation"] = generate_explanation(log)
                            st.session_state.logs.append(log)

                st.session_state.fen = board.fen()
                st.session_state.last_timestamp = time.time()
                st.rerun()
        except ValueError:
            st.error("Invalid move!")

with col2:
    st.markdown("### Engine Evaluation")
    eval_score = st.session_state.eval if st.session_state.player_color == "White" else -st.session_state.eval
    st.progress(max(min((eval_score + 10) / 20, 1.0), 0.0))
    st.caption("Left = Black Advantage | Right = White Advantage")
    
    st.markdown("### Threat Profiles", unsafe_allow_html=True)
    
    if st.session_state.user_time <= 0:
        st.error("Game Over: You lost on time!")
    elif st.session_state.cpu_time <= 0:
        st.success("Game Over: CPU lost on time!")

    # Render sleek HTML cards instead of clunky expanders
    if not st.session_state.logs:
        st.info("Make a move to generate the first psychological profile.")
    
    for log in reversed(st.session_state.logs[-4:]): # Show last 4 profiles
        st.markdown(f"""
        <div class="insight-card">
            <div class="insight-header">
                <div class="insight-move">{log['move']}</div>
                <div class="insight-tag">{log['tag']}</div>
            </div>
            <div class="insight-text">
                {log['explanation']}
            </div>
        </div>
        """, unsafe_allow_html=True)