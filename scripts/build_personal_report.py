"""Create a small file:// report for a single personal-pattern run."""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chess_psych.personal_validation import (
    LABELABLE_ERROR_FAMILIES,
    MIN_FAMILY_PATTERN_HOLDOUT_OCCURRENCES,
    MIN_FAMILY_PATTERN_TRAINING_OCCURRENCES,
    MIN_LABEL_HOLDOUT_AGREEMENT,
    MIN_LABEL_HOLDOUT_MATCHES,
    MIN_LABEL_PURITY,
)


ERROR_MAP_COPY = {
    "Allows a new capture": (
        "Gave the opponent a new capture",
        "Your move created a capture that was not a capture one move earlier.",
        "Before moving, check what the opponent can capture after your move.",
    ),
    "Allows a new check": (
        "Gave the opponent a new check",
        "Your move created a checking reply that was not available one move earlier.",
        "Before moving, check every new check your move allows.",
    ),
    "Missed tactical capture": (
        "Missed a capture",
        "Stockfish preferred a capture, but the played move was not a capture.",
        "Before a quiet move, scan every capture for both sides.",
    ),
    "Missed checking move": (
        "Missed a checking move",
        "Stockfish preferred a check, but the played move was not a check.",
        "Before a quiet move, scan your available checks.",
    ),
    "Leaves a piece loose": (
        "Left a piece loose",
        "The move increased the number of your pieces the opponent could win.",
        "Before moving, ask what became unprotected.",
    ),
    "Delayed recapture": (
        "Delayed a recapture",
        "After an exchange, Stockfish preferred an immediate recapture.",
        "After a capture, first check whether recapturing is necessary.",
    ),
    "King safety": (
        "Opened king danger",
        "The move sharply increased enemy pressure around your king.",
        "Before moving near your king, check the opponent's checks and captures.",
    ),
    "Material oversight": (
        "Lost material",
        "The move immediately reduced your material balance.",
        "Before moving, check what can be taken next.",
    ),
}

PIECE_GLYPHS = {
    "p": "&#9823;", "n": "&#9822;", "b": "&#9821;", "r": "&#9820;", "q": "&#9819;", "k": "&#9818;",
    "P": "&#9817;", "N": "&#9816;", "B": "&#9815;", "R": "&#9814;", "Q": "&#9813;", "K": "&#9812;",
}


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_cluster(validation: Dict[str, Any]) -> Dict[str, Any] | None:
    clusters = validation.get("clusters", [])
    if not clusters:
        return None
    return max(
        clusters,
        key=lambda item: (
            item["holdout_recurrences"],
            item["family_purity"],
            item["training_occurrences"],
        ),
    )


def _most_common(counts: Dict[str, int], fallback: str = "unknown") -> tuple[str, int]:
    if not counts:
        return fallback, 0
    return max(counts.items(), key=lambda item: item[1])


def _matches(cluster: Dict[str, Any], validation: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        item for item in validation["holdout_matches"]
        if item["cluster_id"] == cluster["cluster_id"]
    ]


def cluster_title(cluster: Dict[str, Any]) -> str:
    """Give a player a factual name without over-claiming a chess rule."""
    evidence = cluster["label_evidence"]
    phase, _ = _most_common(evidence.get("phase_counts", {}))
    piece, _ = _most_common(evidence.get("piece_counts", {}))
    clock, clock_count = _most_common(evidence.get("time_context_counts", {}))
    total = cluster["training_occurrences"]
    family = cluster.get("name", "")
    purity = cluster.get("family_purity", 0.0)
    if family != "Other confirmed error" and purity >= 0.75:
        return family
    if clock_count / total >= 0.50:
        if clock == "quick":
            return f"Quick {phase} {piece} moves"
        if clock == "available":
            return f"{phase.title()} {piece} moves with time left"
        if clock == "critical":
            return f"Time-trouble {phase} {piece} moves"
    return f"{phase.title()} {piece} decisions"


def cluster_summary(cluster: Dict[str, Any], validation: Dict[str, Any]) -> str:
    evidence = cluster["label_evidence"]
    phase, phase_count = _most_common(evidence.get("phase_counts", {}))
    piece, piece_count = _most_common(evidence.get("piece_counts", {}))
    total = cluster["training_occurrences"]
    later = cluster["holdout_recurrences"]
    shape = f"mostly {phase} positions involving a {piece}"
    if phase_count == total and piece_count == total:
        shape = f"{phase} positions involving a {piece}"
    matches = _matches(cluster, validation)
    agreements = sum(bool(item["rule_agrees"]) for item in matches)
    return (
        f"This group is {shape}. It appeared {later} time{'s' if later != 1 else ''} "
        f"in later games; {agreements} had the same chess reason."
    )


def clock_summary(cluster: Dict[str, Any]) -> str:
    evidence = cluster["label_evidence"]
    time_context, count = _most_common(evidence.get("time_context_counts", {}))
    total = cluster["training_occurrences"]
    clock_left = evidence.get("median_clock_remaining_seconds")
    spent = evidence.get("median_time_spent_seconds")
    if time_context == "quick":
        lead = "Most of these moves were played quickly"
    elif time_context == "critical":
        lead = "Most of these moves happened in time trouble"
    elif time_context == "available":
        lead = "Most happened with time still available"
    else:
        lead = "The clock situation varied"
    details = []
    if clock_left is not None:
        details.append(f"about {clock_left:.0f} seconds left")
    if spent is not None:
        details.append(f"about {spent:.1f} seconds spent")
    suffix = f" ({', '.join(details)})" if details else ""
    if count == total:
        return f"{lead}{suffix}."
    return f"{lead} in {count} of {total} examples{suffix}."


def practice_cue(cluster: Dict[str, Any]) -> str:
    evidence = cluster["label_evidence"]
    family = cluster.get("name", "")
    if family == "Missed tactical capture" and cluster.get("family_purity", 0.0) >= 0.75:
        return "Before a quiet move, scan every capture for both sides."
    if family == "Leaves a piece loose" and cluster.get("family_purity", 0.0) >= 0.75:
        return "Before moving, ask: what did this move leave unprotected?"
    if family == "King safety" and cluster.get("family_purity", 0.0) >= 0.75:
        return "Before moving the king, check the opponent's checks and captures."
    piece, _ = _most_common(evidence.get("piece_counts", {}))
    cues = {
        "rook": "Before moving a rook, name the opponent's forcing move and your rook's active square.",
        "knight": "Before moving a knight, check the squares and pieces it leaves behind.",
        "bishop": "Before moving a bishop, trace the diagonals it opens and closes.",
        "pawn": "Before pushing a pawn, check what the move opens, attacks, or weakens.",
        "queen": "Before moving the queen, scan checks, captures, and immediate threats.",
        "king": "Before moving the king, check every check, capture, and passed pawn.",
    }
    return cues.get(piece, "Before moving, scan checks, captures, and immediate threats.")


def evidence_cards(cluster: Dict[str, Any], validation: Dict[str, Any]) -> list[tuple[str, str]]:
    matches = _matches(cluster, validation)
    agreements = sum(bool(item["rule_agrees"]) for item in matches)
    return [
        (str(cluster["training_occurrences"]), "similar earlier mistakes"),
        (str(cluster["holdout_recurrences"]), "similar moves later"),
        (f"{agreements}/{len(matches)}" if matches else "-", "same chess reason later"),
    ]


def error_map(validation: Dict[str, Any], limit: int = 3) -> list[Dict[str, Any]]:
    rows = [
        row for row in validation.get("family_validation", [])
        if row.get("family") in ERROR_MAP_COPY and row.get("total_occurrences", 0) > 0
    ]
    return sorted(rows, key=lambda row: row["total_occurrences"], reverse=True)[:limit]


def error_map_card(row: Dict[str, Any]) -> str:
    title, description, cue = ERROR_MAP_COPY[row["family"]]
    examples = row.get("examples", [])
    game_link = ""
    example_read = ""
    if examples and examples[0].get("game_url"):
        example = examples[0]
        played = example.get("move")
        reply = example.get("opponent_best_reply")
        if played and reply:
            example_read = (
                f"<p class='example'><strong>Real instance:</strong> after your "
                f"<code>{html.escape(played)}</code>, Stockfish's reply was "
                f"<code>{html.escape(reply)}</code>.</p>"
            )
        game_link = (
            f"<a href='{html.escape(example['game_url'])}' target='_blank' rel='noreferrer'>Open this position</a>"
        )
    return f"""
    <section class='pattern'>
      <div class='pattern-title'><h3>{html.escape(title)}</h3><span>{row['total_occurrences']} confirmed moves</span></div>
      <p>{html.escape(description)}</p>
      <div class='cue'><strong>Useful check:</strong> {html.escape(cue)}</div>
      {game_link}
    </section>"""


def mini_board(fen: str) -> str:
    """Render a compact, dependency-free board for one stored FEN."""
    position = (fen or "").split(" ", 1)[0]
    ranks = position.split("/")
    if len(ranks) != 8:
        return ""
    squares = []
    for rank_index, rank in enumerate(ranks):
        file_index = 0
        for char in rank:
            if char.isdigit():
                for _ in range(int(char)):
                    color = "dark" if (rank_index + file_index) % 2 else "light"
                    squares.append(f"<span class='square {color}'></span>")
                    file_index += 1
            else:
                color = "dark" if (rank_index + file_index) % 2 else "light"
                squares.append(
                    f"<span class='square {color}'>{PIECE_GLYPHS.get(char, '')}</span>"
                )
                file_index += 1
    return f"<div class='mini-board' aria-label='Chess position'>{''.join(squares)}</div>"


def cluster_explorer(validation: Dict[str, Any]) -> str:
    """Expose the actual HDBSCAN output, including weak clusters and noise."""
    clusters = validation.get("clusters", [])
    if not clusters:
        return """
        <section class='cluster-explorer empty-clusters'>
          <div class='eyebrow'>HDBSCAN cluster explorer</div>
          <h2>No density cluster in this run</h2>
          <p>The model kept the confirmed errors as noise instead of forcing unrelated mistakes into a group. This is a valid model result.</p>
        </section>"""

    summary = [
        (str(validation.get("cluster_count", len(clusters))), "HDBSCAN clusters"),
        (str(validation.get("clustered_training_errors", 0)), "older errors assigned"),
        (str(validation.get("noise_errors", 0)), "older errors left as noise"),
        (
            f"{validation['silhouette_score']:.2f}"
            if validation.get("silhouette_score") is not None else "-",
            "cluster separation",
        ),
    ]
    cards = []
    panels = []
    for index, cluster in enumerate(clusters):
        title = cluster_title(cluster)
        evidence = cluster.get("label_evidence", {})
        family = cluster.get("name", "Other confirmed error")
        purity = float(cluster.get("family_purity", 0.0))
        matches = _matches(cluster, validation)
        audit = cluster.get("label_validation", {})
        example = cluster.get("examples", [{}])[0] if cluster.get("examples") else {}
        button_class = "cluster-choice selected" if index == 0 else "cluster-choice"
        cards.append(f"""
        <button class='{button_class}' type='button' data-cluster='{cluster['cluster_id']}' aria-pressed='{'true' if index == 0 else 'false'}'>
          <span>Cluster {cluster['cluster_id'] + 1}</span>
          <strong>{html.escape(title)}</strong>
          <em>{cluster['training_occurrences']} older errors</em>
        </button>""")
        panel_class = "cluster-panel selected" if index == 0 else "cluster-panel"
        holdout_text = (
            f"{len(matches)} later matches; {sum(bool(item.get('rule_agrees')) for item in matches)}/{len(matches)} agreed with the cluster's rule label"
            if matches else "No later error fell inside this cluster's learned radius"
        )
        mechanism_note = (
            "This rule label was measured after clustering; it was not one of the HDBSCAN input labels."
            if family != "Other confirmed error" else
            "The points are mathematically similar, but no single chess rule label dominates them."
        )
        source = (
            f"<a href='{html.escape(example.get('game_url', ''))}' target='_blank' rel='noreferrer'>Open this source game</a>"
            if example.get("game_url") else ""
        )
        panels.append(f"""
        <article class='{panel_class}' data-cluster-panel='{cluster['cluster_id']}'>
          <div class='cluster-detail'>
            <div>
              <div class='eyebrow'>Actual HDBSCAN cluster {cluster['cluster_id'] + 1}</div>
              <h3>{html.escape(title)}</h3>
              <p>{html.escape(cluster_summary(cluster, validation))}</p>
              <div class='cluster-metrics'>
                <span><strong>{cluster['training_occurrences']}</strong> older members</span>
                <span><strong>{purity:.0%}</strong> rule consistency</span>
                <span><strong>{cluster.get('median_eval_drop_cp', 0)}</strong> median cp lost</span>
                <span><strong>{len(matches)}</strong> later matches</span>
              </div>
              <p class='cluster-note'><strong>Post-cluster explanation:</strong> {html.escape(family)}. {html.escape(mechanism_note)}</p>
              <p class='cluster-note'><strong>Later-game check:</strong> {html.escape(holdout_text)}.</p>
              <details class='technical'><summary>Cluster evidence</summary><div>
                <span>HDBSCAN radius: {cluster.get('radius', '-')}</span>
                <span>Dominant phase counts: {html.escape(str(evidence.get('phase_counts', {})))}</span>
                <span>Dominant piece counts: {html.escape(str(evidence.get('piece_counts', {})))}</span>
              </div></details>
              {source}
            </div>
            {mini_board(example.get('fen_before', ''))}
          </div>
        </article>""")
    metrics = "".join(
        f"<div class='metric'><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span></div>"
        for value, label in summary
    )
    return f"""
    <section class='cluster-explorer'>
      <div class='eyebrow'>HDBSCAN cluster explorer</div>
      <h2>Explore the model's actual clusters</h2>
      <p class='intro'>These groups come directly from HDBSCAN over older, engine-confirmed errors. The model may leave errors as noise; it is not required to group everything.</p>
      <div class='cluster-summary'>{metrics}</div>
      <div class='cluster-choices'>{''.join(cards)}</div>
      <div class='cluster-panels'>{''.join(panels)}</div>
    </section>"""


def recurring_error_families(validation: Dict[str, Any], limit: int = 2) -> list[Dict[str, Any]]:
    rows = [
        row for row in validation.get("family_validation", [])
        if row.get("family") in ERROR_MAP_COPY and (
            row.get("ready_as_repeat_error")
            or (
                row.get("training_occurrences", 0) >= MIN_FAMILY_PATTERN_TRAINING_OCCURRENCES
                and row.get("holdout_occurrences", 0) >= MIN_FAMILY_PATTERN_HOLDOUT_OCCURRENCES
            )
        )
        # A repeated error family is useful evidence, but not necessarily a
        # personal coaching insight. Only display it when a concrete context
        # also persists in the unseen later games.
        and row.get("stable_context")
    ]
    return sorted(
        rows,
        key=lambda row: (row["holdout_occurrences"], row["training_occurrences"]),
        reverse=True,
    )[:limit]


def context_phrase(conditions: Dict[str, str], *, plural: bool = False) -> str:
    phase = conditions.get("phase")
    piece = conditions.get("piece")
    time_context = conditions.get("time_context")
    captured_piece = conditions.get("opponent_reply_capture_piece")
    captures_moved_piece = conditions.get("opponent_reply_captures_moved_piece")
    moved_into_attack = conditions.get("moved_piece_moved_into_attack")
    unprotected_after = conditions.get("moved_piece_unprotected_after")
    core = f"position{'s' if plural else ''}"
    if phase and piece:
        core = f"{phase} {piece} move"
    elif phase:
        core = f"{phase} position{'s' if plural else ''}"
    elif piece:
        core = f"{piece} move{'s' if plural else ''}"
    time_text = {
        "available": "with time left",
        "quick": "after quick moves",
        "low": "in low time",
        "critical": "in critical time",
    }.get(time_context)
    phrase = f"{core} {time_text}" if time_text else core
    if moved_into_attack is True and unprotected_after is True:
        return f"{phrase} where a safe piece lands on an undefended target"
    if moved_into_attack is True:
        return f"{phrase} where a safe piece is moved onto an attacked square"
    if unprotected_after is True:
        return f"{phrase} where the destination square has no defender"
    if captures_moved_piece is True:
        return f"{phrase} where the moved piece becomes capturable"
    if captured_piece and captured_piece != "unknown":
        return f"{phrase} where a {captured_piece} becomes capturable"
    return phrase


def personalized_copy(
    family: str,
    conditions: Dict[str, Any],
    fallback_title: str,
    fallback_description: str,
) -> tuple[str, str]:
    """Name the demonstrated trigger, never a generic family, when possible."""
    if family == "Allows a new capture" and conditions.get("opponent_reply_captures_moved_piece") is True:
        if (
            conditions.get("moved_piece_moved_into_attack") is True
            and conditions.get("moved_piece_unprotected_after") is True
        ):
            return (
                "A safe piece lands on an undefended target",
                "The move repeatedly puts a previously safe piece on a square the opponent can take without a defender.",
            )
        if conditions.get("moved_piece_moved_into_attack") is True:
            return (
                "A safe piece is moved into attack",
                "The move repeatedly relocates a safe piece onto a square the opponent can immediately attack.",
            )
        return (
            "The piece you just moved gets taken",
            "Stockfish's best reply repeatedly captures the exact piece moved on the previous turn.",
        )
    target = conditions.get("opponent_reply_capture_piece")
    if family == "Allows a new capture" and target not in (None, "unknown"):
        return (
            f"A {target} becomes capturable",
            f"Stockfish's best reply repeatedly takes a {target} made available by the move.",
        )
    if family == "Leaves a piece loose":
        return (
            "A piece becomes undefended",
            "The move repeatedly leaves one of the player's pieces available to the opponent.",
        )
    return fallback_title, fallback_description


def technical_tests(conditions: Dict[str, Any]) -> str:
    """Expose the board facts behind a personal trigger without UI jargon."""
    tests = []
    if conditions.get("moved_piece_started_safe") is True:
        tests.append("source square was not attacked before the move")
    if conditions.get("moved_piece_moved_into_attack") is True:
        tests.append("destination square was attacked after the move")
    if conditions.get("moved_piece_unprotected_after") is True:
        tests.append("destination square had no friendly defender")
    if conditions.get("opponent_reply_captures_moved_piece") is True:
        tests.append("Stockfish's best reply captured the moved piece")
    elif conditions.get("opponent_reply_capture_piece") not in (None, "unknown"):
        tests.append(
            f"Stockfish's best reply captured the newly exposed {conditions['opponent_reply_capture_piece']}"
        )
    return "<br>".join(f"<span>{html.escape(test)}</span>" for test in tests)


def recurring_error_card(row: Dict[str, Any], validation: Dict[str, Any]) -> str:
    title, description, cue = ERROR_MAP_COPY[row["family"]]
    split = validation.get("game_split", {})
    earlier_games = max(int(split.get("earlier_games", 0)), 1)
    later_games = max(int(split.get("later_games", 0)), 1)
    earlier_rate = row["training_occurrences"] / earlier_games * 10
    later_rate = row["holdout_occurrences"] / later_games * 10
    evidence = row.get("evidence", {})
    context = row.get("stable_context")
    total = max(int(evidence.get("members", row.get("total_occurrences", 0))), 1)
    time_counts = evidence.get("time_context_counts", {})
    available = int(time_counts.get("available", 0))
    quick_or_low = sum(int(time_counts.get(name, 0)) for name in ("quick", "low", "critical"))
    phase_count = len([count for count in evidence.get("phase_counts", {}).values() if count])
    piece_count = len([count for count in evidence.get("piece_counts", {}).values() if count])
    if context:
        conditions = context["conditions"]
        title, description = personalized_copy(row["family"], conditions, title, description)
        context_text = context_phrase(conditions)
        context_text_plural = context_phrase(conditions, plural=True)
        context_evidence = context.get("evidence", {})
        clock_left = context_evidence.get("median_clock_remaining_seconds")
        spent = context_evidence.get("median_time_spent_seconds")
        clock_read = ""
        if clock_left is not None:
            clock_read = f" The median clock still showed {clock_left:.0f} seconds"
            if spent is not None:
                clock_read += f" after about {spent:.1f} seconds of thinking"
            clock_read += ", so this is not simply time trouble."
        personal_read = (
            f"Personal trigger: this was concentrated in {context_text_plural}: "
            f"{context['training_occurrences']} of {row['training_occurrences']} earlier cases and "
            f"{context['holdout_occurrences']} of {row['holdout_occurrences']} later cases."
            f"{clock_read}"
        )
        new_capture_cue = "name the opponent's strongest capture before you release the move."
        if (
            conditions.get("moved_piece_moved_into_attack") is True
            and conditions.get("moved_piece_unprotected_after") is True
        ):
            new_capture_cue = (
                "compare the destination square: name its enemy attackers and your defenders before you release the move."
            )
        elif conditions.get("moved_piece_moved_into_attack") is True:
            new_capture_cue = "ask which enemy piece attacks the destination square before you release the move."
        elif conditions.get("opponent_reply_captures_moved_piece") is True:
            new_capture_cue = "ask whether the piece you just moved can be taken immediately."
        elif conditions.get("opponent_reply_capture_piece") not in (None, "unknown"):
            new_capture_cue = (
                f"ask whether you have just made a {conditions['opponent_reply_capture_piece']} capturable."
            )
        tailored_cue = (
            f"When you reach a {context_text}, use a 3-second destination-square check: "
            + {
                "Allows a new capture": new_capture_cue,
                "Allows a new check": "name the opponent's strongest check before you release the move.",
                "Leaves a piece loose": "name which of your pieces is now undefended before you release the move.",
                "Missed tactical capture": "name your strongest capture before choosing a quiet move.",
                "Missed checking move": "name your strongest check before choosing a quiet move.",
            }.get(row["family"], cue)
        )
        technical_evidence = technical_tests(conditions)
    elif available / total >= 0.60:
        personal_read = (
            f"Personal read: {available} of {total} happened with time still available. "
            "This is a final-check habit, not simply time trouble."
        )
        final_position_checks = {
            "Allows a new capture": "In the final position, name every capture your opponent has.",
            "Allows a new check": "In the final position, name every check your opponent has.",
            "Leaves a piece loose": "In the final position, name which of your pieces is now undefended.",
            "Missed tactical capture": "In the final position, name every capture you have before playing a quiet move.",
            "Missed checking move": "In the final position, name every check you have before playing a quiet move.",
            "Delayed recapture": "After an exchange, decide explicitly whether an immediate recapture is required.",
            "King safety": "In the final position, name every check and capture against your king.",
            "Material oversight": "In the final position, name what either side can take next.",
        }
        tailored_cue = "Do not just slow down. " + final_position_checks.get(row["family"], cue)
    elif quick_or_low / total >= 0.60:
        personal_read = (
            f"Personal read: {quick_or_low} of {total} happened after quick or low-clock moves. "
            "The check needs to become automatic when the clock is moving."
        )
        tailored_cue = cue
    else:
        personal_read = (
            f"Personal read: this appeared across {phase_count} game phases and {piece_count} piece types, "
            "so the evidence supports one broad board-vision check rather than an opening-specific story."
        )
        tailored_cue = cue
        technical_evidence = ""
    examples = row.get("examples", [])
    game_link = ""
    example_read = ""
    if examples and examples[0].get("game_url"):
        example = examples[0]
        played = example.get("move")
        reply = example.get("opponent_best_reply")
        if played and reply:
            example_read = (
                f"<p class='example'><strong>Real instance:</strong> after your "
                f"<code>{html.escape(played)}</code>, Stockfish's reply was "
                f"<code>{html.escape(reply)}</code>.</p>"
            )
        game_link = (
            f"<a href='{html.escape(example['game_url'])}' target='_blank' rel='noreferrer'>Open this position</a>"
        )
    return f"""
    <section class='pattern featured'>
      <div class='pattern-title'><h3>{html.escape(title)}</h3><span>verified in both time periods</span></div>
      <p>{html.escape(description)}</p>
      <p class='personal-read'>{html.escape(personal_read)}</p>
      <p class='evidence'><strong>Repeat evidence:</strong> {row['training_occurrences']} confirmed moves in the earlier {earlier_games} games, then {row['holdout_occurrences']} more in the later {later_games} games. That is {earlier_rate:.1f}, then {later_rate:.1f} moves per 10 games.</p>
      <div class='cue'><strong>Your check:</strong> {html.escape(tailored_cue)}</div>
      <details class='technical'><summary>Technical evidence</summary><div>{technical_evidence}</div></details>
      {example_read}
      {game_link}
    </section>"""


def useful_clusters(validation: Dict[str, Any], limit: int = 3) -> list[Dict[str, Any]]:
    """Keep player-facing advice limited to repeatable, distinct patterns.

    HDBSCAN can make fine-grained mathematical groups that do not become a
    meaningful coaching habit. A displayed pattern needs a concrete chess
    cause, at least 75% consistency in older games, and a successful check on
    at least two later examples. Broad move contexts never become advice.
    """
    selected = []
    seen_titles = set()
    for cluster in validation.get("clusters", []):
        matches = _matches(cluster, validation)
        later = len(matches)
        agreements = sum(bool(item["rule_agrees"]) for item in matches)
        audit = cluster.get("label_validation", {})
        ready = audit.get("ready_for_coaching")
        if ready is None:
            ready = bool(
                cluster.get("name") in LABELABLE_ERROR_FAMILIES
                and cluster.get("family_purity", 0.0) >= MIN_LABEL_PURITY
                and later >= MIN_LABEL_HOLDOUT_MATCHES
                and agreements / later >= MIN_LABEL_HOLDOUT_AGREEMENT
            )
        if not ready:
            continue
        title = cluster_title(cluster)
        if title in seen_titles:
            continue
        selected.append(cluster)
        seen_titles.add(title)
        if len(selected) == limit:
            break
    return selected


def cluster_card(cluster: Dict[str, Any], validation: Dict[str, Any], featured: bool = False) -> str:
    title = html.escape(cluster_title(cluster))
    summary = html.escape(cluster_summary(cluster, validation))
    clock = html.escape(clock_summary(cluster))
    cue = html.escape(practice_cue(cluster))
    matches = _matches(cluster, validation)
    agreements = sum(bool(item["rule_agrees"]) for item in matches)
    example = next((item for item in matches if item["rule_agrees"]), matches[0] if matches else None)
    game_link = (
        f"<a href='{html.escape(example['game_url'])}' target='_blank' rel='noreferrer'>See one game</a>"
        if example else ""
    )
    css_class = "pattern featured" if featured else "pattern"
    return f"""
    <section class='{css_class}'>
      <div class='pattern-title'><h3>{title}</h3><span>{cluster['training_occurrences']} earlier examples</span></div>
      <p>{summary}</p>
      <p class='clock'>{clock}</p>
      <p class='evidence'><strong>Evidence:</strong> {cluster['training_occurrences']} earlier examples, {len(matches)} later repeats, {agreements}/{len(matches)} same chess reason.</p>
      <div class='cue'><strong>Try this:</strong> {cue}</div>
      {game_link}
    </section>"""


def build_html(evidence: Dict[str, Any], source_name: str) -> str:
    experiment = evidence["experiment"]
    validation = evidence["validation"]
    explorer = cluster_explorer(validation)
    display_clusters = useful_clusters(validation)
    cluster = display_clusters[0] if display_clusters else None
    username = html.escape(experiment["username"])
    controls = experiment.get("allowed_time_controls", [])
    control_description = (
        f"exact {', '.join(str(item) for item in controls)} second controls"
        if controls else "all available controls"
    )
    if cluster is None:
        repeat_errors = recurring_error_families(validation)
        mapped_errors = error_map(validation)
        repeat_cards = "".join(recurring_error_card(row, validation) for row in repeat_errors)
        map_cards = "".join(error_map_card(row) for row in mapped_errors)
        repeat_section = (
            f"<div class='eyebrow'>Your verified personal triggers</div><h2>What keeps happening</h2><p class='intro'>These are narrow, Stockfish-checked situations that appeared in older games and again in later games. Broad error labels are intentionally left out.</p><div class='patterns'>{repeat_cards}</div>"
            if repeat_errors else ""
        )
        map_section = (
            f"<div class='eyebrow'>Your engine-confirmed error map</div><h2>What Stockfish actually found</h2><p class='intro'>These are individual mistake types found across your games. They are useful things to check, but they are not being claimed as repeat habits yet.</p><div class='patterns'>{map_cards}</div>"
            if mapped_errors and not repeat_errors else ""
        )
        if repeat_errors:
            body = repeat_section
        else:
            body = map_section + """
            <section class='status'><p>Stockfish found concrete errors, but none had a narrow trigger that also repeated in later games. The report is withholding personalized advice instead of inventing one.</p></section>
            """
    else:
        cards = "".join(
            f"<div class='metric'><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span></div>"
            for value, label in evidence_cards(cluster, validation)
        )
        other_clusters = display_clusters[1:]
        other_cards = "".join(cluster_card(item, validation) for item in other_clusters)
        other_section = (
            f"<section class='other'><h2>Two more repeat patterns</h2><div class='patterns'>{other_cards}</div></section>"
            if other_clusters else ""
        )
        withheld = max(0, len(validation.get("clusters", [])) - len(display_clusters))
        withheld_note = (
            f"<p class='boundary'>{withheld} weaker groups are not shown as advice because they did not repeat clearly enough in later games.</p>"
            if withheld else ""
        )
        body = f"""
        <div class='eyebrow'>Your strongest repeat pattern</div>
        <h2>{html.escape(cluster_title(cluster))}</h2>
        <p class='intro'>A pattern means several mistakes happened in similar chess situations. It is a practice clue, not a judgement about your style.</p>
        <div class='grid'>{cards}</div>
        <div class='patterns'>{cluster_card(cluster, validation, featured=True)}</div>
        {other_section}
        {withheld_note}
        <p class='boundary'>How this was checked: Stockfish identified the mistakes first. The report grouped similar board situations, then checked later games that were not used to create the groups.</p>
        """
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Chess Psych - {username}</title><style>
:root{{--ink:#14213d;--muted:#596579;--paper:#f5f7fa;--line:#d8e0ea;--navy:#174477;--green:#137a58;--panel:#fff}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Segoe UI,Arial,sans-serif}}main{{width:min(900px,calc(100vw - 32px));margin:0 auto;padding:42px 0}}.eyebrow{{color:var(--muted);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}h1{{margin:8px 0 3px;font-size:38px}}h2{{margin:25px 0 12px;font-size:24px}}.eyebrow+h2{{margin-top:7px;font-size:30px}}h3{{margin:0;font-size:19px}}.sub,.intro{{margin:0 0 20px;color:var(--muted);line-height:1.5}}.panel{{padding:24px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}.metric{{min-height:80px;padding:12px;border:1px solid var(--line);border-radius:6px;background:#fbfcfe}}.metric strong{{display:block;color:var(--navy);font-size:22px}}.metric span{{display:block;margin-top:7px;color:var(--muted);font-size:12px;line-height:1.3}}.patterns{{display:grid;gap:12px;margin-top:16px}}.pattern{{padding:17px;border:1px solid var(--line);border-radius:7px;background:#fbfcfe}}.pattern.featured{{border-left:5px solid var(--green);background:#f2faf6}}.pattern-title{{display:flex;align-items:baseline;justify-content:space-between;gap:12px}}.pattern-title span{{color:var(--muted);font-size:13px;white-space:nowrap}}.pattern p{{margin:10px 0 0;line-height:1.45}}.pattern .clock{{color:var(--muted)}}.pattern .evidence{{font-size:13px;color:var(--muted)}}.pattern .personal-read{{padding:10px 12px;border-radius:5px;background:#edf4fb;color:#254c72}}.pattern .example{{font-size:14px;color:#254c72}}code{{padding:1px 4px;border-radius:3px;background:#e7edf5;font-family:Consolas,monospace}}.cue{{margin-top:14px;padding:11px 12px;border-radius:5px;background:#e8f4ed;line-height:1.45}}.technical{{margin-top:12px;color:var(--muted);font-size:13px}}.technical summary{{cursor:pointer;font-weight:750;color:var(--navy)}}.technical div{{display:grid;gap:4px;margin-top:8px;padding-left:12px;border-left:2px solid var(--line)}}.technical span::before{{content:'• ';color:var(--green)}}.pattern a{{display:inline-block;margin-top:14px}}.status{{margin-top:22px;padding:14px 17px;border:1px solid var(--line);border-left:4px solid var(--navy);border-radius:6px;background:#f7f9fc}}.status h2{{margin:0;font-size:19px}}.status p{{margin:0;color:var(--muted);line-height:1.45}}.boundary{{margin:20px 0 0;color:var(--muted);line-height:1.5}}a{{color:var(--navy);font-weight:750;text-decoration:none}}a:hover{{text-decoration:underline}}@media(max-width:600px){{main{{width:calc(100vw - 20px);padding-top:22px}}.grid{{grid-template-columns:1fr}}h1{{font-size:31px}}.pattern-title{{align-items:flex-start;flex-direction:column;gap:3px}}.pattern-title span{{white-space:normal}}}}
.cluster-explorer{{margin-top:24px;padding:24px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}}.cluster-explorer h2{{margin-top:7px}}.cluster-summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}}.cluster-choices{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:18px}}.cluster-choice{{display:flex;min-height:112px;flex-direction:column;align-items:flex-start;gap:7px;border:1px solid var(--line);border-radius:6px;padding:12px;background:#fbfcfe;color:var(--ink);text-align:left;cursor:pointer}}.cluster-choice:hover,.cluster-choice.selected{{border-color:var(--navy);box-shadow:0 0 0 2px #d9e7f8}}.cluster-choice span{{color:var(--green);font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}}.cluster-choice strong{{font-size:15px;line-height:1.25}}.cluster-choice em{{margin-top:auto;color:var(--muted);font-size:13px;font-style:normal}}.cluster-panel{{display:none;margin-top:16px;padding:17px;border:1px solid #c8d9ea;border-radius:6px;background:#fbfdff}}.cluster-panel.selected{{display:block}}.cluster-detail{{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:20px;align-items:start}}.cluster-detail h3{{margin-top:6px;font-size:21px}}.cluster-detail p{{line-height:1.5}}.cluster-metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}}.cluster-metrics span{{padding:9px;border-radius:5px;background:#eef4fb;color:var(--muted);font-size:12px}}.cluster-metrics strong{{display:block;color:var(--navy);font-size:18px}}.cluster-note{{font-size:14px;color:var(--muted)}}.mini-board{{display:grid;grid-template-columns:repeat(8,1fr);width:280px;max-width:100%;border:5px solid #3f2d1f;aspect-ratio:1}}.square{{display:grid;place-items:center;font-size:29px;line-height:1}}.square.light{{background:#ecd5ae}}.square.dark{{background:#96704b}}.empty-clusters p{{color:var(--muted);line-height:1.5}}
</style></head><body><main><div class='eyebrow'>Chess Psych personal report</div><h1>{username}</h1><p class='sub'>{experiment['games']} public {html.escape(str(experiment['time_class']))} games, {html.escape(control_description)}. Stockfish evidence with a later-game check.</p><article class='panel'>{body}</article>{explorer}</main><script>document.querySelectorAll('.cluster-choice').forEach(function(button){{button.addEventListener('click',function(){{var id=button.dataset.cluster;document.querySelectorAll('.cluster-choice').forEach(function(item){{var selected=item===button;item.classList.toggle('selected',selected);item.setAttribute('aria-pressed',String(selected));}});document.querySelectorAll('.cluster-panel').forEach(function(panel){{panel.classList.toggle('selected',panel.dataset.clusterPanel===id);}});}});}});</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a file:// report from a personal evidence JSON.")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = read_json(args.evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(evidence, args.evidence.name), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
