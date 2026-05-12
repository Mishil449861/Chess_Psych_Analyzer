"""Centralized configuration loaded from environment variables.

Patterns this demonstrates:
  - All config lives in one place, not scattered through modules.
  - Sensible defaults with explicit overrides via env vars.
  - Type coercion at the boundary (env vars are always strings).
  - Frozen dataclass = config can't be mutated at runtime.
"""
from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        logging.warning("Invalid int for %s=%r, using default %d", key, v, default)
        return default


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_path(key: str, default: Path) -> Path:
    v = os.environ.get(key)
    return Path(v) if v else default


@dataclass(frozen=True)
class Config:
    # Database
    db_path: Path

    # Stockfish
    stockfish_path: Optional[str]
    stockfish_depth: int
    stockfish_threads: int
    stockfish_hash_mb: int

    # Chess.com API
    chesscom_user_agent: str
    chesscom_request_timeout: int
    chesscom_retry_max: int
    chesscom_retry_backoff: float

    # LLM
    ollama_url: str
    ollama_model: str
    ollama_timeout: int

    # Analysis
    blunder_min_ply: int
    cluster_min_size: int

    # Logging
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_path=_env_path(
                "CHESS_PSYCH_DB",
                Path.home() / ".chess_psych" / "data.db",
            ),
            stockfish_path=os.environ.get("STOCKFISH_PATH"),
            stockfish_depth=_env_int("STOCKFISH_DEPTH", 12),
            stockfish_threads=_env_int("STOCKFISH_THREADS", 1),
            stockfish_hash_mb=_env_int("STOCKFISH_HASH_MB", 64),
            chesscom_user_agent=_env_str(
                "CHESSCOM_USER_AGENT",
                "ChessPsych/0.1 (https://github.com/yourname/chess_psych)",
            ),
            chesscom_request_timeout=_env_int("CHESSCOM_TIMEOUT", 30),
            chesscom_retry_max=_env_int("CHESSCOM_RETRY_MAX", 4),
            chesscom_retry_backoff=float(_env_str("CHESSCOM_RETRY_BACKOFF", "1.5")),
            ollama_url=_env_str("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            ollama_model=_env_str("OLLAMA_MODEL", "llama3"),
            ollama_timeout=_env_int("OLLAMA_TIMEOUT", 120),
            blunder_min_ply=_env_int("BLUNDER_MIN_PLY", 6),
            cluster_min_size=_env_int("CLUSTER_MIN_SIZE", 3),
            log_level=_env_str("LOG_LEVEL", "INFO"),
        )


# Singleton — loaded once at import
config = Config.from_env()


def setup_logging(level: Optional[str] = None) -> None:
    """Configure root logger. Idempotent."""
    lvl = (level or config.log_level).upper()
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,  # Allow re-running in notebooks / tests
    )
