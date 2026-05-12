"""Blunder detection.

A blunder is a user move whose eval drop (from the user's POV) exceeds
a rating-calibrated threshold. The threshold scales because "blunder"
is relative: a 100cp drop is catastrophic at 2000 but routine at 1200.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from config import config
from db import get_conn
from features import extract_move_features

log = logging.getLogger(__name__)


def blunder_threshold(rating: Optional[int]) -> int:
    """Centipawn drop that counts as a blunder at a given rating."""
    if rating is None:
        return 200
    if rating < 1200:
        return 300
    if rating < 1600:
        return 200
    if rating < 2000:
        return 150
    return 100


def detect_blunders(
    user_id: int,
    db_path: Optional[Path] = None,
    min_ply: Optional[int] = None,
) -> int:
    """Re-detect blunders for a user. Idempotent: wipes prior blunders first.

    Returns the number of blunders inserted.
    """
    min_ply = min_ply if min_ply is not None else config.blunder_min_ply
    inserted = 0

    with get_conn(db_path) as conn:
        u = conn.execute(
            "SELECT rating FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        rating = u["rating"] if u else None
        threshold = blunder_threshold(rating)
        log.info("Detecting blunders for user_id=%d (rating=%s, threshold=%dcp)",
                 user_id, rating, threshold)

        conn.execute("DELETE FROM blunders WHERE user_id = ?", (user_id,))

        rows = conn.execute(
            """SELECT m.id AS move_id,
                      m.game_id, m.ply, m.san, m.uci,
                      m.fen_before, m.fen_after,
                      m.eval_before, m.eval_after,
                      m.time_spent, m.side,
                      g.user_color, g.eco, g.user_rating, g.time_class
               FROM moves m
               JOIN games g ON m.game_id = g.id
               WHERE g.user_id = ?
                 AND m.side = g.user_color
                 AND m.ply >= ?
                 AND m.eval_before IS NOT NULL
                 AND m.eval_after IS NOT NULL""",
            (user_id, min_ply),
        ).fetchall()

        for r in rows:
            # Eval drop in the user's POV
            if r["side"] == "white":
                drop = r["eval_before"] - r["eval_after"]
            else:
                drop = r["eval_after"] - r["eval_before"]

            # Suppress noise around mate-score positions
            if abs(r["eval_before"]) >= 9000 or abs(r["eval_after"]) >= 9000:
                if abs(drop) > 5000:
                    continue

            if drop < threshold:
                continue

            try:
                feats = extract_move_features(
                    fen_before=r["fen_before"],
                    fen_after=r["fen_after"],
                    san=r["san"],
                    uci=r["uci"],
                    time_spent=r["time_spent"],
                    eval_before=r["eval_before"],
                    eval_after=r["eval_after"],
                    side=r["side"],
                    eco=r["eco"],
                )
                # Time class is a Chess.com-native concept worth carrying
                # through to features for downstream clustering.
                feats["time_class"] = r["time_class"]
            except Exception as e:
                log.warning("Feature extraction failed at move_id=%d: %s",
                            r["move_id"], e)
                continue

            conn.execute(
                """INSERT INTO blunders
                     (user_id, game_id, move_id, eval_drop, features_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, r["game_id"], r["move_id"], drop, json.dumps(feats)),
            )
            inserted += 1

    log.info("Inserted %d blunders for user_id=%d", inserted, user_id)
    return inserted
