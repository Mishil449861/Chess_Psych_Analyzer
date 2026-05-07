import chess
import chess.engine

STOCKFISH_PATH = "C:/ChessEngine/stockfish-windows-x86-64-sse41-popcnt.exe"
DEFAULT_DEPTH = 12 

class PersistentEngine:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PersistentEngine, cls).__new__(cls)
            cls._instance.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            cls._instance.engine.configure({"Threads": 2, "Hash": 128})
        return cls._instance

    def evaluate_position(self, board: chess.Board, depth: int = DEFAULT_DEPTH) -> int:
        if board.is_game_over():
            return 0
        info = self.engine.analyse(board, chess.engine.Limit(depth=depth))
        return info["score"].white().score(mate_score=10000)

    def close(self):
        if self.engine:
            self.engine.quit()