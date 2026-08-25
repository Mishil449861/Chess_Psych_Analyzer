import "./style.css";
import { Chess } from "chess.js";
import {
  analyzeGames,
  boardSquares,
  clusterConfirmedErrors,
  FAST_GAME_LIMIT,
  fetchRecentBlitzGames,
  findObservedFocusAreas,
  findVerifiedTrigger,
  MIN_GAMES_FOR_PERSONAL_CONCLUSION,
  normaliseUsername,
  selectBlitzGames,
} from "./analysis.js";
import { BrowserStockfish } from "./engine.js";

const form = document.querySelector("#analysis-form");
const usernameInput = document.querySelector("#username");
const fileInput = document.querySelector("#pgn-file");
const sampleSize = document.querySelector("#sample-size");
const button = document.querySelector("#analyze-button");
const progress = document.querySelector("#progress");
const progressBar = document.querySelector("#progress-bar");
const progressCopy = document.querySelector("#progress-copy");
const formError = document.querySelector("#form-error");
const report = document.querySelector("#report");
const emptyState = document.querySelector("#empty-state");

function setProgress(copy, value) {
  progress.hidden = false;
  progressCopy.textContent = copy;
  progressBar.style.width = `${Math.max(2, Math.min(value, 100))}%`;
}

function setError(message) {
  formError.hidden = !message;
  formError.textContent = message || "";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
}

function renderBoard(fen) {
  const squares = boardSquares(fen);
  return `<div class="board" aria-label="Chess position">${squares.map((piece, index) => `<span class="square ${(Math.floor(index / 8) + index) % 2 ? "dark" : "light"}">${piece}</span>`).join("")}</div>`;
}

function downloadEvidence(data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `chess-psych-${data.username.toLowerCase()}-evidence.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function renderFocusAreas(focusAreas) {
  if (!focusAreas.length) {
    return `<p class="method-note">The confirmed errors did not contain three examples of the same concrete tactical mechanism. Review the exported evidence instead of following a generic drill.</p>`;
  }
  return `
    <section class="focus-section" aria-labelledby="focus-title">
      <p class="eyebrow">Evidence-backed review</p>
      <h3 id="focus-title">What to practice next</h3>
      <p class="focus-intro">These are repeated engine-confirmed situations in this sample. They are useful practice targets, but not yet claimed as lasting personal habits.</p>
      <div class="focus-list">${focusAreas.map((area) => {
        const sample = area.errors[0];
        return `<article class="focus-card">
          <div class="focus-head"><h4>${escapeHtml(`${area.title}${area.context?.label || ""}`)}</h4><span>${area.errors.length}/${area.moves} moves</span></div>
          <p>${escapeHtml(area.description)}</p>
          <p class="focus-rate"><strong>${(area.errorRate * 100).toFixed(1)}%</strong> in this situation, ${(area.lift).toFixed(1)}x this player's overall confirmed-error rate.</p>
          <p class="focus-cue"><strong>Practice:</strong> ${escapeHtml(area.cue)}</p>
          ${sample?.gameUrl ? `<a class="game-link" href="${escapeHtml(sample.gameUrl)}" target="_blank" rel="noreferrer">Open one real example</a>` : ""}
        </article>`;
      }).join("")}</div>
    </section>`;
}

function renderClusterDetail(cluster) {
  const sample = cluster.sample;
  return `
    <div class="group-detail-copy">
      <p class="eyebrow">Selected cluster</p>
      <h4>${escapeHtml(cluster.title)}</h4>
      <p>${escapeHtml(cluster.description)}</p>
      <p class="cluster-explanation"><strong>Common explanation after clustering:</strong> ${escapeHtml(cluster.explanation)}</p>
      <p class="focus-cue"><strong>Review idea:</strong> ${escapeHtml(cluster.cue)}</p>
      <p class="real-instance"><strong>One example:</strong> <code>${escapeHtml(sample.move)}</code> lost ${sample.evalDropCp} centipawns; Stockfish replied <code>${escapeHtml(sample.reply)}</code>.</p>
      ${sample.gameUrl ? `<a class="game-link" href="${escapeHtml(sample.gameUrl)}" target="_blank" rel="noreferrer">Open real game</a>` : ""}
    </div>
    <div>${renderBoard(sample.fenBefore)}</div>`;
}

function renderClusterMap(clustering) {
  const { clusters, noiseCount, epsilon, minimumPoints } = clustering;
  if (!clusters.length) {
    return `<section class="error-map" aria-labelledby="error-map-title"><p class="eyebrow">Density clustering</p><h3 id="error-map-title">No dense cluster in this sample</h3><p class="focus-intro">${noiseCount} confirmed errors were treated as individual points rather than forced into a misleading group. Add more games or inspect the evidence-backed focus areas above.</p><details class="technical map-method"><summary>Clustering settings</summary><p>DBSCAN used a neighborhood radius of ${epsilon} and a minimum of ${minimumPoints} similar errors. It groups only dense regions and marks the rest as noise.</p></details></section>`;
  }
  const firstCluster = clusters[0];
  return `
    <section class="error-map" id="error-map" aria-labelledby="error-map-title">
      <div class="map-heading">
        <div><p class="eyebrow">Density clustering</p><h3 id="error-map-title">Explore your actual error clusters</h3></div>
        <span class="map-count">${clusters.length} clusters</span>
      </div>
      <p class="focus-intro">The model clustered confirmed errors from board context, moved piece, tactical shape, engine-reply shape, and loss severity. Choose a phase, then open a cluster to inspect it.</p>
      <div class="phase-tabs" role="tablist" aria-label="Filter error clusters by phase">
        <button type="button" class="phase-tab active" data-phase="all" role="tab" aria-selected="true">All</button>
        <button type="button" class="phase-tab" data-phase="opening" role="tab" aria-selected="false">Opening</button>
        <button type="button" class="phase-tab" data-phase="middlegame" role="tab" aria-selected="false">Middlegame</button>
        <button type="button" class="phase-tab" data-phase="endgame" role="tab" aria-selected="false">Endgame</button>
      </div>
      <div class="group-grid">${clusters.map((cluster, index) => `
        <button type="button" class="group-card${index === 0 ? " selected" : ""}" data-cluster-id="${escapeHtml(cluster.id)}" data-phase="${escapeHtml(cluster.phase)}" aria-pressed="${index === 0 ? "true" : "false"}">
          <span class="group-phase">${escapeHtml(cluster.phase)}</span>
          <strong>${escapeHtml(cluster.title)}</strong>
          <span>${cluster.count} similar errors · ${cluster.piece} most often</span>
          <em>Average ${cluster.averageDrop} cp lost</em>
        </button>`).join("")}</div>
      <div class="group-detail" id="group-detail">${renderClusterDetail(firstCluster)}</div>
      <details class="technical map-method"><summary>Clustering settings</summary><p>DBSCAN used a neighborhood radius of ${epsilon} and a minimum of ${minimumPoints} similar errors. ${noiseCount} errors were marked as noise rather than assigned to a cluster. Chess mechanisms are used only after the clustering pass to explain a group, not to create it.</p></details>
    </section>`;
}

function wireClusterMap(clustering) {
  const map = document.querySelector("#error-map");
  if (!map) return;
  const detail = map.querySelector("#group-detail");
  for (const card of map.querySelectorAll(".group-card")) {
    card.addEventListener("click", () => {
      const cluster = clustering.clusters.find((item) => item.id === card.dataset.clusterId);
      if (!cluster) return;
      for (const item of map.querySelectorAll(".group-card")) {
        const selected = item === card;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-pressed", String(selected));
      }
      detail.innerHTML = renderClusterDetail(cluster);
    });
  }
  for (const tab of map.querySelectorAll(".phase-tab")) {
    tab.addEventListener("click", () => {
      const phase = tab.dataset.phase;
      for (const item of map.querySelectorAll(".phase-tab")) {
        const selected = item === tab;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-selected", String(selected));
      }
      for (const card of map.querySelectorAll(".group-card")) {
        card.hidden = phase !== "all" && card.dataset.phase !== phase;
      }
    });
  }
}

function renderReport(result) {
  const { games, observations, opportunities, screenedPositions, screenCandidates, trigger, analysisLevel } = result;
  const focusAreas = result.focusAreas || findObservedFocusAreas(observations, opportunities);
  const clustering = result.clustering || clusterConfirmedErrors(observations);
  const quality = `
    <div class="quality-grid" aria-label="Analysis quality">
      <div><strong>${screenedPositions}</strong><span>moves screened</span></div>
      <div><strong>${screenCandidates}</strong><span>deep checks</span></div>
      <div><strong>${observations.length}</strong><span>confirmed errors</span></div>
    </div>`;
  if (analysisLevel === "quick") {
    report.innerHTML = `
      <article class="result-panel abstain">
        <p class="eyebrow">Quick scan complete</p>
        <h2>Useful signal, not a personal verdict yet</h2>
        <p>${observations.length} moves passed the deeper Stockfish check across ${games.length} games. A 12-game scan is intentionally too small to label a lasting personal habit.</p>
        ${quality}
        ${renderFocusAreas(focusAreas)}
        ${renderClusterMap(clustering)}
        <p class="method-note">Choose <strong>Full 40</strong> to test a candidate on newer games that were not used to discover it.</p>
        <button class="icon-command" id="export-evidence" type="button">Export evidence</button>
      </article>`;
  } else if (!trigger) {
    report.innerHTML = `
      <article class="result-panel abstain">
        <p class="eyebrow">Full analysis complete</p>
        <h2>No stable personal trigger in this sample</h2>
        <p>${observations.length} moves passed the deeper Stockfish check across ${games.length} games, but no mechanism and board context repeated strongly enough in newer games. The errors are real; one broad practice rule would not be well-supported.</p>
        ${quality}
        ${renderFocusAreas(focusAreas)}
        ${renderClusterMap(clustering)}
        <details class="technical"><summary>What was tested</summary><p>Older games discover concrete error mechanisms and contexts such as phase or moved piece. The newest quarter of games is held back. A claim needs at least four older errors, two newer errors, enough matching moves in both periods, and a higher-than-baseline earlier error rate.</p></details>
        <button class="icon-command" id="export-evidence" type="button">Export evidence</button>
      </article>`;
  } else {
    const sample = trigger.later[0] || trigger.earlier[0];
    report.innerHTML = `
      <article class="result-panel">
        <div class="result-topline"><p class="eyebrow">Verified personal trigger</p><span class="verified">Later-game checked</span></div>
        <h2>${escapeHtml(`${trigger.title}${trigger.context?.label || ""}`)}</h2>
        <p class="result-description">${escapeHtml(trigger.description)}</p>
        <div class="evidence-grid">
          <div><strong>${trigger.earlier.length}/${trigger.earlierMoves}</strong><span>older matching moves</span></div>
          <div><strong>${trigger.later.length}/${trigger.laterMoves}</strong><span>newer matching moves</span></div>
          <div><strong>${games.length}</strong><span>public blitz games</span></div>
        </div>
        <div class="result-layout">
          <div>${renderBoard(sample.fenBefore)}</div>
          <div class="insight-copy">
            <p class="cue"><strong>Your blitz check:</strong> ${escapeHtml(trigger.cue)}</p>
            <p class="real-instance"><strong>Real instance:</strong> after <code>${escapeHtml(sample.move)}</code>, Stockfish chose <code>${escapeHtml(sample.reply)}</code>.</p>
            <details class="technical" open>
              <summary>Why this is personal</summary>
              <ul>${trigger.tests.map((test) => `<li>${escapeHtml(test)}</li>`).join("")}</ul>
              <p>Older games: ${(trigger.earlierRate * 100).toFixed(1)}% error rate in this context, ${(trigger.earlierLift).toFixed(1)}x the player's overall error rate. Newer games: ${(trigger.laterRate * 100).toFixed(1)}%.</p>
              <p>Real instance: ${sample.evalDropCp} centipawns lost after <code>${escapeHtml(sample.move)}</code>; Stockfish chose <code>${escapeHtml(sample.reply)}</code>.</p>
            </details>
            ${sample.gameUrl ? `<a class="game-link" href="${escapeHtml(sample.gameUrl)}" target="_blank" rel="noreferrer">Open real game</a>` : ""}
          </div>
        </div>
        ${quality}
        ${renderClusterMap(clustering)}
        <button class="icon-command" id="export-evidence" type="button">Export evidence</button>
      </article>`;
  }
  report.hidden = false;
  emptyState.hidden = true;
  document.querySelector("#export-evidence").addEventListener("click", () => downloadEvidence(result));
  wireClusterMap(clustering);
}

function pgnGames(text, username) {
  const chunks = text.split(/(?=\[Event\s)/).filter((chunk) => chunk.trim());
  return chunks.map((pgn) => {
    const game = new Chess();
    game.loadPgn(pgn);
    const headers = game.getHeaders();
    return {
      pgn,
      white: { username: headers.White || "", rating: Number(headers.WhiteElo) || null },
      black: { username: headers.Black || "", rating: Number(headers.BlackElo) || null },
      end_time: Number(headers.Date?.replaceAll(".", "")) || 0,
      time_class: "blitz",
      time_control: headers.TimeControl || "",
      rated: true,
      rules: "chess",
      url: headers.Site || "",
    };
  }).filter((game) => [game.white.username, game.black.username].map(normaliseUsername).includes(normaliseUsername(username)));
}

async function runAnalysis(username, suppliedGames = null) {
  setError("");
  report.hidden = true;
  button.disabled = true;
  button.textContent = "Analyzing…";
  let engine;
  try {
    setProgress("Getting public games", 5);
    const requestedGames = Number(sampleSize.value) || FAST_GAME_LIMIT;
    const games = suppliedGames || await fetchRecentBlitzGames(username, requestedGames, setProgress);
    if (games.length < 4) throw new Error("Not enough matching 3- or 5-minute blitz games were found. Try a PGN file or play more games in that format.");
    setProgress("Starting Stockfish on this device", 23);
    engine = new BrowserStockfish(new URL("engine/stockfish-18-lite-single.js", window.location.href));
    await engine.start();
    const analysis = await analyzeGames(games, username, engine, setProgress);
    const analysisLevel = games.length >= MIN_GAMES_FOR_PERSONAL_CONCLUSION ? "full" : "quick";
    const trigger = analysisLevel === "full"
      ? findVerifiedTrigger(analysis.observations, analysis.opportunities, games.length)
      : null;
    const result = {
      schemaVersion: 2,
      username,
      games,
      ...analysis,
      focusAreas: findObservedFocusAreas(analysis.observations, analysis.opportunities),
      clustering: clusterConfirmedErrors(analysis.observations),
      analysisLevel,
      trigger,
      createdAt: new Date().toISOString(),
    };
    localStorage.setItem("chessPsych.lastEvidence", JSON.stringify(result));
    setProgress("Report ready", 100);
    renderReport(result);
  } catch (error) {
    setError(error instanceof Error ? error.message : "Analysis could not finish.");
  } finally {
    engine?.stop();
    button.disabled = false;
    button.textContent = "Analyze";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runAnalysis(usernameInput.value.trim());
});

fileInput.addEventListener("change", async () => {
  const [file] = fileInput.files;
  if (!file) return;
  const username = usernameInput.value.trim();
  if (!username) {
    setError("Enter the username used in this PGN first.");
    fileInput.value = "";
    return;
  }
  try {
    const games = pgnGames(await file.text(), username);
    if (!games.length) throw new Error("The PGN did not contain games for that username.");
    const requestedGames = Number(sampleSize.value) || FAST_GAME_LIMIT;
    runAnalysis(username, games.slice(-requestedGames));
  } catch (error) {
    setError(error instanceof Error ? error.message : "That PGN could not be read.");
  }
});

try {
  const saved = JSON.parse(localStorage.getItem("chessPsych.lastEvidence"));
  if (saved?.schemaVersion === 2 && saved?.username && saved?.observations) renderReport(saved);
  else localStorage.removeItem("chessPsych.lastEvidence");
} catch {
  localStorage.removeItem("chessPsych.lastEvidence");
}
