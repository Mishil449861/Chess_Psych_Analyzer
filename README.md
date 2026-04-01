# Chess Psych Analyzer

A psychological profiler and chess engine interface built with Streamlit. This application allows you to play chess against the Stockfish engine while a local Large Language Model (Llama 3) analyzes the computer's momentum shifts, tactical decisions, and "emotional" state in real-time to generate behavioral threat profiles.

## Features

* **Interactive Chessboard:** Playable drag-and-drop interface powered by chessboard.js and python-chess.
* **Custom UI:** Features custom CSS for digital chess clocks and dark-themed threat profile cards.
* **Stockfish Integration:** Calculates CPU moves and provides continuous centipawn evaluation.
* **Real-Time Psychological Profiling:** Uses an asynchronous connection to a local LLM to generate two-sentence behavioral profiles based on tactical context (captures, checks), game phase, and evaluation swings.
* **Bypass Windows Background Restrictions:** Implements the `WindowsProactorEventLoopPolicy` to ensure background Python subprocesses execute smoothly on Windows.

## Prerequisites

To run this project locally, you must have the following installed:

1. **Python 3.8+**
2. **Stockfish Engine:** Download the Windows executable.
3. **Local LLM Server:** An API running locally on `http://127.0.0.1:11434` (e.g., Ollama running the `llama3` model).

## Installation

1. Clone the repository:
```bash
git clone [https://github.com/Mishil449861/chess_psych.git](https://github.com/Mishil449861/chess_psych.git)
cd chess_psych
