"""Chess Psych — command-line interface.

Subcommands:
    analyze   Full pipeline: ingest -> blunders -> cluster -> summary
    summary   Re-generate summary from already-ingested data
    stats     Show counts for a user
    clear     Delete all data for a user

Default platform is Chess.com (the hero path). Use --source lichess to
switch to the fallback.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

from blunders import detect_blunders
from config import config, setup_logging
from db import get_conn, get_or_create_user, init_db, delete_user_data
from ingest import ingest_chesscom_user, ingest_lichess_user
from llm_summary import generate_user_summary
from patterns import cluster_blunders

log = logging.getLogger("chess_psych.cli")


def _get_user_id(username: str, source: str) -> Optional[int]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? AND source = ?",
            (username, source),
        ).fetchone()
    return row["id"] if row else None


def cmd_analyze(args: argparse.Namespace) -> int:
    log.info("DB at %s", config.db_path)
    init_db()

    print(f"\n[1/4] Fetching up to {args.max_games} {args.source} games for "
          f"'{args.username}'{'  (time classes: ' + ','.join(args.time_class) + ')' if args.time_class else ''}...")
    t0 = time.time()
    try:
        if args.source == "chess.com":
            stats = ingest_chesscom_user(
                username=args.username,
                max_games=args.max_games,
                time_classes=args.time_class or None,
                rated_only=not args.include_unrated,
                use_stockfish=not args.no_stockfish,
                eval_depth=args.depth,
            )
        else:
            stats = ingest_lichess_user(
                username=args.username,
                max_games=args.max_games,
                use_stockfish=not args.no_stockfish,
                eval_depth=args.depth,
            )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"      done in {time.time() - t0:.1f}s — {stats.to_dict()}")

    user_id = _get_user_id(args.username, args.source)
    if not user_id:
        print("Error: user not found after ingestion (no matching games).",
              file=sys.stderr)
        return 1

    print("[2/4] Detecting blunders...")
    n = detect_blunders(user_id)
    print(f"      {n} blunders found.")

    print("[3/4] Clustering patterns...")
    result = cluster_blunders(user_id, min_cluster_size=args.min_cluster_size)
    print(f"      {len(result['clusters'])} clusters "
          f"({result.get('n_noise', 0)} unclassified blunders)")

    print("[4/4] Generating summary...")
    print("\n" + "=" * 70)
    print(f"  CHESS PROFILE — {args.username}")
    print("=" * 70)
    print(generate_user_summary(user_id, use_llm=not args.no_llm))
    print("=" * 70)
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    user_id = _get_user_id(args.username, args.source)
    if not user_id:
        print(f"No data for {args.username} on {args.source}. Run `analyze` first.",
              file=sys.stderr)
        return 1
    print(generate_user_summary(user_id, use_llm=not args.no_llm))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    user_id = _get_user_id(args.username, args.source)
    if not user_id:
        print(f"No data for {args.username} on {args.source}.", file=sys.stderr)
        return 1

    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        ng = conn.execute(
            "SELECT COUNT(*) AS c FROM games WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        nm = conn.execute(
            """SELECT COUNT(*) AS c FROM moves m
               JOIN games g ON m.game_id=g.id WHERE g.user_id=?""",
            (user_id,),
        ).fetchone()["c"]
        nb = conn.execute(
            "SELECT COUNT(*) AS c FROM blunders WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        npats = conn.execute(
            "SELECT COUNT(*) AS c FROM patterns WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        tc_counts = conn.execute(
            """SELECT time_class, COUNT(*) AS c FROM games
               WHERE user_id=? GROUP BY time_class ORDER BY c DESC""",
            (user_id,),
        ).fetchall()

    print(f"User       : {user['username']} ({user['source']})")
    print(f"Ratings    : bullet={user['bullet_rating']} blitz={user['blitz_rating']} "
          f"rapid={user['rapid_rating']} daily={user['daily_rating']}")
    print(f"Games      : {ng}")
    if tc_counts:
        breakdown = ", ".join(f"{r['time_class']}={r['c']}" for r in tc_counts)
        print(f"  by class : {breakdown}")
    print(f"Moves      : {nm}")
    print(f"Blunders   : {nb}")
    print(f"Patterns   : {npats}")

    if npats:
        print("\nTop patterns:")
        with get_conn() as conn:
            for p in conn.execute(
                """SELECT name, description, size FROM patterns
                   WHERE user_id=? ORDER BY size DESC""",
                (user_id,),
            ):
                print(f"  - {p['name']} ({p['size']}×)")
                print(f"    {p['description']}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    user_id = _get_user_id(args.username, args.source)
    if not user_id:
        print("User not found.")
        return 1
    with get_conn() as conn:
        delete_user_data(conn, user_id)
    print(f"Cleared all data for {args.username} ({args.source}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chess_psych",
        description="Personal blunder-pattern coach using Chess.com data.",
    )
    p.add_argument("--log-level", default=None,
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Override log level (default: from LOG_LEVEL env)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # analyze
    a = sub.add_parser("analyze", help="Run the full pipeline")
    a.add_argument("username")
    a.add_argument("--source", choices=["chess.com", "lichess"], default="chess.com")
    a.add_argument("--max-games", type=int, default=30)
    a.add_argument("--time-class", action="append",
                   choices=["bullet", "blitz", "rapid", "daily"],
                   help="Filter to one or more time classes. Repeat to allow multiple.")
    a.add_argument("--include-unrated", action="store_true")
    a.add_argument("--depth", type=int, default=None,
                   help=f"Stockfish depth (default {config.stockfish_depth})")
    a.add_argument("--min-cluster-size", type=int, default=None,
                   help=f"HDBSCAN min_cluster_size (default {config.cluster_min_size})")
    a.add_argument("--no-stockfish", action="store_true")
    a.add_argument("--no-llm", action="store_true")
    a.set_defaults(func=cmd_analyze)

    # summary
    s = sub.add_parser("summary", help="Regenerate summary from stored data")
    s.add_argument("username")
    s.add_argument("--source", choices=["chess.com", "lichess"], default="chess.com")
    s.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_summary)

    # stats
    st = sub.add_parser("stats", help="Show stored stats for a user")
    st.add_argument("username")
    st.add_argument("--source", choices=["chess.com", "lichess"], default="chess.com")
    st.set_defaults(func=cmd_stats)

    # clear
    cl = sub.add_parser("clear", help="Delete all data for a user")
    cl.add_argument("username")
    cl.add_argument("--source", choices=["chess.com", "lichess"], default="chess.com")
    cl.set_defaults(func=cmd_clear)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
