export class BrowserStockfish {
  constructor(engineUrl) {
    this.engineUrl = engineUrl;
    this.worker = null;
    this.waiters = [];
    this.activeSearch = null;
  }

  async start() {
    this.worker = new Worker(this.engineUrl);
    this.worker.addEventListener("message", (event) => this.#onLine(String(event.data)));
    this.worker.addEventListener("error", () => this.#fail("The local chess engine could not start."));
    this.worker.postMessage("uci");
    await this.#waitFor(/^uciok$/);
    this.worker.postMessage("setoption name Threads value 1");
    this.worker.postMessage("setoption name Hash value 8");
    this.worker.postMessage("isready");
    await this.#waitFor(/^readyok$/);
  }

  analyze(fen, depth) {
    if (this.activeSearch) throw new Error("The engine received overlapping searches.");
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => this.#fail("The local engine took too long. Try the PGN route or a faster device."), 25000);
      this.activeSearch = { resolve, reject, scoreCp: 0, timeout };
      this.worker.postMessage(`position fen ${fen}`);
      this.worker.postMessage(`go depth ${depth}`);
    });
  }

  stop() {
    this.worker?.terminate();
    this.worker = null;
    this.activeSearch = null;
  }

  #waitFor(pattern) {
    return new Promise((resolve) => this.waiters.push({ pattern, resolve }));
  }

  #onLine(line) {
    for (const waiter of this.waiters.slice()) {
      if (waiter.pattern.test(line)) {
        this.waiters.splice(this.waiters.indexOf(waiter), 1);
        waiter.resolve(line);
      }
    }
    if (!this.activeSearch) return;
    const score = line.match(/\bscore\s+(cp|mate)\s+(-?\d+)/);
    if (score) {
      this.activeSearch.scoreCp = score[1] === "mate"
        ? Math.sign(Number(score[2]) || 1) * 100000
        : Number(score[2]);
    }
    const bestMove = line.match(/^bestmove\s+(\S+)/);
    if (bestMove) {
      const search = this.activeSearch;
      this.activeSearch = null;
      window.clearTimeout(search.timeout);
      search.resolve({ bestMove: bestMove[1], scoreCp: search.scoreCp });
    }
  }

  #fail(message) {
    if (this.activeSearch) {
      const search = this.activeSearch;
      this.activeSearch = null;
      window.clearTimeout(search.timeout);
      search.reject(new Error(message));
    }
  }
}
