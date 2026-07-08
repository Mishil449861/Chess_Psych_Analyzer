# 90-Second Demo Script

## Setup

Open this file first:

`demos/generated/cross_era_genius_demo.html`

Have a terminal ready in the repo root.

Optional refresh command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1 -CrossEraDemo
```

Full smoke test, only when your machine has memory headroom:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1 -CrossEraDemo -FullSmoke
```

## Talk Track

**0:00-0:10**

"This is Chess Psych. The point is not to replace Stockfish. The point is to explain chess through the player, not only through the number."

**0:10-0:25**

"First, this is Botvinnik versus Mikhail Tal, a real World Championship game from Moscow 1960. Tal is Black. The critical move is the famous knight sacrifice, 21...Nf4."

**0:25-0:42**

"I tested the position with Stockfish at depths 1 through 14. At every tested depth, the engine says Tal's move makes Black's evaluation worse. The engine-only read says: this looks suspicious."

**0:42-1:00**

"But the historical result tells another story. This sacrifice created a forcing attacking problem that Botvinnik failed to solve over the board, and Tal won the game."

**1:00-1:18**

"Now jump forward more than fifty years to Magnus Carlsen versus Viswanathan Anand, World Championship 2013 Game 3. The move is 28.e3. It gives material, but opens the position and reactivates Carlsen's pieces."

**1:18-1:30**

"That is the cross-era point. Tal shows attacking genius in 1960. Carlsen shows modern resilience in 2013. Chess Psych adds the missing layer: style, initiative, reactivation, and practical pressure. Stockfish sees the board. Chess Psych sees the player."

## What To Emphasize

- This is not a random online game.
- It starts with Botvinnik-Tal, World Championship Match 1960, Game 6.
- It adds Carlsen-Anand, World Championship Match 2013, Game 3.
- Both move scores are validated by `python-chess`.
- Stockfish is probed at multiple depths.
- Tal shows engine-only doubt.
- Carlsen shows that even a modern World Champion's practical resource can look suspicious to engine-only snapshots.
- The product claim is not "ignore engines"; it is "engine numbers need player context."

## Strong One-Liner

"Stockfish sees the board. Chess Psych sees the player."

## Technical Credibility Notes

- The project has a real engine-backed pipeline.
- Stockfish is run as a persistent process.
- The game score is parsed and verified legally.
- The exact pre-sacrifice FEN is generated from the move score, not typed by hand.
- The demo records all engine probes in JSON.
- The product layer extracts move features and attaches higher-level player-pattern tags.
- The HTML is reproducible from `tests/test_cross_era_genius_demo.py`.
