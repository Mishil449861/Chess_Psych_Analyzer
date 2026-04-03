import chess
import chess.engine
import asyncio
import sys

# Windows asyncio fix
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

STOCKFISH_PATH = "C:/ChessEngine/stockfish-windows-x86-64-sse41-popcnt.exe"
DEFAULT_DEPTH = 5


def analyze_and_respond(board_after_user_move: chess.Board, depth: int = DEFAULT_DEPTH, skill_level: int = 10):
    """
    Opens Stockfish ONCE per turn.
    Returns: (engine_move, eval_after_user_move_cp, eval_after_engine_move_cp)
    All evals are in centipawns from White's perspective.
    Returns (None, 0, 0) if the position is already terminal.
    """
    if board_after_user_move.is_game_over():
        return None, 0, 0

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        engine.configure({"Skill Level": skill_level})

        # 1. Evaluate the position AFTER the user's move (before engine replies)
        info_mid = engine.analyse(board_after_user_move, chess.engine.Limit(depth=depth))
        eval_mid = info_mid["score"].white().score(mate_score=10000)

        # 2. Get the engine's response move
        result = engine.play(board_after_user_move, chess.engine.Limit(depth=depth))
        engine_move = result.move

        # 3. Push engine move temporarily to evaluate the resulting position
        board_after_user_move.push(engine_move)
        info_final = engine.analyse(board_after_user_move, chess.engine.Limit(depth=depth))
        eval_final = info_final["score"].white().score(mate_score=10000)
        board_after_user_move.pop()  # Restore board — caller handles push

    return engine_move, eval_mid, eval_final


def quick_evaluate(board: chess.Board, depth: int = DEFAULT_DEPTH) -> int:
    """
    Standalone eval for the opening position of the game
    (called once to seed st.session_state.last_eval).
    """
    if board.is_game_over():
        return 0
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        return info["score"].white().score(mate_score=10000)
