"""End-to-end smoke test using a temp DB and synthetic PGNs.

Runs the full Phase 1+2 pipeline (ingest -> blunders -> cluster -> summary)
against three made-up games. Uses real Stockfish but never touches the
network. Useful for verifying nothing's regressed before shipping.

Run:
    python smoke_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

# Point the config at a temp DB BEFORE other modules import the config singleton.
TMP_DB = Path(tempfile.mkdtemp()) / "smoke.db"
os.environ["CHESS_PSYCH_DB"] = str(TMP_DB)
os.environ["LOG_LEVEL"] = "WARNING"  # quiet during smoke

# Now import everything
from config import setup_logging  # noqa: E402
setup_logging()

from blunders import detect_blunders  # noqa: E402
from db import get_conn, get_or_create_user, init_db  # noqa: E402
from features import extract_move_features  # noqa: E402
from ingest import ingest_pgn  # noqa: E402
from llm_summary import generate_user_summary  # noqa: E402
from patterns import cluster_blunders  # noqa: E402
from stockfish_pool import StockfishPool  # noqa: E402

import chess  # noqa: E402

# Three synthetic games — each has a blunder somewhere
TEST_PGNS = [
"""[Event "Test1"]
[Site "test1"]
[Date "2024.01.01"]
[Round "1"]
[White "TestUser"]
[Black "Opp"]
[Result "0-1"]
[ECO "C20"]
[WhiteElo "1500"]
[BlackElo "1500"]

1. e4 e5 2. Bc4 Nf6 3. Nf3 Nxe4 4. Nc3 Nxc3 5. dxc3 d6 6. Qxd6 cxd6 7. Bb5+ Bd7 8. Bxd7+ Nxd7 0-1
""",
"""[Event "Test2"]
[Site "test2"]
[Date "2024.01.02"]
[Round "1"]
[White "TestUser"]
[Black "Opp"]
[Result "0-1"]
[ECO "C50"]
[WhiteElo "1500"]
[BlackElo "1500"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6 5. d3 d6 6. Nc3 O-O 7. Bg5 h6 8. Bh4 g5 9. Bg3 Nh5 10. Nd5 Nxg3 11. hxg3 Bg4 12. Qd2 Bxf3 13. gxf3 Qf6 14. Kg2 Nd4 15. Rh1 Nxf3 0-1
""",
"""[Event "Test3"]
[Site "test3"]
[Date "2024.01.03"]
[Round "1"]
[White "TestUser"]
[Black "Opp"]
[Result "0-1"]
[ECO "C50"]
[WhiteElo "1500"]
[BlackElo "1500"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. d3 Bc5 5. O-O O-O 6. Bg5 h6 7. Bh4 d6 8. Nbd2 Bg4 9. h3 Bxf3 10. Nxf3 Nh5 11. Bxd8 Rxd8 0-1
""",
]


def step(msg: str) -> None:
    print(f"\n>>> {msg}")


def test_a_features():
    step("[A] features.extract_move_features")
    b = chess.Board()
    move = chess.Move.from_uci("e2e4")
    san, uci = b.san(move), move.uci()
    fb = b.fen()
    b.push(move)
    feats = extract_move_features(
        fen_before=fb, fen_after=b.fen(), san=san, uci=uci,
        time_spent=2.0, eval_before=20, eval_after=30,
        side="white", eco="C20",
    )
    assert feats["piece"] == "pawn"
    assert feats["phase"] == "opening"
    print(f"    OK — piece={feats['piece']} phase={feats['phase']}")


def test_b_schema():
    step("[B] init_db creates schema")
    init_db()
    with get_conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"users", "games", "moves", "blunders", "patterns"}
    missing = expected - tables
    assert not missing, f"missing tables: {missing}"
    print(f"    OK — tables present: {sorted(tables)}")


def test_c_full_pipeline():
    step("[C] Full ingest -> blunders -> cluster pipeline")
    sf = StockfishPool()
    sf.start()
    try:
        with get_conn() as conn:
            uid = get_or_create_user(conn, "TestUser", "chess.com", rating=1500)
            for i, pgn in enumerate(TEST_PGNS, 1):
                gid = ingest_pgn(
                    conn, uid, "TestUser", pgn,
                    external_id=f"test/{i}",
                    time_class="blitz",
                    stockfish=sf, eval_depth=8,
                )
                print(f"    ingested game_id={gid}")

        with get_conn() as conn:
            n_moves = conn.execute(
                """SELECT COUNT(*) FROM moves m JOIN games g ON m.game_id=g.id
                   WHERE g.user_id=?""",
                (uid,),
            ).fetchone()[0]
        print(f"    moves stored: {n_moves}")
        assert n_moves > 30

        n_blunders = detect_blunders(uid)
        print(f"    blunders detected: {n_blunders}")
        assert n_blunders >= 1

        result = cluster_blunders(uid, min_cluster_size=2)
        print(f"    clusters: {len(result['clusters'])}  noise: {result.get('n_noise', 0)}")

        summary = generate_user_summary(uid, use_llm=False)
        print("\n--- mechanical summary ---")
        print(summary)
        print("--- end ---\n")
        assert "blunder" in summary.lower() or "pattern" in summary.lower()
    finally:
        sf.close()


if __name__ == "__main__":
    test_a_features()
    test_b_schema()
    test_c_full_pipeline()
    print("\nALL SMOKE TESTS PASSED.")
