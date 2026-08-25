# Install Stockfish

Chess Psych needs the free Stockfish chess engine to evaluate positions. You only need to install it once. A local AI model is **not** required.

## Windows Setup

1. Download the Windows version from the official [Stockfish download page](https://stockfishchess.org/download/).
2. Extract the downloaded ZIP to a simple location, for example `C:\Stockfish`.
3. Find the extracted file ending in `.exe`, for example `stockfish-windows-x86-64-avx2.exe`.
4. Open PowerShell and run this once, replacing the example path with your actual file path:

```powershell
[Environment]::SetEnvironmentVariable(
  "STOCKFISH_PATH",
  "C:\Stockfish\stockfish-windows-x86-64-avx2.exe",
  "User"
)
```

5. Close PowerShell, open it again, and double-click `RUN_MY_ANALYSIS.bat`.

## Check It Worked

Open a new PowerShell window and run:

```powershell
$env:STOCKFISH_PATH
```

You should see the full path to the Stockfish `.exe` file.
