"""Build a chronological, evidence-backed personal-pattern demo artifact.

Example:
    python scripts/build_personal_pattern_demo.py MishilT --max-games 160

Public games and engine checkpoints are cached under demos/generated so an
interrupted run can resume without repeating completed analysis.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import chess
import chess.pgn

from chess_psych.chesscom_client import ArchivedGame, ChessComClient
from chess_psych.features import PIECE_NAMES, clock_context, parse_time_control, phase_of
from chess_psych.ingest import parse_clock_comment
from chess_psych.personal_validation import (
    ErrorObservation,
    adaptive_risk_patterns,
    error_threshold,
    extract_error_features,
    user_eval_drop,
    validate_patterns,
)
from chess_psych.ollama_labels import label_clusters
from chess_psych.stockfish_pool import StockfishPool


# Increment when the per-error feature packet changes. Cached Stockfish work
# must not be reused when a report needs newer explanatory fields.
ANALYSIS_SCHEMA_VERSION = 9


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A process can be interrupted while updating a local checkpoint.
        # Treat an unreadable cache as absent rather than blocking a rerun.
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # OneDrive can briefly lock a target during atomic replacement. Direct
    # writes are reliable in this synced workspace; _read_json handles an
    # interrupted local checkpoint on the next run.
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _game_to_dict(game: ArchivedGame) -> Dict[str, Any]:
    return asdict(game)


def parse_allowed_time_controls(raw: str) -> Optional[tuple[str, ...]]:
    """Parse exact controls, or accept ``any`` for one whole time class."""
    if raw.strip().lower() in {"any", "all", "auto"}:
        return None
    controls = tuple(sorted({item.strip() for item in raw.split(",") if item.strip()}))
    if not controls or any(not control.replace("+", "").isdigit() for control in controls):
        raise ValueError("--allowed-time-controls must be a comma-separated list such as 180,300")
    return controls


def fetch_games(
    username: str,
    max_games: int,
    time_class: str,
    cache: Path,
    *,
    refresh: bool = False,
    display_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    cached = _read_json(cache, [])
    if not refresh and len(cached) >= max_games:
        return cached[:max_games]
    print(f"Fetching {max_games} public {time_class} games for {display_name or username}...")
    with ChessComClient() as client:
        games = list(client.iter_games(
            username,
            max_games=max_games,
            time_classes=[time_class],
            rated_only=True,
        ))
    payload = [_game_to_dict(g) for g in games]
    _write_json(cache, payload)
    return payload


def checkpoint_meta(args: argparse.Namespace, allowed_controls: Optional[tuple[str, ...]]) -> Dict[str, Any]:
    """Describe every setting that changes stored Stockfish observations."""
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "username": args.username.lower(),
        "time_class": args.time_class,
        "allowed_time_controls": list(allowed_controls or ()),
        "screen_depth": args.screen_depth,
        "confirm_depth": args.confirm_depth,
    }


def _played_at(game: Dict[str, Any]) -> str:
    timestamp = game.get("end_time")
    if timestamp:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    return ""


def _user_rating(game: Dict[str, Any], color: chess.Color) -> Optional[int]:
    return game.get("white_rating" if color == chess.WHITE else "black_rating")


def _opponent(game: Dict[str, Any], color: chess.Color) -> str:
    return game.get("black_username" if color == chess.WHITE else "white_username", "")


def analyze_game(
    game_data: Dict[str, Any],
    username: str,
    engine: StockfishPool,
    screen_depth: int,
    confirm_depth: int,
) -> List[ErrorObservation]:
    game = chess.pgn.read_game(io.StringIO(game_data["pgn"]))
    if game is None:
        return []
    white = game.headers.get("White", "")
    black = game.headers.get("Black", "")
    username_lc = username.lower()
    if white.lower() == username_lc:
        user_color = chess.WHITE
    elif black.lower() == username_lc:
        user_color = chess.BLACK
    else:
        return []

    board = game.board()
    # The benchmark is deliberately standard-chess only. Chess.com archives
    # can include Chess960 or other variants that a standard UCI engine cannot
    # evaluate with the same assumptions.
    if board.uci_variant != "chess":
        return []
    observations: List[ErrorObservation] = []
    previous_move: Optional[chess.Move] = None
    previous_was_capture = False
    previous_clock: Dict[chess.Color, Optional[float]] = {
        chess.WHITE: None,
        chess.BLACK: None,
    }
    initial_seconds, increment_seconds = parse_time_control(
        game.headers.get("TimeControl") or game_data.get("time_control")
    )
    node = game
    ply = 0
    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        ply += 1
        board_before = board.copy(stack=False)
        side = board_before.turn
        was_capture = board_before.is_capture(move)
        san = board_before.san(move)
        clock_remaining = parse_clock_comment(next_node.comment)
        time_spent: Optional[float] = None
        if clock_remaining is not None:
            prior_clock = previous_clock[side]
            if prior_clock is None:
                prior_clock = initial_seconds
            if prior_clock is not None:
                elapsed = prior_clock + increment_seconds - clock_remaining
                # Chess.com clocks are rounded. Treat a tiny negative number as zero,
                # but leave genuinely inconsistent comments out of the model.
                if elapsed >= -0.2:
                    time_spent = max(0.0, elapsed)
            previous_clock[side] = clock_remaining
        board.push(move)
        board_after = board.copy(stack=False)

        if board_before.turn == user_color and ply >= 6:
            before_screen = engine.analyse(board_before, depth=screen_depth)
            after_screen = engine.analyse(board_after, depth=screen_depth)
            rating = _user_rating(game_data, user_color)
            threshold = error_threshold(rating)
            screen_drop = user_eval_drop(before_screen, after_screen, user_color)
            if screen_drop >= int(threshold * 0.70):
                candidates = engine.analyse_with_pv(board_before, depth=confirm_depth, multipv=2)
                if candidates:
                    before_confirm = candidates[0]["eval_cp"]
                    reply_candidates = engine.analyse_with_pv(
                        board_after, depth=confirm_depth, multipv=1,
                    )
                    after_confirm = (
                        reply_candidates[0]["eval_cp"]
                        if reply_candidates else engine.analyse(board_after, depth=confirm_depth)
                    )
                    confirmed_drop = user_eval_drop(before_confirm, after_confirm, user_color)
                    if confirmed_drop >= threshold:
                        best_move = candidates[0]["move"]
                        opponent_best_reply = reply_candidates[0]["move"] if reply_candidates else None
                        features = extract_error_features(
                            board_before,
                            board_after,
                            move,
                            best_move,
                            previous_move=previous_move,
                            previous_was_capture=previous_was_capture,
                            opponent_best_reply=opponent_best_reply,
                            eval_drop_cp=confirmed_drop,
                            time_class=game_data.get("time_class", ""),
                            clock_remaining=clock_remaining,
                            time_spent=time_spent,
                            time_control=game.headers.get("TimeControl") or game_data.get("time_control"),
                        )
                        observations.append(ErrorObservation(
                            game_url=game_data.get("url", ""),
                            played_at=_played_at(game_data),
                            time_class=game_data.get("time_class", ""),
                            user_color="white" if user_color == chess.WHITE else "black",
                            user_rating=rating,
                            opponent=_opponent(game_data, user_color),
                            ply=ply,
                            move_number=(ply + 1) // 2,
                            san=san,
                            uci=move.uci(),
                            fen_before=board_before.fen(),
                            fen_after=board_after.fen(),
                            eval_before_cp=before_confirm,
                            eval_after_cp=after_confirm,
                            eval_drop_cp=confirmed_drop,
                            threshold_cp=threshold,
                            best_move_san=board_before.san(best_move),
                            best_move_uci=best_move.uci(),
                            features=features,
                            opponent_best_reply_san=(
                                board_after.san(opponent_best_reply)
                                if opponent_best_reply else None
                            ),
                            opponent_best_reply_uci=(
                                opponent_best_reply.uci() if opponent_best_reply else None
                            ),
                            clock_remaining_seconds=clock_remaining,
                            time_spent_seconds=time_spent,
                            initial_seconds=initial_seconds,
                        ))
        previous_move = move
        previous_was_capture = was_capture
        node = next_node
    return observations


def extract_decision_contexts(game_data: Dict[str, Any], username: str) -> List[Dict[str, Any]]:
    """Replay all of one player's decisions without invoking the engine.

    Error counts alone cannot show whether a context is unusually risky for a
    player. These rows provide the denominator for that comparison.
    """
    game = chess.pgn.read_game(io.StringIO(game_data["pgn"]))
    if game is None:
        return []
    username_lc = username.lower()
    if game.headers.get("White", "").lower() == username_lc:
        user_color = chess.WHITE
    elif game.headers.get("Black", "").lower() == username_lc:
        user_color = chess.BLACK
    else:
        return []

    board = game.board()
    if board.uci_variant != "chess":
        return []
    initial_seconds, increment_seconds = parse_time_control(
        game.headers.get("TimeControl") or game_data.get("time_control")
    )
    previous_clock: Dict[chess.Color, Optional[float]] = {
        chess.WHITE: None,
        chess.BLACK: None,
    }
    decisions: List[Dict[str, Any]] = []
    node = game
    ply = 0
    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        ply += 1
        board_before = board.copy(stack=False)
        side = board_before.turn
        clock_remaining = parse_clock_comment(next_node.comment)
        time_spent: Optional[float] = None
        if clock_remaining is not None:
            prior_clock = previous_clock[side]
            if prior_clock is None:
                prior_clock = initial_seconds
            if prior_clock is not None:
                elapsed = prior_clock + increment_seconds - clock_remaining
                if elapsed >= -0.2:
                    time_spent = max(0.0, elapsed)
            previous_clock[side] = clock_remaining

        if side == user_color and ply >= 6:
            piece = board_before.piece_at(move.from_square)
            decisions.append({
                "game_url": game_data.get("url", ""),
                "played_at": _played_at(game_data),
                "ply": ply,
                "features": {
                    "phase": phase_of(board_before),
                    "piece": PIECE_NAMES.get(piece.piece_type, "unknown") if piece else "unknown",
                    "time_context": clock_context(clock_remaining, initial_seconds, time_spent),
                },
            })
        board.push(move)
        node = next_node
    return decisions


def build(args: argparse.Namespace) -> Dict[str, Any]:
    generated = ROOT / "demos" / "generated"
    slug = args.username.lower()
    allowed_controls = parse_allowed_time_controls(args.allowed_time_controls)
    controls_slug = "all" if allowed_controls is None else "_".join(
        control.replace("+", "p") for control in allowed_controls
    )
    game_cache = generated / f"{slug}_{args.time_class}_{controls_slug}_{args.max_games}_games.json"
    checkpoint = generated / f"{slug}_{args.time_class}_{controls_slug}_analysis.json"
    output = Path(args.output) if args.output else ROOT / "demos" / "personal_pattern_evidence.json"

    games = fetch_games(
        args.username,
        args.max_games,
        args.time_class,
        game_cache,
        refresh=args.refresh_games,
        display_name=args.display_name,
    )
    if allowed_controls is not None:
        games = [
            game for game in games
            if str(game.get("time_control", "")) in allowed_controls
        ]
    if not games:
        available_controls = sorted({
            str(game.get("time_control", "")) for game in fetch_games(
                args.username, args.max_games, args.time_class, game_cache,
                refresh=False, display_name=args.display_name,
            ) if game.get("time_control")
        })
        available_note = (
            f" Available recent controls: {', '.join(available_controls)}."
            if available_controls else ""
        )
        raise ValueError(
            f"No {args.time_class} games found with the selected controls."
            f" Choose a different format or use 'any' controls.{available_note}"
        )
    games = sorted(games, key=lambda g: g.get("end_time") or 0)
    existing = _read_json(checkpoint, {"games": {}, "meta": {}})
    run_meta = checkpoint_meta(args, allowed_controls)
    if existing.get("meta") != run_meta:
        completed: Dict[str, List[Dict[str, Any]]] = {}
    else:
        completed = existing.get("games", {})

    with StockfishPool(threads=args.threads, hash_mb=args.hash_mb) as engine:
        for index, game in enumerate(games, 1):
            key = game.get("url") or str(game.get("end_time"))
            if key in completed:
                continue
            observations = analyze_game(
                game, args.username, engine, args.screen_depth, args.confirm_depth,
            )
            completed[key] = [o.to_dict() for o in observations]
            _write_json(checkpoint, {
                "meta": {
                    **run_meta,
                },
                "games": completed,
            })
            print(f"[{index:>3}/{len(games)}] {key}: {len(observations)} confirmed errors")

    observations = [
        ErrorObservation(**item)
        for game in games
        for item in completed.get(game.get("url") or str(game.get("end_time")), [])
    ]
    observations = [
        observation for observation in observations
        if observation.eval_drop_cp >= max(args.min_error_cp, observation.threshold_cp)
        and abs(observation.eval_before_cp) < 9000
        and abs(observation.eval_after_cp) < 9000
    ]
    dated_games = [g for g in games if g.get("end_time")]
    cutoff_index = max(1, min(len(dated_games) - 1, int(len(dated_games) * args.train_fraction)))
    cutoff = _played_at(dated_games[cutoff_index])
    validation = validate_patterns(
        observations,
        cutoff=cutoff,
        min_cluster_size=args.min_cluster_size,
        focus_rule_label=args.focus_rule_label,
    )
    validation["game_split"] = {
        "earlier_games": sum(1 for game in games if _played_at(game) < cutoff),
        "later_games": sum(1 for game in games if _played_at(game) >= cutoff),
    }
    decisions = [
        decision
        for game in games
        for decision in extract_decision_contexts(game, args.username)
    ]
    validation["adaptive_risk_patterns"] = adaptive_risk_patterns(
        observations,
        decisions,
        cutoff=cutoff,
    )
    result = {
        "experiment": {
            "username": args.username,
            "source": "Chess.com public API",
            "time_class": args.time_class,
            "allowed_time_controls": list(allowed_controls or ()),
            "games": len(games),
            "training_fraction": args.train_fraction,
            "screen_depth": args.screen_depth,
            "confirm_depth": args.confirm_depth,
            "minimum_error_floor_cp": args.min_error_cp,
            "rating_relative_thresholds": True,
            "method": "Chronological holdout; HDBSCAN on older engine-confirmed errors",
            "focus_rule_label": args.focus_rule_label,
            "accuracy_note": (
                "Clustering is unsupervised. Silhouette measures separation; rule agreement "
                "and holdout recurrence measure consistency, not supervised accuracy."
            ),
        },
        "validation": validation,
    }
    if not args.skip_ai_labels:
        result["validation"]["ai_labels"] = label_clusters(
            validation.get("clusters", []),
            model=args.ollama_model,
            limit=args.max_cluster_labels,
        )
    _write_json(output, result)
    print(f"Wrote evidence to {output}")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("username")
    p.add_argument(
        "--display-name",
        help="Optional terminal-only progress label; does not change the Chess.com username used for fetching.",
    )
    p.add_argument("--time-class", default="blitz", choices=["bullet", "blitz", "rapid"])
    p.add_argument(
        "--allowed-time-controls",
        default="180,300",
        help="Comma-separated exact Chess.com controls, or 'any' for all controls in one time class. Defaults to 3- and 5-minute blitz.",
    )
    p.add_argument("--max-games", type=int, default=160)
    p.add_argument("--train-fraction", type=float, default=0.75)
    p.add_argument("--screen-depth", type=int, default=6)
    p.add_argument("--confirm-depth", type=int, default=10)
    p.add_argument("--min-cluster-size", type=int, default=4)
    p.add_argument(
        "--focus-rule-label",
        help="Optionally cluster the context around one strict chess-rule label, such as 'Missed tactical capture'.",
    )
    p.add_argument(
        "--min-error-cp",
        type=int,
        default=0,
        help="Optional global floor in centipawns. The default keeps the per-player rating threshold.",
    )
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--hash-mb", type=int, default=16)
    p.add_argument("--ollama-model", default="qwen2.5:7b-instruct")
    p.add_argument("--max-cluster-labels", type=int, default=3)
    p.add_argument("--skip-ai-labels", action="store_true")
    p.add_argument(
        "--refresh-games",
        action="store_true",
        help="Fetch the latest public archive data before reusing any local game cache.",
    )
    p.add_argument("--output")
    return p


if __name__ == "__main__":
    build(parser().parse_args())
