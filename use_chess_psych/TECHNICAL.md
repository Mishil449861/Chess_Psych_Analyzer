# Technical Use

## Quick Reproduction

Prerequisites: Python 3.11+, Stockfish available through `STOCKFISH_PATH` or `PATH`, and internet access for public Chess.com data. Ollama/Qwen is optional because the personal run uses `--skip-ai-labels`.

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python scripts\build_personal_pattern_demo.py ChessComUsername `
  --max-games 120 --allowed-time-controls 180,300 `
  --screen-depth 8 --confirm-depth 14 --threads 1 --hash-mb 16 --skip-ai-labels `
  --output demos\my_results\chesscomusername_blitz_evidence.json
python scripts\build_personal_report.py `
  demos\my_results\chesscomusername_blitz_evidence.json `
  --output demos\my_results\chesscomusername_report.html
```

## What The Pipeline Does

1. Downloads public rated Chess.com games. The guided Blitz preset retains exact `180` or `300` second games; Bullet and Rapid can retain all controls in their selected format.
2. Screens positions with Stockfish, then confirms the rating-relative errors at a stronger depth.
3. Splits the error sequence chronologically. Older games establish evidence; later games are held out for verification.
4. HDBSCAN explores non-leaky board and clock contexts. It can leave examples as noise instead of forcing every error into a pattern, and it never writes player-facing advice.
5. The report exposes every HDBSCAN cluster in an interactive explorer, including noise and weak clusters. It only turns a cluster into coaching advice after a deterministic chess cause and a concrete board/clock trigger recur in later games.

## Label Gate

The report never turns a broad context such as "middlegame pawn moves" into advice. It only publishes a trigger for a concrete engine-checkable cause, such as a missed capture or a newly opened opponent capture, when the cause repeats in both periods and a compact board/clock detail also remains common in the later games. For example, it can say that the moved piece is repeatedly captured while time remains; it cannot merely say "you make pawn mistakes." Otherwise it reports no verified personal trigger yet.

## Read The Evidence

Each evidence JSON records the game URL, FEN before and after the move, Stockfish evaluation drop, move clocks, the engine's best reply, its captured piece where applicable, cluster distance, features, and chronological validation output.

Do not call HDBSCAN precision overall model accuracy. It is an unsupervised grouping method used for exploration. The player-facing report relies on deterministic Stockfish facts plus chronological recurrence; low support and small holdouts should remain visible in any presentation.

## Local AI Wording

The prepared demo can use local Ollama through `qwen2.5:7b-instruct`. It only drafts short wording. The shown label is assembled from majority evidence and is withheld if the draft contradicts measured phase, clock, or rule facts.
