# Chess Psych Web

This is the no-server browser version of Chess Psych. It fetches public
Chess.com games, runs Stockfish 18 Lite in a browser Web Worker, and saves the
evidence only in the visitor's browser.

## Run Locally

```powershell
cd web
npm install
npm run dev
```

Open the local URL printed by Vite. Choose **Quick 12** to check that the
engine can find confirmed errors, or **Full 40** for a personal-pattern test.
A quick scan never produces a coaching claim. The engine and its GPLv3 license
are copied into the build at build time; `public/engine/` is generated and
intentionally untracked.

## Deploy To Cloudflare Pages

1. Push this repository to GitHub.
2. In Cloudflare, open **Workers & Pages**, then **Create application**,
   **Pages**, and connect the repository.
3. Set **Root directory** to `web`.
4. Set **Build command** to `npm run build`.
5. Set **Build output directory** to `dist`.
6. Deploy. Do not add Pages Functions, a database, API keys, or a payment
   method for this version.

The static build includes the browser worker, WebAssembly engine, and GPLv3
license. It does not upload game data or keep a user profile on a server.

## Boundaries

- The first run downloads about 7 MB for Stockfish and uses the visitor's CPU.
- Public Chess.com profile data is fetched directly in the browser. A PGN
  upload is available as a fallback.
- Stockfish first screens moves cheaply, then re-checks possible errors more
  deeply. A personal claim is based on a concrete chess mechanism plus a
  context discovered in older games (phase and moved piece) and checked against
  the newest quarter of the sample. It also compares the error rate with all
  matching player moves, not only the errors.
- This browser version does not claim to run HDBSCAN. HDBSCAN remains an
  exploratory tool in the Python project; the browser report uses interpretable
  mechanisms and chronological validation for player-facing results.
