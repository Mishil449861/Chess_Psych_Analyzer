import chess
import chess.engine
import asyncio
import sys

# THE WINDOWS FIX: Force Streamlit to use the modern task manager!
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

STOCKFISH_PATH = "C:/ChessEngine/stockfish-windows-x86-64-sse41-popcnt.exe"

def evaluate_fen(fen):
    # The 'with' statement safely opens AND securely closes Stockfish in one go
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        board = chess.Board(fen)
        result = engine.analyse(board, chess.engine.Limit(depth=5))
        score = result["score"].white().score(mate_score=10000)
        return score

def evaluate(board):
    return evaluate_fen(board.fen())

def get_engine_move(board, depth=5, skill_level=10):
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        engine.configure({"Skill Level": skill_level})
        result = engine.play(board, chess.engine.Limit(depth=depth))
        return result.move