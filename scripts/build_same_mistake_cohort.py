"""Build the three-player 'same reference move, different coaching' artifact."""
from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable

import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chess_psych.ollama_labels import evidence_label, label_cluster
from chess_psych.personal_validation import MODEL_FIELDS


PLAYERS = (
    {
        "username": "erolmcc",
        "display_name": "Player X",
        "rating": 657,
        "band": "Lower-rated comparison",
        "selection": "best_validated",
        "display_label": "King moves with time available",
        "recommendation": "Before moving your king, identify the opponent's checks, captures, and threats.",
    },
    {
        "username": "MishilT",
        "display_name": "MishilT",
        "rating": 1290,
        "band": "Your profile",
        "selection": "largest_recurrent",
        "display_label": "Middlegame rook moves with time available",
        "recommendation": "Before moving a rook, ask what your opponent can do now and where the rook helps next.",
    },
    {
        "username": "hikaru",
        "display_name": "Hikaru",
        "rating": 3420,
        "band": "Higher-rated comparison",
        "selection": "most_quick_recurrent",
        "display_label": "Quick middlegame queen moves",
        "recommendation": "Before a quick queen move, take one second to scan checks, captures, and threats.",
    },
)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def quick_share(cluster: Dict[str, Any]) -> float:
    evidence = cluster["label_evidence"]
    return evidence["time_context_counts"].get("quick", 0) / max(evidence["members"], 1)


def choose_cluster(
    clusters: Iterable[Dict[str, Any]], strategy: str, holdout: Iterable[Dict[str, Any]]
) -> Dict[str, Any]:
    clusters = list(clusters)
    holdout = list(holdout)
    if strategy == "best_validated":
        # Selection is based on later rule agreement, never on a dramatic move.
        def quality(cluster: Dict[str, Any]) -> tuple[int, float, int]:
            matches = [m for m in holdout if m["cluster_id"] == cluster["cluster_id"]]
            true_positives = sum(bool(m["rule_agrees"]) for m in matches)
            precision = true_positives / len(matches) if matches else 0.0
            return true_positives, precision, cluster["training_occurrences"]

        return max(clusters, key=quality)
    if strategy == "largest_recurrent":
        return max(clusters, key=lambda c: (c["holdout_recurrences"], c["training_occurrences"], c["family_purity"]))
    if strategy == "most_quick_recurrent":
        candidates = [cluster for cluster in clusters if cluster["holdout_recurrences"] > 0]
        return max(candidates, key=lambda c: (quick_share(c), c["holdout_recurrences"], c["training_occurrences"]))
    raise ValueError(f"Unknown selection strategy: {strategy}")


def dominant_clock(cluster: Dict[str, Any]) -> str:
    counts = cluster["label_evidence"]["time_context_counts"]
    return max(counts, key=counts.get)


def dominant_phase(cluster: Dict[str, Any]) -> str:
    counts = cluster["label_evidence"]["phase_counts"]
    return max(counts, key=counts.get)


def choose_match(matches: Iterable[Dict[str, Any]], cluster: Dict[str, Any]) -> Dict[str, Any]:
    relevant = [match for match in matches if match["cluster_id"] == cluster["cluster_id"] and match["rule_agrees"]]
    if not relevant:
        relevant = [match for match in matches if match["cluster_id"] == cluster["cluster_id"]]
    desired_clock = dominant_clock(cluster)
    desired_phase = dominant_phase(cluster)
    same_clock = [match for match in relevant if match["time_context"] == desired_clock]
    same_context = [match for match in same_clock if match["phase"] == desired_phase]
    return min(same_context or same_clock or relevant, key=lambda match: match["normalized_distance"])


def move_label(board: chess.Board, move: chess.Move) -> str:
    prefix = f"{board.fullmove_number}." if board.turn else f"{board.fullmove_number}..."
    return f"{prefix} {board.san(move)}"


def build_replay(username: str, match: Dict[str, Any]) -> Dict[str, Any]:
    cache = ROOT / "demos" / "generated" / f"{username.lower()}_blitz_180_300_120_games.json"
    game_data = next(game for game in read_json(cache) if game["url"] == match["game_url"])
    game = chess.pgn.read_game(StringIO(game_data["pgn"]))
    if game is None:
        raise ValueError(f"Could not parse public PGN for {match['game_url']}")

    moves = list(game.mainline_moves())
    target_ply = int(match["ply"])
    start_ply = max(1, target_ply - 3)
    end_ply = min(len(moves), target_ply + 3)
    board = game.board()
    frames = []
    for ply, move in enumerate(moves, start=1):
        label = move_label(board, move)
        from_square = chess.square_name(move.from_square)
        to_square = chess.square_name(move.to_square)
        board.push(move)
        if start_ply <= ply <= end_ply:
            frames.append({
                "ply": ply,
                "label": label,
                "fen": board.fen(),
                "from": from_square,
                "to": to_square,
                "featured": ply == target_ply,
            })

    if not frames:
        raise ValueError(f"No replay frames found for {match['game_url']}")
    return {
        "white": game.headers.get("White", "White"),
        "black": game.headers.get("Black", "Black"),
        "time_control": game_data["time_control"],
        "frames": frames,
        "featured_ply": target_ply,
    }


def cluster_table(validation: Dict[str, Any], selected_id: int) -> list[Dict[str, Any]]:
    """Return every discovered cluster with a plain, auditable scorecard."""
    rows = []
    for cluster in validation["clusters"]:
        matches = [
            item for item in validation["holdout_matches"]
            if item["cluster_id"] == cluster["cluster_id"]
        ]
        agreements = sum(bool(item["rule_agrees"]) for item in matches)
        rows.append({
            "cluster_id": cluster["cluster_id"],
            "label": evidence_label(cluster["label_evidence"]),
            "older_examples": cluster["training_occurrences"],
            "later_matches": len(matches),
            "later_agreements": agreements,
            "selected": cluster["cluster_id"] == selected_id,
        })
    rows.sort(
        key=lambda row: (row["later_agreements"], row["later_matches"], row["older_examples"]),
        reverse=True,
    )
    return rows


def build() -> Dict[str, Any]:
    output_players = []
    for profile in PLAYERS:
        path = ROOT / "demos" / f"{profile['username'].lower()}_blitz_evidence.json"
        evidence = read_json(path)
        validation = evidence["validation"]
        cluster = choose_cluster(validation["clusters"], profile["selection"], validation["holdout_matches"])
        match = choose_match(validation["holdout_matches"], cluster)
        cluster_holdout = [
            item for item in validation["holdout_matches"]
            if item["cluster_id"] == cluster["cluster_id"]
        ]
        true_positives = sum(bool(item["rule_agrees"]) for item in cluster_holdout)
        output_players.append({
            **{key: value for key, value in profile.items() if key != "selection"},
            "selected_cluster": cluster,
            "cluster_table": cluster_table(validation, cluster["cluster_id"]),
            "ai_label": label_cluster(cluster),
            "representative_holdout_match": match,
            "replay": build_replay(profile["username"], match),
            "source_evidence": path.name,
            "method": {
                "algorithm": "HDBSCAN",
                "model_input_count": len(MODEL_FIELDS),
                "games": evidence["experiment"]["games"],
                "allowed_time_controls": evidence["experiment"]["allowed_time_controls"],
                "training_errors": validation["training_errors"],
                "holdout_errors": validation["holdout_errors"],
                "clustered_training_errors": validation["clustered_training_errors"],
                "noise_errors": validation["noise_errors"],
                "holdout_match_count": validation["holdout_match_count"],
                "overall_holdout_rule_agreement": validation["holdout_rule_agreement"],
                "cluster_count": validation.get("cluster_count", 0),
                "holdout_predictions": len(cluster_holdout),
                "holdout_rule_agreements": true_positives,
                "holdout_precision": round(true_positives / len(cluster_holdout), 3) if cluster_holdout else None,
            },
        })
    result = {
        "title": "Same reference move, different coaching",
        "shared_benchmark": {
            "source_player": next(player for player in output_players if player["username"] == "MishilT"),
            "scope": (
                "The replay is one fixed public reference move from MishilT's game. "
                "Each tab shows a different player's independently trained historical model results; "
                "it does not claim the other players made this exact move."
            ),
        },
        "claim_boundary": (
            "The fixed replay crossed MishilT's rating-relative Stockfish error threshold. "
            "The product compares independently learned recurring contexts from each player's own errors; "
            "it does not diagnose personality or predict that every player would make the reference move."
        ),
        "trust_controls": [
            "Exact 3- and 5-minute public Chess.com blitz games only",
            "Stockfish confirms the error before clustering",
            "Chronological holdout keeps later games out of training",
            "Rule-defining chess fields are excluded from HDBSCAN inputs",
            "Ollama supplies wording only and may abstain when evidence is mixed",
        ],
        "players": output_players,
    }
    output = ROOT / "demos" / "same_mistake_cohort_evidence.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    return result


if __name__ == "__main__":
    build()
