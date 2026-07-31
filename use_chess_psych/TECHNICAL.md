# Technical Use

## Quick Reproduction

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python scripts\build_personal_pattern_demo.py ChessComUsername `
  --max-games 120 --allowed-time-controls 180,300 `
  --threads 1 --hash-mb 16 --skip-ai-labels `
  --output demos\my_results\chesscomusername_blitz_evidence.json
python scripts\build_personal_report.py `
  demos\my_results\chesscomusername_blitz_evidence.json `
  --output demos\my_results\chesscomusername_report.html
```

## What The Pipeline Does

1. Downloads public rated Chess.com games and retains exact `180` or `300` second blitz controls.
2. Screens positions with Stockfish, then confirms the rating-relative errors at a stronger depth.
3. Splits the error sequence chronologically. Earlier errors train HDBSCAN; later errors are never used to fit the cluster.
4. HDBSCAN groups non-leaky board and clock features. It can leave examples as noise instead of forcing every error into a pattern.
5. A deterministic chess-rule label checks later cluster assignments. The report shows selected-cluster precision as `rule agreements / later assignments`.

## Read The Evidence

Each evidence JSON records the game URL, FEN before and after the move, Stockfish evaluation drop, move clocks, cluster distance, features, cluster support, and chronological validation output.

Do not call selected-cluster precision overall model accuracy. HDBSCAN is an unsupervised grouping method; the report measures whether a chosen cluster's later assignments agree with an independent chess rule. Low support and small holdouts should remain visible in any presentation.

## Local AI Wording

The prepared demo can use local Ollama through `qwen2.5:7b-instruct`. It only drafts short wording. The shown label is assembled from majority evidence and is withheld if the draft contradicts measured phase, clock, or rule facts.
