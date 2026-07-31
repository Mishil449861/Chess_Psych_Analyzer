# Use Chess Psych

## Get The Project From GitHub

1. Open the repository page on GitHub.
2. Click `Code`, then `Download ZIP`.
3. Extract the ZIP anywhere on your computer.
4. Open the extracted `use_chess_psych` folder.

## No-Tech Route

1. Double-click `RUN_MY_ANALYSIS.bat`.
2. Enter a public Chess.com username when asked.
3. Wait for the analysis to finish. The first run can take a while because Stockfish checks positions.
4. Your browser opens a personal report automatically.

The launcher uses only public Chess.com games, keeps exact three- and five-minute blitz games, and saves your result under `demos/my_results/`.

Requirements: Windows, Python 3.11 or newer, and an internet connection. On a first run, the launcher creates `venv` and installs the dependencies in `requirements.txt`.

## Technical route

Read [TECHNICAL.md](TECHNICAL.md) for reproducible commands, evidence files, and model boundaries.
