"""Persistent Stockfish engine wrapper.

Fixes the original code's pattern of opening/closing Stockfish on every move,
which costs ~200-500ms per call. Use as a context manager:

    with StockfishPool() as sf:
        eval_cp = sf.analyse(board, depth=12)

Path resolution order:
    1. Constructor argument
    2. STOCKFISH_PATH environment variable
    3. Common system locations
    4. PATH fallback (just "stockfish")
"""
import os
import sys
from pathlib import Path
import chess
import chess.engine

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def get_stockfish_path() -> str:
    p = os.environ.get("STOCKFISH_PATH")
    if p and os.path.exists(p):
        return p
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        str(repo_root / "vendor" / "ChessEngine" / "stockfish-windows-x86-64-sse41-popcnt.exe"),
        str(repo_root / "vendor" / "stockfish" / "stockfish-windows-x86-64-avx2.exe"),
        "C:/ChessEngine/stockfish-windows-x86-64-sse41-popcnt.exe",
        "/usr/games/stockfish",
        "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "stockfish"  # let popen_uci raise a clear error if missing


def _env_int(key: str, default: int) -> int:
    value = os.environ.get(key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class StockfishPool:
    """Single persistent Stockfish process. Reuse across many analyses."""

    def __init__(self, path: str = None, skill_level: int = 20,
                 threads: int = None, hash_mb: int = None):
        self.path = path or get_stockfish_path()
        self.skill_level = skill_level
        self.threads = threads if threads is not None else _env_int("STOCKFISH_THREADS", 1)
        self.hash_mb = hash_mb if hash_mb is not None else _env_int("STOCKFISH_HASH_MB", 16)
        self._engine = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    def start(self):
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
            try:
                self._engine.configure({
                    "Skill Level": self.skill_level,
                    "Threads": self.threads,
                    "Hash": self.hash_mb,
                })
            except chess.engine.EngineError:
                # Some Stockfish builds may reject options; ignore and use defaults
                pass

    def close(self):
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def analyse(self, board: chess.Board, depth: int = 12) -> int:
        """Return centipawn score from White's perspective. Mate clamped to ±10000."""
        if self._engine is None:
            self.start()
        info = self._engine.analyse(board, chess.engine.Limit(depth=depth))
        return info["score"].white().score(mate_score=10000)

    def analyse_with_pv(self, board: chess.Board, depth: int = 12, multipv: int = 3) -> list:
        """Get the top-N candidate moves with their evaluations.

        Returns a list of dicts {move, eval_cp, pv} sorted best-first.
        eval_cp is from White's perspective. Returns [] for terminal positions.
        """
        if board.is_game_over():
            return []
        if self._engine is None:
            self.start()
        infos = self._engine.analyse(
            board, chess.engine.Limit(depth=depth), multipv=multipv
        )
        if isinstance(infos, dict):
            infos = [infos]
        results = []
        for info in infos:
            pv = info.get("pv", [])
            if not pv:
                continue
            results.append({
                "move": pv[0],
                "eval_cp": info["score"].white().score(mate_score=10000),
                "pv": pv,
            })
        return results

    def play(self, board: chess.Board, depth: int = 12):
        if self._engine is None:
            self.start()
        return self._engine.play(board, chess.engine.Limit(depth=depth))
