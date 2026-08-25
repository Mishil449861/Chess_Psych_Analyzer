# Use Chess Psych

## Get The Project From GitHub

1. Open the repository page on GitHub.
2. Click `Code`, then `Download ZIP`.
3. Extract the ZIP anywhere on your computer.
4. Open the extracted `use_chess_psych` folder.

## No-Tech Route

1. Double-click `RUN_MY_ANALYSIS.bat`.
2. Enter a public Chess.com username when asked.
3. Choose Blitz (recommended), Bullet, Rapid, or a custom exact time control.
4. Wait for the analysis to finish. The first run can take a while because Stockfish checks positions.
5. Your browser opens a personal report automatically.

The recommended option keeps exact three- and five-minute blitz games. Bullet and Rapid use the player's recent rated games in that format; the custom option keeps one exact control. Results are saved under `demos/my_results/`.

## Requirements

- **Windows** and an internet connection.
- **Python 3.11 or newer.** The launcher creates `venv` and installs Python dependencies on its first run.
- **Stockfish.** It is required to identify chess errors and is not downloaded automatically. Follow [INSTALL_STOCKFISH.md](INSTALL_STOCKFISH.md) once.
- **No local AI model is required.** Ollama/Qwen is optional; the guided personal report uses deterministic labels and works without it.

## Technical route

Read [TECHNICAL.md](TECHNICAL.md) for reproducible commands, evidence files, and model boundaries.
