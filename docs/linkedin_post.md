# LinkedIn Post Draft

## Screenshot Order

1. **Stockfish panel:** the fixed `Rbc1 = -2.33 pawns` reference move.
2. **MishilT panel:** `Middlegame rook moves with time available` and `11` / `9/12` evidence cards.
3. **Player X or Hikaru panel:** same board, changed ML cluster result and coaching habit.

## Post Copy

**Stockfish told me a move was bad. It did not tell me what to practice because of it.**

That was the problem I wanted to solve.

I can review a chess game and get a long list of engine mistakes. But I cannot realistically calculate every move like a grandmaster, and a list of best moves does not reveal whether I keep making the *same kind* of error.

So I built **Chess Psych**.

It takes public Chess.com games, uses Stockfish to find rating-relative errors, then uses HDBSCAN clustering to group repeated board and clock contexts.

The key idea is simple:

- The Stockfish verdict stays fixed: `Rbc1` loses 2.33 pawns.
- The coaching changes with the player's history.
- One player shows repeated rook moves with time available.
- Another shows king-move errors.
- A stronger reference player shows quick queen moves.

This is not trying to beat Stockfish at chess calculation. Stockfish finds the error. Chess Psych turns many errors into one evidence-backed practice habit.

I validate each selected cluster on later games that were not used to train it. That is why I show bounded results such as `9/12` or `6/8`, rather than claiming one inflated overall accuracy number.

**Try it on your own public Chess.com account:**

1. Clone the GitHub repository: `<YOUR_GITHUB_REPOSITORY_URL>`
2. Open `use_chess_psych`.
3. Double-click `RUN_MY_ANALYSIS.bat` on Windows.
4. Enter a public Chess.com username.

The first run sets up Python dependencies, analyzes exact three- and five-minute blitz games locally, and opens a personal report. Your downloaded games and report remain local and are not committed to Git.

The technical stack: Python, Chess.com public PGNs, Stockfish, `python-chess`, NumPy, scikit-learn/HDBSCAN, SQLite, and local Ollama/Qwen for constrained wording.

I would love feedback from chess players, coaches, and anyone building practical ML products from behavioral data.

`#Chess #MachineLearning #DataScience #Python #Stockfish #OpenSource`
