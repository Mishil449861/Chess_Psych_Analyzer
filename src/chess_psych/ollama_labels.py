"""Constrained local-Ollama labels for evidence-backed chess clusters.

The model is only a language layer. Stockfish confirms errors, HDBSCAN groups
them, and deterministic chess rules validate recurrence. This module turns a
cluster's factual evidence into a short player-facing label or an abstention.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

import requests

from .personal_validation import LABELABLE_ERROR_FAMILIES, MIN_LABEL_PURITY


PROMPT_VERSION = "cluster-label-v1"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
ALLOWED_CONFIDENCE = {"low", "medium", "high"}

SYSTEM_PROMPT = """You label chess-error clusters for a coaching demo.
Use only the supplied evidence. Do not diagnose personality or mental health.
Do not claim causation. If the examples are too mixed, return abstain=true.
Use phase_counts and time_context_counts literally: call a pattern endgame or
late-game only when endgame is the majority; call it fast only when quick is
the majority; call it time pressure only when low or critical is the majority.
Use rule_label_counts literally as well. Only use 'tactical', 'forcing', or
'missed capture' language when Missed tactical capture is the majority. Only
use 'loose' or 'hanging' language when Leaves a piece loose is the majority.
When Other confirmed error is the majority, abstain. Do not turn a broad move
context into a chess mistake label.
Return JSON only with exactly these fields:
label (max 72 characters), coaching_cue (max 140 characters),
alternative_explanation (max 140 characters), confidence (low|medium|high),
abstain (boolean), reason (max 180 characters).
Use observable language such as 'late-game queen moves miss forcing options',
not psychological claims such as 'anxiety' or 'tilt'."""


def _fallback(reason: str) -> Dict[str, Any]:
    return {
        "label": "Unclear pattern",
        "coaching_cue": "Collect more examples before turning this into advice.",
        "alternative_explanation": "The cluster may combine different chess situations.",
        "confidence": "low",
        "abstain": True,
        "reason": reason,
    }


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _fallback("The local model did not return a JSON object.")
    confidence = str(raw.get("confidence", "low")).lower()
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "low"
    result = {
        "label": str(raw.get("label", "Unclear pattern"))[:72],
        "coaching_cue": str(raw.get("coaching_cue", "Collect more examples before turning this into advice."))[:140],
        "alternative_explanation": str(raw.get("alternative_explanation", "The cluster may combine different chess situations."))[:140],
        "confidence": confidence,
        "abstain": bool(raw.get("abstain", False)),
        "reason": str(raw.get("reason", "No explanation returned."))[:180],
    }
    if not result["label"].strip() or not result["coaching_cue"].strip():
        return _fallback("The local model returned an incomplete label.")
    return result


def _contradicts_evidence(result: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
    """Reject attractive prose that conflicts with the measured cluster facts."""
    # A cue may legitimately tell a player to check captures or threats. Only
    # reject claims that the model makes about the cluster itself.
    text = " ".join(str(result[key]).lower() for key in ("label", "reason"))
    members = max(int(evidence.get("members", 0)), 1)
    phases = evidence.get("phase_counts", {})
    clocks = evidence.get("time_context_counts", {})
    endgame_share = phases.get("endgame", 0) / members
    quick_share = clocks.get("quick", 0) / members
    pressure_share = (clocks.get("low", 0) + clocks.get("critical", 0)) / members
    rule_counts = evidence.get("rule_label_counts", {})
    tactical_share = rule_counts.get("Missed tactical capture", 0) / members
    loose_share = rule_counts.get("Leaves a piece loose", 0) / members
    if ("late-game" in text or "late game" in text or "endgame" in text) and endgame_share < 0.6:
        return True
    if ("fast" in text or "quick" in text or "speed" in text or "instant" in text) and quick_share < 0.6:
        return True
    if ("time pressure" in text or "clock pressure" in text or "scramble" in text) and pressure_share < 0.6:
        return True
    if ("tactic" in text or "forcing" in text) and tactical_share < 0.6:
        return True
    return ("loose" in text or "hanging" in text) and loose_share < 0.6


def evidence_label(evidence: Dict[str, Any]) -> str:
    """Publish a label assembled from measured majorities, not model wording."""
    members = max(int(evidence.get("members", 0)), 1)

    def majority(counts: Dict[str, int]) -> Optional[str]:
        value = max(counts, key=counts.get, default=None)
        return value if value is not None and counts[value] / members >= 0.6 else None

    phase = majority(evidence.get("phase_counts", {}))
    piece = majority(evidence.get("piece_counts", {}))
    clock = majority(evidence.get("time_context_counts", {}))
    rule = majority(evidence.get("rule_label_counts", {}))
    if rule not in LABELABLE_ERROR_FAMILIES:
        return "Unclear chess cause"
    parts = []
    if clock == "quick":
        parts.append("Quick")
    if phase:
        parts.append(phase.capitalize())
    if piece:
        parts.append(piece.capitalize())
    suffixes = {
        "Missed tactical capture": "missed captures",
        "Leaves a piece loose": "pieces left loose",
        "Delayed recapture": "delayed recaptures",
        "King safety": "king-safety errors",
        "Material oversight": "material oversights",
        "Missed checking move": "missed checking moves",
        "Allows a new capture": "new captures allowed",
        "Allows a new check": "new checks allowed",
    }
    parts.append(suffixes.get(rule, "confirmed errors"))
    return " ".join(parts)


def label_cluster(
    cluster: Dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = "http://127.0.0.1:11434/api/chat",
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """Ask Ollama for a constrained explanation of a single cluster."""
    evidence = cluster.get("label_evidence", {})
    support = int(cluster.get("training_occurrences", 0))
    rule_counts = evidence.get("rule_label_counts", {})
    peak_rule = max(rule_counts, key=rule_counts.get, default="")
    peak_rule_share = max(rule_counts.values(), default=0) / support if support else 0.0
    if (
        support < 4
        or peak_rule not in LABELABLE_ERROR_FAMILIES
        or peak_rule_share < MIN_LABEL_PURITY
    ):
        result = _fallback("No specific chess cause met the deterministic label-consistency gate.")
    else:
        packet = {
            "cluster_support": support,
            "median_eval_drop_cp": cluster.get("median_eval_drop_cp"),
            "evidence": evidence,
            "examples": cluster.get("examples", [])[:3],
        }
        try:
            response = requests.post(
                endpoint,
                json={
                    "model": model,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(packet, ensure_ascii=True)},
                    ],
                    "options": {"temperature": 0},
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            result = _validate(json.loads(response.json()["message"]["content"]))
            if not result["abstain"] and _contradicts_evidence(result, evidence):
                result = _fallback("The local model's wording contradicted the measured phase or clock evidence.")
        except (requests.RequestException, KeyError, TypeError, json.JSONDecodeError) as exc:
            result = _fallback(f"Local label model unavailable: {type(exc).__name__}.")
    published_label = evidence_label(evidence)
    if not result["abstain"]:
        # The model drafts wording; the shown label comes only from majority evidence.
        result["model_draft_label"] = result["label"]
        result["label"] = evidence_label(evidence)
    return {
        "provider": "ollama",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "evidence_label": published_label,
        "label": result,
    }


def label_clusters(
    clusters: Iterable[Dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return local labels without changing the cluster or validation result."""
    output = []
    for index, cluster in enumerate(clusters):
        if limit is not None and index >= limit:
            break
        output.append({"cluster_id": cluster["cluster_id"], **label_cluster(cluster, model=model)})
    return output
