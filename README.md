# Chess Psych

A personal blunder-pattern coach for Chess.com players.

Most chess training tools give you stats. Chess Psych finds the recurring shapes of your mistakes, clusters them into patterns, and explains them in plain language.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the full pipeline against your Chess.com username
PYTHONPATH=src python -m chess_psych.cli analyze YourChessComName --max-games 50

# 3. Just blitz games
PYTHONPATH=src python -m chess_psych.cli analyze YourChessComName --time-class blitz --max-games 50

# 4. See what was found
PYTHONPATH=src python -m chess_psych.cli stats YourChessComName
```

On Windows PowerShell, set the package path first:

```powershell
$env:PYTHONPATH = "src"
python -m chess_psych.cli analyze YourChessComName --max-games 50
```

Optional: run a local Ollama server with `llama3` to get LLM-polished pattern names and a personalized profile paragraph. The system works without it and falls back to mechanical descriptions.

## What It Does

1. Ingests recent games from the Chess.com public API.
2. Evaluates each position with Stockfish, or uses inline PGN evals when present.
3. Detects blunders with a rating-calibrated threshold.
4. Extracts features per blunder: piece, capture/check, hanging pieces, king exposure, phase, time class, and time spent.
5. Clusters blunders with HDBSCAN to find recurring patterns.
6. Summarizes each pattern in plain language.

## UI Demo

For the polished 90-second product demo, open this file directly in a browser:

```text
demos/ui_demo.html
```

That is the main show file. It is a static, offline UI built from the verified Tal/Carlsen engine probe data, so it does not need Streamlit, Stockfish, or a dev server during the presentation.

To refresh the underlying cross-era data when your machine has enough memory for Stockfish:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1 -CrossEraDemo
```

## Live Coaching Demo

Once you have analyzed a user, launch the Streamlit app:

```bash
streamlit run apps/live_coach_app.py
```

In the sidebar, enter the username you analyzed. The coach loads that player's recurring patterns, watches every move, and flags live moves that resemble known weaknesses.

For a deterministic presentation UI:

```bash
streamlit run apps/presentation_demo.py
```

## Demo Data Builders

The UI demo uses the Tal/Carlsen cross-era artifact:

```bash
python tests/test_cross_era_genius_demo.py
```

That writes:

- `demos/generated/cross_era_genius_demo.html`
- `demos/generated/cross_era_genius_demo.json`

## Repository Layout

```text
src/chess_psych/              Python package
  cli.py                      CLI entry point
  ingest.py                   Chess.com primary, Lichess fallback
  chesscom_client.py          Chess.com API wrapper
  stockfish_pool.py           Persistent Stockfish engine wrapper
  db.py                       SQLite schema and helpers
  blunders.py                 Rating-scaled blunder detection
  features.py                 Per-move feature engineering
  patterns.py                 HDBSCAN clustering
  llm_summary.py              Ollama-backed naming and summaries
  live_coach.py               Real-time pattern matching

apps/                         Streamlit apps
scripts/                      Local utility and smoke-test scripts
tests/                        Unit tests and opt-in demo data builders
demos/ui_demo.html            Main static UI demo
demos/generated/              Generated demo source data
web_components/               Streamlit chessboard component
vendor/                       Stockfish source and binaries
models/                       Local LLM model files
data/                         Local SQLite data, ignored by git
```

## Configuration

All knobs are environment variables, loaded in `src/chess_psych/config.py`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CHESS_PSYCH_DB` | `~/.chess_psych/data.db` | SQLite path |
| `STOCKFISH_PATH` | auto-detected | Engine binary |
| `STOCKFISH_DEPTH` | `12` | Search depth per position |
| `STOCKFISH_THREADS` | `1` | Engine threads |
| `STOCKFISH_HASH_MB` | `16` | Engine hash size |
| `CHESSCOM_USER_AGENT` | `ChessPsych/0.1 ...` | Chess.com API user agent |
| `CHESSCOM_TIMEOUT` | `30` | Per-request timeout |
| `CHESSCOM_RETRY_MAX` | `4` | Retry attempts |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/generate` | LLM endpoint |
| `OLLAMA_MODEL` | `llama3` | LLM model name |
| `BLUNDER_MIN_PLY` | `6` | Skip opening blunders below this ply |
| `CLUSTER_MIN_SIZE` | `3` | HDBSCAN minimum cluster size |
| `LOG_LEVEL` | `INFO` | Python logging level |

## Docker

```bash
docker build -t chess-psych .
docker run --rm -v $PWD/data:/data chess-psych analyze YourChessComName --max-games 50
```

The `/data` volume keeps the SQLite database between runs.

## Testing

```bash
PYTHONPATH=src pytest tests/ -v
python scripts/smoke_test.py
```

The unit tests cover pure functions and the Chess.com client using stubbed requests. The smoke test runs the full synthetic PGN pipeline with Stockfish.

## Design Notes

- Persistent Stockfish avoids per-move engine startup cost.
- Inline evals are used first when PGNs include them.
- Blunder thresholds scale by rating.
- HDBSCAN avoids forcing every blunder into a pattern.
- Time class is preserved as a first-class feature.
- Re-ingestion and reclustering are idempotent.
- LLM summaries are optional.
