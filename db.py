"""SQLite schema + connection helpers.

Schema overview:
    users     — one row per (username, source). Holds per-time-class ratings.
    games     — ingested games with time_class as a first-class column.
    moves     — every move with FEN, eval, time_spent.
    blunders  — user mistakes with feature JSON; assigned a cluster_id later.
    patterns  — clusters (the user's "fingerprint" of recurring mistakes).
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config import config

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,
    source        TEXT NOT NULL,
    rating        INTEGER,
    bullet_rating INTEGER,
    blitz_rating  INTEGER,
    rapid_rating  INTEGER,
    daily_rating  INTEGER,
    last_synced   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(username, source)
);

CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    external_id     TEXT,
    user_color      TEXT NOT NULL,
    result          TEXT,
    eco             TEXT,
    opening_name    TEXT,
    user_rating     INTEGER,
    opponent_rating INTEGER,
    time_class      TEXT,
    time_control    TEXT,
    played_at       TEXT,
    pgn             TEXT,
    ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_games_user ON games(user_id);
CREATE INDEX IF NOT EXISTS idx_games_time_class ON games(user_id, time_class);

CREATE TABLE IF NOT EXISTS moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    ply         INTEGER NOT NULL,
    san         TEXT NOT NULL,
    uci         TEXT NOT NULL,
    fen_before  TEXT NOT NULL,
    fen_after   TEXT NOT NULL,
    eval_before INTEGER,
    eval_after  INTEGER,
    time_spent  REAL,
    side        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moves_game ON moves(game_id);

CREATE TABLE IF NOT EXISTS blunders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id       INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    move_id       INTEGER NOT NULL REFERENCES moves(id) ON DELETE CASCADE,
    eval_drop     INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    cluster_id    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_blunders_user ON blunders(user_id);
CREATE INDEX IF NOT EXISTS idx_blunders_cluster ON blunders(user_id, cluster_id);

CREATE TABLE IF NOT EXISTS patterns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cluster_id          INTEGER NOT NULL,
    name                TEXT,
    description         TEXT,
    size                INTEGER NOT NULL,
    example_blunder_ids TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, cluster_id)
);
"""


def init_db(db_path: Optional[Path] = None) -> Path:
    """Create schema if missing. Idempotent. Returns the resolved DB path."""
    path = Path(db_path) if db_path else config.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    log.debug("DB initialized at %s", path)
    return path


@contextmanager
def get_conn(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection with row_factory set, commit on clean exit, rollback on error."""
    path = Path(db_path) if db_path else config.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_or_create_user(
    conn: sqlite3.Connection,
    username: str,
    source: str,
    rating: Optional[int] = None,
    bullet: Optional[int] = None,
    blitz: Optional[int] = None,
    rapid: Optional[int] = None,
    daily: Optional[int] = None,
) -> int:
    """Insert or update a user. Returns user_id. Only updates fields that are not None."""
    row = conn.execute(
        "SELECT id FROM users WHERE username = ? AND source = ?",
        (username, source),
    ).fetchone()

    if row:
        updates, vals = [], []
        for col, val in [
            ("rating", rating), ("bullet_rating", bullet), ("blitz_rating", blitz),
            ("rapid_rating", rapid), ("daily_rating", daily),
        ]:
            if val is not None:
                updates.append(f"{col} = ?")
                vals.append(val)
        if updates:
            vals.append(row["id"])
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", vals)
        return row["id"]

    cur = conn.execute(
        """INSERT INTO users
           (username, source, rating, bullet_rating, blitz_rating,
            rapid_rating, daily_rating)
           VALUES (?,?,?,?,?,?,?)""",
        (username, source, rating, bullet, blitz, rapid, daily),
    )
    return cur.lastrowid


def delete_user_data(conn: sqlite3.Connection, user_id: int) -> None:
    """Cascade-delete a user and all dependent rows."""
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
