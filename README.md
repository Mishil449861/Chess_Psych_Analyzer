# Chess Psych

A personal blunder-pattern coach for Chess.com players.

Most chess training tools give you stats. This one finds the *recurring shapes* of your mistakes — the f7 weakness you've fallen into eight times this month, the queen-trade habit you don't realize you have — and tells you about them in plain language.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt
sudo apt install stockfish    # or `brew install stockfish` on macOS

# 2. Run the full pipeline against your Chess.com username
python cli.py analyze YourChessComName --max-games 50

# 3. Just blitz games
python cli.py analyze YourChessComName --time-class blitz --max-games 50

# 4. See what was found
python cli.py stats YourChessComName
```

Optional: run a local [Ollama](https://ollama.com) server with `llama3` to get LLM-polished pattern names and a personalized profile paragraph. The system works fully without it — it just falls back to mechanical descriptions.

## What it does

1. **Ingest** the last N games from the Chess.com public API.
2. **Evaluate** each position with Stockfish (or use inline PGN evals when present).
3. **Detect blunders** using a rating-calibrated threshold (a 100cp drop is a blunder at 2000, a 200cp drop is a blunder at 1500).
4. **Extract features** per blunder: which piece, was it a capture, did it leave pieces hanging, did it expose the king, game phase, time class, time spent.
5. **Cluster** the blunders with HDBSCAN to find recurring patterns.
6. **Summarize** each pattern in plain language (LLM-polished if Ollama is running).

The output is a few sentences telling you what you actually do wrong.

## Architecture

```
cli.py
  └── ingest.py              ← Chess.com primary, Lichess fallback
        └── chesscom_client  ← retry, rate limits, type-safe responses
        └── stockfish_pool   ← persistent engine, no per-move spawn
        └── db               ← SQLite schema + connection helpers
  └── blunders.py            ← rating-scaled threshold detection
        └── features.py      ← per-move feature engineering
  └── patterns.py            ← HDBSCAN clustering of feature vectors
  └── llm_summary.py         ← Ollama-backed naming + final paragraph
```

Every module has a single responsibility, no circular imports, and all configuration flows from `config.py` (env-var based, with sensible defaults).

## Configuration

All knobs are environment variables (see `config.py`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `CHESS_PSYCH_DB` | `~/.chess_psych/data.db` | SQLite path |
| `STOCKFISH_PATH` | auto-detected | engine binary |
| `STOCKFISH_DEPTH` | `12` | search depth per position |
| `CHESSCOM_USER_AGENT` | `ChessPsych/0.1 ...` | required by Chess.com API |
| `CHESSCOM_TIMEOUT` | `30` | per-request timeout |
| `CHESSCOM_RETRY_MAX` | `4` | retry attempts on 5xx |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/generate` | LLM endpoint |
| `OLLAMA_MODEL` | `llama3` | LLM model name |
| `BLUNDER_MIN_PLY` | `6` | skip opening blunders below this ply |
| `CLUSTER_MIN_SIZE` | `3` | HDBSCAN min cluster size |
| `LOG_LEVEL` | `INFO` | python logging level |

## Running with Docker

```bash
docker build -t chess-psych .
docker run --rm -v $PWD/data:/data chess-psych analyze YourChessComName --max-games 50
```

The `/data` volume keeps the SQLite database between runs.

## Testing

```bash
pytest tests/ -v        # 40 unit tests, no network, no engine
python smoke_test.py    # end-to-end with synthetic PGNs + Stockfish
```

The unit tests cover pure functions (feature extraction, blunder thresholds, PGN comment parsing, clustering vectorization) and the Chess.com client (retry logic, rate-limit handling, time-class filtering) using a stubbed `requests.Session`. The smoke test runs the full pipeline against three synthetic games.

## Design notes

- **Persistent Stockfish.** The engine is opened once via a context manager (`StockfishPool`) and reused for the whole ingestion. The naive approach of `popen_uci` per move costs 200–500 ms of overhead each time; with ~80 moves per game and 50 games, that's the difference between a 30-second run and a 15-minute one.

- **Inline evals first, Stockfish as fallback.** Lichess PGNs include `[%eval ...]` comments on most moves. Chess.com generally does not. The ingestor uses the inline value when present and only spins up Stockfish when needed — significant time saved on Lichess data.

- **Rating-calibrated thresholds.** "Blunder" means something different at every level. A 1200 player's 200cp drop is a normal Tuesday; a 2100 player's is an emergency. The threshold table in `blunders.py` reflects this.

- **HDBSCAN over k-means.** k-means forces every point into a cluster and assumes spherical clusters of similar size. Blunder patterns aren't shaped like that. HDBSCAN finds density-based clusters of variable shape and labels outliers as `-1` instead of forcing them somewhere they don't belong.

- **Time class as a first-class feature.** Bullet, Blitz, Rapid, and Daily produce different blunder profiles for the same player. Surfacing this through Chess.com's `time_class` field (rather than guessing from time controls) keeps clusters meaningful.

- **Idempotent re-runs.** Re-ingesting the same games is a no-op (deduplicated by `external_id`). Re-running blunder detection wipes prior blunders for that user first. Re-running clustering wipes prior patterns. You can re-run any step without corrupting state.

- **LLM-optional.** If Ollama isn't running, the system falls back to mechanical pattern descriptions. The product still works; it's just less polished.

## Roadmap

- [ ] Web UI replacing the Streamlit prototype with FastAPI + React
- [ ] Real-time in-game pattern matching (warn before you blunder again)
- [ ] Position similarity search ("this looks like your loss against X last Tuesday")
- [ ] Shareable persona cards
- [ ] Boss mode: the engine plays into your weaknesses on purpose
