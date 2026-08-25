"""A minimalist presentation UI for real, precomputed Chess Psych evidence.

Run:
    streamlit run apps/presentation_demo.py

Generate the input evidence first with:
    python scripts/precompute_presentation_profiles.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import chess
import streamlit as st
import streamlit.components.v1 as components

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from chess_psych.personal_validation import (
    decision_context_from_cluster,
    user_eval_drop,
)
from chess_psych.stockfish_pool import StockfishPool


PROFILE_ORDER = (
    ("mishilt", "MishilT"),
    ("player_x", "Player X"),
    ("gm_reference", "GM reference"),
)
FEATURED_CLUSTER_IDS = {
    "mishilt": 3,
    "player_x": 1,
    "gm_reference": 1,
}


st.set_page_config(page_title="Chess Psych Presentation", layout="wide")
st.markdown(
    """
<style>
  .block-container { max-width: 1180px; padding-top: 2rem; }
  h1, h2, h3 { letter-spacing: 0; }
  .eyebrow { color: #5d6b7d; font-size: .75rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
  .prepared { display: inline-block; padding: .3rem .55rem; border: 1px solid #bcd2e9; border-radius: 4px; background: #edf4fb; color: #174c83; font-size: .8rem; font-weight: 800; }
</style>
""",
    unsafe_allow_html=True,
)


def evidence_path(profile_id: str) -> Path:
    return REPO_ROOT / "demos" / f"presentation_{profile_id}_evidence.json"


@st.cache_data(show_spinner=False)
def load_evidence(path_text: str, modified: int) -> dict[str, Any]:
    del modified
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


@st.cache_resource
def presentation_board():
    """Use the reusable legal-move chessboard component from the live coach."""
    return components.declare_component(
        "presentation_chessboard",
        path=str(REPO_ROOT / "web_components" / "chessboard"),
    )


def available_profiles() -> list[tuple[str, str]]:
    return [profile for profile in PROFILE_ORDER if evidence_path(profile[0]).exists()]


def story_for(cluster: dict[str, Any]) -> dict[str, str]:
    return cluster.get("decision_context") or decision_context_from_cluster(cluster)


def ordered_clusters(profile_id: str, clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    featured_id = FEATURED_CLUSTER_IDS.get(profile_id)
    return sorted(
        clusters,
        key=lambda cluster: (
            cluster.get("cluster_id") != featured_id,
            cluster.get("name") == "Other confirmed error",
            -cluster.get("family_purity", 0),
            -cluster.get("training_occurrences", 0),
        ),
    )


def presentation_patterns(profile_id: str, validation: dict[str, Any]) -> list[dict[str, Any]]:
    """Show one strict cluster plus a small number of measured risk contexts."""
    strict = ordered_clusters(profile_id, presentation_clusters(validation.get("clusters", [])))
    adaptive = validation.get("adaptive_risk_patterns", [])
    adaptive_items = [
        {
            **pattern,
            "cluster_id": f"risk-{index}",
            "decision_context": pattern["story"],
            "training_occurrences": pattern["training_errors"],
            "holdout_recurrences": pattern["holdout_errors"],
            "presentation_type": "risk_context",
        }
        for index, pattern in enumerate(adaptive)
    ]
    # One mechanism-specific cluster is more useful than several near-duplicate
    # categories. Risk contexts cover players for whom no narrow cluster passes.
    return strict[:1] + adaptive_items[:2]


def pattern_labels(clusters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    used: dict[str, int] = {}
    for cluster in clusters:
        base = story_for(cluster)["title"]
        used[base] = used.get(base, 0) + 1
        label = base if used[base] == 1 else f"{base} - another decision group"
        labels[label] = cluster
    return labels


def presentation_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep broad geometry groups out of the player-facing presentation.

    HDBSCAN can validly find a dense region made mostly of a phase or moved
    piece. That is useful during analysis, but it is not a personal coaching
    insight unless the independently derived chess mechanism also recurs in
    the later games.
    """
    return [
        cluster
        for cluster in clusters
        if cluster.get("label_validation", {}).get("ready_for_coaching")
    ]


def engine_caught(example: dict[str, Any]) -> str:
    family = example.get("rule_label", "")
    if family == "Allows a new capture":
        return "The move gave the opponent a new capture."
    if family == "Allows a new check":
        return "The move opened a forcing check."
    if family == "Missed tactical capture":
        return "The move missed a tactical capture."
    if family == "Leaves a piece loose":
        return "The move left a piece available to win."
    return "The move let the opponent improve immediately."


def set_board_position(token: str, fen: str, *, reveal: bool) -> None:
    st.session_state.presentation_board_token = token
    st.session_state.presentation_board_fen = fen
    st.session_state.presentation_reveal = reveal
    st.session_state.presentation_board_position_id = (
        st.session_state.get("presentation_board_position_id", 0) + 1
    )


def run_live_check(example: dict[str, Any], depth: int) -> int:
    before = chess.Board(example["fen_before"])
    after = chess.Board(example["fen_after"])
    player_color = before.turn
    with StockfishPool(threads=1, hash_mb=16) as engine:
        before_score = engine.analyse(before, depth=depth)
        after_score = engine.analyse(after, depth=depth)
    return user_eval_drop(before_score, after_score, player_color)


profiles = available_profiles()
st.markdown("<div class='eyebrow'>Chess Psych</div>", unsafe_allow_html=True)
st.title("Find the mistake behind the mistake.")
st.write(
    "Each player tab shows one real engine error, the repeat pattern behind it, "
    "and one useful next-game action."
)
st.markdown("<span class='prepared'>Prepared analysis &middot; live engine check</span>", unsafe_allow_html=True)

if not profiles:
    st.warning("No presentation evidence is available yet. Run `python scripts/precompute_presentation_profiles.py` first.")
    st.stop()

profile_lookup = {name: profile_id for profile_id, name in profiles}
selected_name = st.radio("Player", list(profile_lookup), horizontal=True, label_visibility="collapsed")
profile_id = profile_lookup[selected_name]
path = evidence_path(profile_id)
evidence = load_evidence(str(path), path.stat().st_mtime_ns)
validation = evidence["validation"]
clusters = presentation_patterns(profile_id, validation)

if not clusters:
    st.info("This sample does not yet contain enough evidence for a useful personal insight.")
    st.stop()

labels = pattern_labels(ordered_clusters(profile_id, clusters))
selected_label = st.selectbox("See another pattern", labels)
cluster = labels[selected_label]
story = story_for(cluster)
example = (cluster.get("examples") or [{}])[0]
token = f"{profile_id}:{cluster.get('cluster_id')}"

if st.session_state.get("presentation_board_token") != token:
    set_board_position(token, example.get("fen_before", ""), reveal=False)

left, right = st.columns([1.05, 0.95])
with left:
    before_button, move_button, reset_button = st.columns(3)
    if before_button.button("Before the mistake", use_container_width=True):
        set_board_position(token, example.get("fen_before", ""), reveal=False)
    if move_button.button("Show the recorded move", use_container_width=True):
        set_board_position(token, example.get("fen_after", ""), reveal=True)
    if reset_button.button("Reset", use_container_width=True):
        set_board_position(token, example.get("fen_before", ""), reveal=False)

    board_fen = st.session_state.presentation_board_fen
    presentation_board()(
        fen=board_fen,
        orientation="white",
        movable_color="white" if chess.Board(board_fen).turn == chess.WHITE else "black",
        position_id=st.session_state.presentation_board_position_id,
        key="presentation_board_widget",
        default=None,
    )
    st.caption("Drag a legal move to explore. Use the buttons to return to the recorded position.")
    if st.session_state.presentation_reveal:
        st.caption(f"Recorded move: {example.get('move', '-')}")
    if example.get("game_url"):
        st.link_button("Open public game", example["game_url"])

with right:
    if st.session_state.presentation_reveal:
        st.markdown("<div class='eyebrow'>What Stockfish caught</div>", unsafe_allow_html=True)
        st.subheader(engine_caught(example))
        st.write(
            f"In this game, {example.get('move', 'the move')} was met by "
            f"{example.get('opponent_best_reply', 'the engine reply')}."
        )
        st.divider()
        st.markdown("<div class='eyebrow'>What repeats for this player</div>", unsafe_allow_html=True)
        st.subheader(story["title"])
        st.write(story["why"])
        if cluster.get("presentation_type") == "risk_context":
            st.caption(
                f"Older games: {cluster.get('training_errors', 0)} engine errors in "
                f"{cluster.get('training_decisions', 0)} similar decisions "
                f"({cluster.get('training_lift', 0)}x this player's normal error rate). "
                f"Newer games: {cluster.get('holdout_errors', 0)} in "
                f"{cluster.get('holdout_decisions', 0)} "
                f"({cluster.get('holdout_lift', 0)}x normal)."
            )
        else:
            st.caption(
                f"Seen {cluster.get('training_occurrences', 0)} times in earlier games and "
                f"{cluster.get('holdout_recurrences', 0)} times in later games."
            )
        if st.button("Check this position live", type="primary"):
            with st.spinner("Stockfish is evaluating this recorded position locally..."):
                run_live_check(example, int(evidence["experiment"].get("confirm_depth", 14)))
            st.success("Live check complete: Stockfish confirmed this move is a significant mistake.")
