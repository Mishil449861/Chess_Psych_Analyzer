"""Cluster a user's blunders into recurring patterns.

Pipeline:
  1. Load all blunders for a user.
  2. Vectorize each (one-hot categoricals + log-scaled / clipped numerics).
  3. Standard-scale, then HDBSCAN (density-based — handles variable cluster
     shapes and labels outliers as -1 rather than forcing them into a cluster).
  4. Summarize each cluster mechanically; store to `patterns`; tag each
     blunder with its `cluster_id`.

The LLM polishing step lives in llm_summary.py to keep this module
deterministic and unit-testable.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.preprocessing import StandardScaler

from config import config
from db import get_conn

log = logging.getLogger(__name__)

PHASES = ["opening", "middlegame", "endgame"]
PIECES = ["pawn", "knight", "bishop", "rook", "queen", "king"]
ECO_LETTERS = ["A", "B", "C", "D", "E"]
TIME_CLASSES = ["bullet", "blitz", "rapid", "daily"]


def features_to_vector(feat: Dict[str, Any]) -> np.ndarray:
    """Convert one feature dict to a fixed-length numeric vector."""
    v: List[float] = []

    phase = feat.get("phase", "middlegame")
    v.extend(1.0 if phase == p else 0.0 for p in PHASES)

    piece = feat.get("piece", "pawn")
    v.extend(1.0 if piece == p else 0.0 for p in PIECES)

    eco = (feat.get("eco") or "")[:1]
    v.extend(1.0 if eco == e else 0.0 for e in ECO_LETTERS)

    tc = (feat.get("time_class") or "").lower()
    v.extend(1.0 if tc == t else 0.0 for t in TIME_CLASSES)

    v.append(1.0 if feat.get("is_capture") else 0.0)
    v.append(1.0 if feat.get("is_check") else 0.0)

    v.append(np.log1p(max(feat.get("time_spent", 0) or 0, 0)))
    v.append(min(feat.get("hanging_increase", 0), 5))
    v.append(min(feat.get("king_attackers_increase", 0), 8))
    v.append(max(min(feat.get("material_delta", 0), 10), -15))
    v.append(min(feat.get("eval_drop_cp", 0), 1500) / 100.0)

    return np.array(v, dtype=float)


def _mode(values):
    c = Counter(v for v in values if v is not None)
    return c.most_common(1)[0][0] if c else None


def summarize_cluster(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a deterministic, frequency-based summary of a cluster."""
    feats = [m["features"] for m in members]

    def avg(key: str) -> float:
        return float(np.mean([f.get(key, 0) or 0 for f in feats]))

    piece = _mode(f.get("piece") for f in feats)
    phase = _mode(f.get("phase") for f in feats)
    time_class = _mode(f.get("time_class") for f in feats)
    eco = _mode(f.get("eco") for f in feats)

    avg_hang = avg("hanging_increase")
    avg_king = avg("king_attackers_increase")
    capture_rate = sum(1 for f in feats if f.get("is_capture")) / max(len(feats), 1)
    avg_time = avg("time_spent")
    avg_eval_drop = avg("eval_drop_cp")

    # Default name
    parts = []
    if phase:
        parts.append(phase.capitalize())
    if piece:
        parts.append(f"{piece} mistakes")
    default_name = " — ".join(parts) or "Unclassified pattern"

    # Default description
    bits = []
    if avg_hang > 0.5:
        bits.append("often leaves a piece undefended")
    if avg_king > 0.5:
        bits.append("exposes the king")
    if capture_rate > 0.5:
        bits.append("usually involves a capture")
    if avg_time < 5:
        bits.append("typically played quickly")
    elif avg_time > 30:
        bits.append("usually after long thought")
    if eco:
        bits.append(f"appears in {eco[:1]}-code openings")
    if time_class:
        bits.append(f"most often in {time_class}")
    default_desc = "; ".join(bits) if bits else "no single dominant signal"

    return {
        "name": default_name,
        "description": default_desc,
        "size": len(members),
        "piece": piece,
        "phase": phase,
        "time_class": time_class,
        "eco_letter": eco[:1] if eco else None,
        "avg_eval_drop": avg_eval_drop,
        "avg_time_spent": avg_time,
        "avg_hanging_increase": avg_hang,
        "avg_king_attackers_increase": avg_king,
        "capture_rate": capture_rate,
    }


def cluster_blunders(
    user_id: int,
    db_path: Optional[Path] = None,
    min_cluster_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Run HDBSCAN over a user's blunders and persist clusters as patterns."""
    min_cluster_size = min_cluster_size or config.cluster_min_size

    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT id, features_json FROM blunders WHERE user_id = ?",
            (user_id,),
        ).fetchall()

    n = len(rows)
    log.info("Clustering %d blunders for user_id=%d (min_cluster_size=%d)",
             n, user_id, min_cluster_size)

    if n < min_cluster_size:
        return {
            "clusters": [], "n_blunders": n, "n_noise": 0,
            "message": f"Need >= {min_cluster_size} blunders to cluster (have {n}).",
        }

    blunder_ids = [r["id"] for r in rows]
    feats_list = [json.loads(r["features_json"]) for r in rows]
    X = np.vstack([features_to_vector(f) for f in feats_list])
    X = StandardScaler().fit_transform(X)

    labels = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        copy=True,
    ).fit_predict(X)

    clusters: Dict[int, List[Dict[str, Any]]] = {}
    for bid, label, feats in zip(blunder_ids, labels, feats_list):
        if label == -1:
            continue
        clusters.setdefault(int(label), []).append({"blunder_id": bid, "features": feats})

    cluster_summaries = []
    with get_conn(db_path) as conn:
        conn.execute("UPDATE blunders SET cluster_id = NULL WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM patterns WHERE user_id = ?", (user_id,))

        for cid, members in clusters.items():
            summary = summarize_cluster(members)
            ids = [m["blunder_id"] for m in members]
            conn.executemany(
                "UPDATE blunders SET cluster_id = ? WHERE id = ?",
                [(cid, bid) for bid in ids],
            )
            conn.execute(
                """INSERT INTO patterns
                     (user_id, cluster_id, name, description, size,
                      example_blunder_ids)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, cid, summary["name"], summary["description"],
                 len(members), json.dumps(ids[:5])),
            )
            cluster_summaries.append({
                "cluster_id": cid,
                "size": len(members),
                "summary": summary,
                "example_blunder_ids": ids[:5],
            })

    cluster_summaries.sort(key=lambda x: -x["size"])
    n_noise = int((labels == -1).sum())
    log.info("Clustering done: %d clusters, %d noise points",
             len(cluster_summaries), n_noise)

    return {
        "clusters": cluster_summaries,
        "n_blunders": n,
        "n_noise": n_noise,
    }
