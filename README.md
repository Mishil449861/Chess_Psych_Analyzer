# Chess Psych

A personal blunder-pattern coach for Chess.com players.

Most chess training tools give you stats. Chess Psych finds repeatable, Stockfish-confirmed mistake triggers in your own games and explains them in plain language.

## Before You Run

You need:

- Python `3.11+` from [python.org](https://www.python.org/downloads/), with **Add Python to PATH** enabled during installation.
- Stockfish for your operating system. It performs the chess evaluation; see [Stockfish setup](use_chess_psych/INSTALL_STOCKFISH.md).
- An internet connection for public Chess.com games.
- Around 2 GB of free disk space and a laptop/desktop that can keep running while Stockfish analyzes games. A 120-game deep run is deliberately slower than a casual game review.

You do **not** need an OpenAI key, a paid Chess.com account, Ollama, Qwen, Docker, or a GPU. Ollama is optional wording assistance only; it never decides whether a cluster is valid.

## Easiest Windows Route

1. On GitHub, click `Code`, then `Download ZIP`.
2. Extract the ZIP and open the `use_chess_psych` folder.
3. Double-click `RUN_MY_ANALYSIS.bat`.
4. Enter a public Chess.com username and choose Blitz, Bullet, Rapid, or a custom exact control. Blitz uses a focused 3/5-minute preset; the other two use the player's recent rated games in that format. The guided run defaults to 120 games, performs deeper local Stockfish checks, runs HDBSCAN on the older confirmed errors, and opens a private interactive report.

Your personal result is written to `demos/my_results/` and is ignored by Git.

The guided run refreshes public games, screens with Stockfish at depth 8,
confirms candidates at depth 14, and opens a local HTML report. The report is
private to the computer running it. Its HDBSCAN explorer includes both clusters
and noise; a visible cluster is not automatically a coaching claim.

## Command Line Route

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

Optional: run local Ollama with `qwen2.5:7b-instruct` (or another compatible local model) to draft pattern wording. The clustering and evidence checks work without it and fall back to mechanical descriptions.

## Troubleshooting

- **`Stockfish is required` or engine will not start:** confirm `STOCKFISH_PATH` points to the actual `.exe`, then reopen PowerShell. Use the official setup guide above.
- **`No blitz games found with controls 180,300`:** choose Bullet, Rapid, or Custom in the launcher. A player may simply not have public 3/5-minute games.
- **The first run stops during installation:** run `RUN_MY_ANALYSIS.bat` again after confirming Python and internet access. The launcher safely resumes the local setup.
- **Analysis takes a long time:** this is expected for local engine analysis. Keep the window open; completed games are checkpointed under `demos/generated/`, and a rerun resumes compatible work.
- **No cluster or no coaching claim:** that is a valid result. The model is designed to leave ambiguous errors as noise and withhold unsupported advice.

## What It Does

1. Ingests recent games from the Chess.com public API.
2. Evaluates each position with Stockfish, or uses inline PGN evals when present.
3. Detects blunders with a rating-calibrated threshold.
4. Extracts features per blunder: piece, capture/check, hanging pieces, king exposure, phase, time class, time spent, clock remaining, and clock context.
5. Uses HDBSCAN to explore similar board and clock contexts without forcing every error into a group.
6. Shows a coaching trigger only when the exact engine-checked cause and a concrete context recur in a later chronological holdout.

## Use It Yourself

The [use_chess_psych](use_chess_psych) folder is the handoff point for people using the repository from GitHub:

- `RUN_MY_ANALYSIS.bat`: double-click route for a Windows user who only knows a public Chess.com username.
- `START_HERE.md`: plain-English walkthrough.
- `TECHNICAL.md`: reproducible command line, data-science method, and result boundaries.

The app uses public Chess.com games only. Personal reports, downloaded games, and presentation assets stay local under `demos/` and are excluded from Git.

## Live Coaching Demo

Once you have analyzed a user, launch the Streamlit app:

```bash
streamlit run apps/live_coach_app.py
```

In the sidebar, enter the username you analyzed. The coach loads that player's recurring patterns, watches every move, and flags live moves that resemble known weaknesses.

## Data And Validation

The pipeline uses Stockfish to flag rating-relative errors, HDBSCAN to explore non-leaky board and clock contexts, and a chronological holdout for later-game checks. HDBSCAN never creates the coaching claim. A player-facing trigger needs a concrete chess cause, a repeated board/clock situation in both time periods, and enough earlier and later examples to support it. Broad labels such as "pawn moves" are withheld. Local Ollama may draft wording, but deterministic evidence gates control which labels are shown.

## Browser App

The `web/` app is a lightweight public, no-server preview. It runs Stockfish
WebAssembly on the visitor's device and keeps results in their browser. For the
real HDBSCAN model, chronological validation, and interactive cluster explorer,
use `RUN_MY_ANALYSIS.bat` / `RUN_MY_ANALYSIS.ps1`. For web preview use and
Cloudflare Pages deployment, see [web/README.md](web/README.md).

## What Is Public

The GitHub repository contains the reusable analyzer and user-facing routes.
Private reports, downloaded games, local presentation material, historical
comparison demos, and exploratory experiment outputs stay ignored on the local
computer. This keeps the repository lightweight and prevents a demo profile
from becoming part of the public product.

## Repository Layout

```text
src/chess_psych/              Python package
  __init__.py                 Package metadata
  cli.py                      Command-line analysis and reporting entry point
  chesscom_client.py          Rate-aware Chess.com Public Data API client
  ingest.py                   PGN ingestion and database population
  stockfish_pool.py           Bounded, reusable local Stockfish process
  blunders.py                 Rating-calibrated engine error detection
  features.py                 Chess and clock feature engineering primitives
  patterns.py                 Database-oriented HDBSCAN pattern clustering
  personal_validation.py      Chronological validation and adaptive risk analysis
  ollama_labels.py            Optional local-LLM wording, bounded by evidence
  llm_summary.py              Optional Ollama summary helper
  live_coach.py               Matches live decisions to saved player patterns
  coaching_experiments.py     Shared research utilities for taxonomy experiments
  config.py                   Environment-variable configuration
  db.py                       SQLite schema and persistence helpers

apps/
  live_coach_app.py           Streamlit interface for an analyzed player

scripts/
  build_personal_pattern_demo.py  Main public-game to validated-evidence pipeline
  build_personal_report.py        Builds the private, file-based HTML report
  smoke_test.py                   End-to-end synthetic pipeline check
  test_local.ps1                 Local verification helper

use_chess_psych/
  RUN_MY_ANALYSIS.bat         Double-click Windows launcher
  RUN_MY_ANALYSIS.ps1         Guided PowerShell launcher and dependency setup
  START_HERE.md               Plain-language setup and usage guide
  INSTALL_STOCKFISH.md        Stockfish installation instructions
  TECHNICAL.md                Method, validation, and result boundaries

web/
  index.html                  Browser-preview entry page
  package.json                Browser preview package and npm commands
  package-lock.json           Locked browser-preview dependencies
  src/analysis.js             In-browser feature and advice logic
  src/engine.js               Stockfish WebAssembly integration
  src/main.js                 Browser-app interaction flow
  src/style.css               Browser-app styling
  scripts/copy-engine.mjs     Copies the local engine asset for development
  scripts/test-analysis.mjs   Browser-analysis contract test
  README.md                   Browser preview and deployment instructions

web_components/
  chessboard/index.html       Reusable interactive chessboard for Streamlit
  custom_chess/index.html     Custom board component used by the live coach

tests/
  test_pure.py                Deterministic feature and validation unit tests
  test_chesscom_client.py     Stubbed Chess.com client tests
  test_personal_report.py     HTML report contract tests

vendor/stockfish/             Stockfish source for reproducible local builds
Dockerfile                    Container build definition
Makefile                      Shortcuts for install, test, smoke, app, and Docker
requirements.txt              Python runtime and test dependencies
python-version.txt            Recommended Python version marker
.gitignore                    Keeps local reports, data, demos, and caches private
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
- Time class, clock remaining, and increment-aware time spent are preserved as first-class features.
- Re-ingestion and reclustering are idempotent.
- LLM summaries are optional.
