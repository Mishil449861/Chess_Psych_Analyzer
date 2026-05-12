"""LLM polishing layer.

Two responsibilities:
  1. Turn a cluster's mechanical summary into a human name + description.
  2. Write the final "cool moment" paragraph introducing the player to
     their own profile.

Both go through the Ollama HTTP endpoint. If Ollama is unreachable, the
mechanical fallbacks from patterns.py are used — the product stays
functional, just less polished.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests

from config import config
from db import get_conn

log = logging.getLogger(__name__)


def ollama_complete(
    prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 300,
) -> str:
    """Returns generated text, or empty string on connection error."""
    try:
        r = requests.post(
            config.ollama_url,
            json={
                "model": config.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=config.ollama_timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        log.warning("Ollama unreachable at %s — falling back to mechanical output",
                    config.ollama_url)
        return ""
    except Exception as e:
        log.exception("Ollama error: %s", e)
        return ""


def name_cluster_with_llm(
    cluster_summary: Dict[str, Any],
    example_features: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """Return (name, description). Falls back to defaults if LLM fails."""
    fallback = (cluster_summary.get("name", "Pattern"),
                cluster_summary.get("description", ""))

    examples_text = ""
    for i, f in enumerate(example_features[:5], 1):
        examples_text += (
            f"  {i}. {f.get('piece','?')} move {f.get('san','?')} — "
            f"phase={f.get('phase','?')}, "
            f"time_spent={f.get('time_spent', 0):.0f}s, "
            f"hanging_change={f.get('hanging_increase', 0)}, "
            f"king_attackers_change={f.get('king_attackers_increase', 0)}, "
            f"eval_drop={f.get('eval_drop_cp', 0)}cp\n"
        )

    prompt = f"""You are a chess coach. Below are {len(example_features)} similar mistakes from a student.
Find the pattern they share and name it.

Cluster stats:
  Occurrences         : {cluster_summary['size']}
  Most common piece   : {cluster_summary.get('piece')}
  Most common phase   : {cluster_summary.get('phase')}
  Most common t-class : {cluster_summary.get('time_class')}
  Avg eval drop       : {cluster_summary.get('avg_eval_drop', 0):.0f} cp
  Avg time spent      : {cluster_summary.get('avg_time_spent', 0):.0f} s
  Avg hanging change  : {cluster_summary.get('avg_hanging_increase', 0):.2f}
  Avg king exposure   : {cluster_summary.get('avg_king_attackers_increase', 0):.2f}
  Capture rate        : {cluster_summary.get('capture_rate', 0):.0%}

Examples:
{examples_text}
Respond in EXACTLY this format, nothing else:
NAME: <4-7 word descriptive name, no quotes>
DESCRIPTION: <one plain-English sentence explaining the mistake>
"""
    response = ollama_complete(prompt, temperature=0.3, max_tokens=150)
    if not response:
        return fallback

    name, desc = fallback
    for line in response.splitlines():
        line = line.strip().lstrip("*").lstrip("-").strip()
        if line.lower().startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"').strip()
        elif line.lower().startswith("description:"):
            desc = line.split(":", 1)[1].strip().strip('"').strip()
    return name, desc


def generate_user_summary(
    user_id: int,
    db_path: Optional[Path] = None,
    use_llm: bool = True,
) -> str:
    """Produce the final paragraph (the 'cool moment')."""
    with get_conn(db_path) as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        n_games = conn.execute(
            "SELECT COUNT(*) AS c FROM games WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        n_blunders = conn.execute(
            "SELECT COUNT(*) AS c FROM blunders WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        patterns = conn.execute(
            "SELECT * FROM patterns WHERE user_id = ? ORDER BY size DESC LIMIT 5",
            (user_id,),
        ).fetchall()

    if not patterns:
        return (f"You've played {n_games} games and I found {n_blunders} blunders, "
                "but no recurring patterns yet — try ingesting more games "
                "(or lowering --min-cluster-size).")

    enhanced = []
    for p in patterns:
        item = {"name": p["name"], "description": p["description"], "size": p["size"]}
        if use_llm:
            example_ids = json.loads(p["example_blunder_ids"]) if p["example_blunder_ids"] else []
            if example_ids:
                with get_conn(db_path) as conn:
                    placeholders = ",".join(["?"] * len(example_ids))
                    blunder_rows = conn.execute(
                        f"SELECT features_json FROM blunders WHERE id IN ({placeholders})",
                        example_ids,
                    ).fetchall()
                examples = [json.loads(b["features_json"]) for b in blunder_rows]
                cluster_summary = {
                    "size": p["size"],
                    "name": p["name"],
                    "description": p["description"],
                    "piece": _mode(e.get("piece") for e in examples),
                    "phase": _mode(e.get("phase") for e in examples),
                    "time_class": _mode(e.get("time_class") for e in examples),
                    "avg_eval_drop": float(np.mean([e.get("eval_drop_cp", 0) for e in examples])),
                    "avg_time_spent": float(np.mean([e.get("time_spent", 0) or 0 for e in examples])),
                    "avg_hanging_increase": float(np.mean([e.get("hanging_increase", 0) for e in examples])),
                    "avg_king_attackers_increase": float(np.mean([e.get("king_attackers_increase", 0) for e in examples])),
                    "capture_rate": sum(1 for e in examples if e.get("is_capture")) / max(len(examples), 1),
                }
                name, desc = name_cluster_with_llm(cluster_summary, examples)
                with get_conn(db_path) as conn:
                    conn.execute(
                        "UPDATE patterns SET name = ?, description = ? WHERE id = ?",
                        (name, desc, p["id"]),
                    )
                item["name"], item["description"] = name, desc
        enhanced.append(item)

    if not use_llm:
        lines = [f"You've played {n_games} games. I found {n_blunders} blunders "
                 f"and {len(enhanced)} recurring patterns:"]
        for i, p in enumerate(enhanced, 1):
            lines.append(f"  {i}. {p['name']} ({p['size']}×) — {p['description']}")
        return "\n".join(lines)

    pattern_text = "\n".join(
        f"- {p['name']} (occurred {p['size']} times): {p['description']}"
        for p in enhanced
    )
    final_prompt = f"""You are a chess coach giving a player their first profile after analyzing their games.

Player    : {user['username']}
Rating    : {user['rating'] or 'unknown'}
Games     : {n_games}
Blunders  : {n_blunders}

Their top recurring patterns:
{pattern_text}

Write ONE paragraph (4-6 sentences) that:
  1. Greets the player by their username briefly.
  2. States the games and blunder counts naturally.
  3. Highlights the top 2-3 patterns by name with their counts.
  4. Ends with ONE concrete suggestion for what to focus on first.

Be specific to the patterns above. Do not invent patterns. Do not be sycophantic.
Plain language. No bullet points. No headers. Just one paragraph.
"""
    out = ollama_complete(final_prompt, temperature=0.5, max_tokens=400)
    if not out:
        return generate_user_summary(user_id, db_path, use_llm=False)
    return out


def _mode(values):
    from collections import Counter
    c = Counter(v for v in values if v is not None)
    return c.most_common(1)[0][0] if c else None
