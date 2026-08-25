import { Chess } from "chess.js";

const PIECE_GLYPHS = {
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
  P: "♙", N: "♘", B: "♗", R: "♖", Q: "♕", K: "♔",
};

export const FAST_GAME_LIMIT = 12;
export const FULL_GAME_LIMIT = 40;
export const SCREEN_DEPTH = 6;
export const CONFIRM_DEPTH = 10;
export const MIN_GAMES_FOR_PERSONAL_CONCLUSION = 30;

function ratingThreshold(rating) {
  if (!Number.isFinite(rating)) return 200;
  if (rating < 1200) return 250;
  if (rating < 1600) return 180;
  if (rating < 2000) return 150;
  return 120;
}

export function normaliseUsername(username) {
  return username.trim().toLowerCase();
}

export function selectBlitzGames(games, username, limit = FAST_GAME_LIMIT) {
  const player = normaliseUsername(username);
  return games
    .filter((game) => {
      const isPlayer = [game.white?.username, game.black?.username]
        .filter(Boolean)
        .map(normaliseUsername)
        .includes(player);
      return isPlayer
        && game.rated
        && game.rules === "chess"
        && game.time_class === "blitz"
        && ["180", "300"].includes(String(game.time_control));
    })
    .sort((left, right) => Number(left.end_time) - Number(right.end_time))
    .slice(-limit);
}

export async function fetchRecentBlitzGames(username, limit, onProgress) {
  const profile = encodeURIComponent(username.trim());
  const archiveResponse = await fetch(`https://api.chess.com/pub/player/${profile}/games/archives`);
  if (!archiveResponse.ok) {
    throw new Error(archiveResponse.status === 404 ? "That Chess.com username was not found." : "Chess.com could not provide game archives right now.");
  }
  const archiveData = await archiveResponse.json();
  const archives = Array.isArray(archiveData.archives) ? archiveData.archives.slice().reverse() : [];
  const games = [];
  for (let index = 0; index < archives.length && games.length < limit; index += 1) {
    onProgress?.(`Getting public games (${games.length}/${limit})`, 5 + Math.min(index * 4, 20));
    const response = await fetch(archives[index]);
    if (!response.ok) continue;
    const month = await response.json();
    games.push(...selectBlitzGames(month.games || [], username, limit));
  }
  return selectBlitzGames(games, username, limit);
}

function uciToMove(game, uci) {
  if (!uci || uci === "(none)" || uci === "0000") return null;
  try {
    return game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || "q" });
  } catch {
    return null;
  }
}

function other(color) {
  return color === "w" ? "b" : "w";
}

function withTurn(fen, turn) {
  const parts = fen.split(" ");
  parts[1] = turn;
  return parts.join(" ");
}

function scoreForPlayer(engineScore, playerColor, sideToMove) {
  return playerColor === sideToMove ? engineScore : -engineScore;
}

function wasReplyAlreadyACapture(fenBefore, playerColor, replyUci) {
  const beforeOpponent = new Chess(withTurn(fenBefore, other(playerColor)));
  const reply = uciToMove(beforeOpponent, replyUci);
  return Boolean(reply?.captured);
}

function wasReplyAlreadyACheck(fenBefore, playerColor, replyUci) {
  const beforeOpponent = new Chess(withTurn(fenBefore, other(playerColor)));
  const reply = uciToMove(beforeOpponent, replyUci);
  return Boolean(reply && beforeOpponent.isCheck());
}

function phaseOfFen(fen) {
  const [position, , , , , moveNumber] = fen.split(" ");
  if (Number(moveNumber) < 10) return "opening";
  const nonPawnPieces = (position.match(/[nbrqNBRQ]/g) || []).length;
  return nonPawnPieces <= 6 ? "endgame" : "middlegame";
}

function pieceName(piece) {
  return ({ p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" })[piece] || "piece";
}

function opportunityFromMove(beforeFen, played, gameIndex) {
  return { gameIndex, phase: phaseOfFen(beforeFen), piece: pieceName(played.piece) };
}

function observationFromMove({ beforeFen, afterFen, played, playerColor, rating, beforeEngine, afterEngine, game, gameIndex }) {
  if (!beforeEngine.bestMove || !afterEngine.bestMove) return null;
  const before = new Chess(beforeFen);
  const after = new Chess(afterFen);
  const replyBoard = new Chess(afterFen);
  const reply = uciToMove(replyBoard, afterEngine.bestMove);
  const bestBoard = new Chess(beforeFen);
  const best = uciToMove(bestBoard, beforeEngine.bestMove);
  if (!reply || !best) return null;

  const evalBefore = scoreForPlayer(beforeEngine.scoreCp, playerColor, before.turn());
  const evalAfter = scoreForPlayer(afterEngine.scoreCp, playerColor, after.turn());
  const dropCp = evalBefore - evalAfter;
  if (dropCp < ratingThreshold(rating)) return null;

  const replyCapturesMovedPiece = Boolean(reply.captured && reply.to === played.to);
  const replyWasAlreadyCapture = wasReplyAlreadyACapture(beforeFen, playerColor, afterEngine.bestMove);
  const sourceSafe = !before.isAttacked(played.from, other(playerColor));
  const destinationAttacked = after.isAttacked(played.to, other(playerColor));
  const destinationDefenders = after.attackers(played.to, playerColor).length;
  const replyGivesCheck = replyBoard.isCheck();
  const replyWasAlreadyCheck = wasReplyAlreadyACheck(beforeFen, playerColor, afterEngine.bestMove);
  const playedIsCapture = Boolean(played.captured);
  const playedGivesCheck = after.isCheck();
  const bestIsCapture = Boolean(best.captured);
  const bestGivesCheck = bestBoard.isCheck();
  const missedCapture = Boolean(bestIsCapture && !playedIsCapture);
  const missedCheck = Boolean(bestGivesCheck && !playedGivesCheck);
  const opensNewCapture = Boolean(reply.captured && !replyWasAlreadyCapture);
  const opensNewCheck = Boolean(replyGivesCheck && !replyWasAlreadyCheck);
  const opponentForcingReply = Boolean(reply.captured || replyGivesCheck);
  const ownForcingOption = Boolean(bestIsCapture || bestGivesCheck);
  const mechanisms = [];
  if (opensNewCapture && replyCapturesMovedPiece && sourceSafe && destinationAttacked) mechanisms.push("safe-piece-into-attack");
  if (sourceSafe && destinationAttacked) mechanisms.push("moves-safe-piece-into-attack");
  if (destinationAttacked && destinationDefenders === 0) mechanisms.push("undefended-destination");
  if (opensNewCheck) mechanisms.push("opens-new-check");
  if (missedCapture) mechanisms.push("missed-capture");
  if (missedCheck) mechanisms.push("missed-check");
  if (opensNewCapture) mechanisms.push("opens-new-capture");
  if (opponentForcingReply) mechanisms.push("opponent-forcing-reply");
  if (ownForcingOption) mechanisms.push("own-forcing-option");

  return {
    gameIndex,
    gameUrl: game.url || "",
    playedAt: game.end_time || 0,
    move: played.san,
    bestMove: best.san,
    reply: reply.san,
    fenBefore: beforeFen,
    evalDropCp: Math.round(dropCp),
    phase: phaseOfFen(beforeFen),
    piece: pieceName(played.piece),
    sourceSafe,
    destinationAttacked,
    destinationDefenders,
    replyCapturesMovedPiece,
    replyIsCapture: Boolean(reply.captured),
    replyGivesCheck,
    playedIsCapture,
    playedGivesCheck,
    bestIsCapture,
    bestGivesCheck,
    opensNewCapture,
    opensNewCheck,
    missedCapture,
    missedCheck,
    opponentForcingReply,
    ownForcingOption,
    mechanisms,
  };
}

export async function analyzeGames(games, username, engine, onProgress) {
  const player = normaliseUsername(username);
  const observations = [];
  const opportunities = [];
  let screenedPositions = 0;
  let screenCandidates = 0;
  for (let gameIndex = 0; gameIndex < games.length; gameIndex += 1) {
    const game = games[gameIndex];
    const playerColor = normaliseUsername(game.white.username) === player ? "w" : "b";
    const rating = Number(playerColor === "w" ? game.white.rating : game.black.rating);
    const replay = new Chess();
    try {
      replay.loadPgn(game.pgn);
    } catch {
      continue;
    }
    const moves = replay.history({ verbose: true });
    replay.reset();
    for (let ply = 0; ply < moves.length; ply += 1) {
      const beforeFen = replay.fen();
      const playerTurn = replay.turn() === playerColor;
      const played = replay.move(moves[ply]);
      const afterFen = replay.fen();
      if (!playerTurn || ply < 6 || !played) continue;
      opportunities.push(opportunityFromMove(beforeFen, played, gameIndex));
      onProgress?.(`Checking game ${gameIndex + 1} of ${games.length}`, 25 + Math.round(((gameIndex + ply / Math.max(moves.length, 1)) / games.length) * 70));
      const beforeScreen = await engine.analyze(beforeFen, SCREEN_DEPTH);
      const afterScreen = await engine.analyze(afterFen, SCREEN_DEPTH);
      screenedPositions += 1;
      // This move is made by playerColor: the position switches turns after it.
      const screenDrop = scoreForPlayer(beforeScreen.scoreCp, playerColor, playerColor)
        - scoreForPlayer(afterScreen.scoreCp, playerColor, other(playerColor));
      if (screenDrop < ratingThreshold(rating) * 0.70) continue;
      screenCandidates += 1;
      const beforeEngine = await engine.analyze(beforeFen, CONFIRM_DEPTH);
      const afterEngine = await engine.analyze(afterFen, CONFIRM_DEPTH);
      const observation = observationFromMove({
        beforeFen, afterFen, played, playerColor, rating, beforeEngine, afterEngine, game, gameIndex,
      });
      if (observation) observations.push(observation);
    }
  }
  return { observations, opportunities, screenedPositions, screenCandidates };
}

const MECHANISMS = [
  {
    id: "safe-piece-into-attack",
    title: "A safe piece is moved into attack",
    description: "The move puts a previously safe piece on a square the opponent can immediately attack.",
    cue: "Before you release a move, point to its destination square and name the enemy piece that attacks it.",
    tests: [
      "Source square was not attacked before the move",
      "Destination square was attacked after the move",
      "Stockfish's best reply captured the piece that moved",
    ],
  },
  {
    id: "undefended-destination",
    title: "A piece is left without a defender",
    description: "The destination square has no friendly defender after the move.",
    cue: "Before you release a move, count the attackers and defenders of the destination square.",
    tests: [
      "Destination square was attacked after the move",
      "Destination square had no friendly defender",
    ],
  },
  {
    id: "moves-safe-piece-into-attack",
    title: "A safe piece is moved onto an attacked square",
    description: "The moved piece started safe, but its destination was under enemy attack.",
    cue: "For this move type, pause on the destination square: identify every enemy attacker before deciding whether the move is worth it.",
    tests: ["Source square was not attacked before the move", "Destination square was attacked after the move"],
  },
  {
    id: "opens-new-check",
    title: "A new checking reply is allowed",
    description: "The move creates a check that the opponent did not have one move earlier.",
    cue: "Before you release a move near your king, name the opponent's new checks in the final position.",
    tests: ["Stockfish's best reply gave check", "That checking reply was not a check one move earlier"],
  },
  {
    id: "missed-capture",
    title: "A forcing capture is passed up",
    description: "Stockfish preferred a capture, but the played move was not a capture.",
    cue: "Before a quiet move, scan your forcing captures once.",
    tests: ["Stockfish's best move was a capture", "The played move was not a capture"],
  },
  {
    id: "missed-check",
    title: "A forcing check is passed up",
    description: "Stockfish preferred a check, but the played move did not give check.",
    cue: "Before a quiet move, scan your forcing checks once.",
    tests: ["Stockfish's best move gave check", "The played move did not give check"],
  },
  {
    id: "opens-new-capture",
    title: "A new capture is allowed",
    description: "The move creates a capture that was not available one move earlier.",
    cue: "After choosing a move, scan the opponent's captures in the final position.",
    tests: ["Stockfish's best reply was a capture", "That capture was not available one move earlier"],
  },
  {
    id: "opponent-forcing-reply",
    title: "The opponent's forcing reply is missed",
    description: "After the move, Stockfish's best reply was an immediate check or capture.",
    cue: "After choosing a candidate, calculate the opponent's single most forcing reply: check first, then capture.",
    tests: ["Stockfish's best reply gave check or made a capture"],
  },
  {
    id: "own-forcing-option",
    title: "A forcing option is passed up",
    description: "Stockfish's preferred alternative was an immediate check or capture.",
    cue: "Before committing to a quiet idea, list your checks and captures once, then compare your intended move with the strongest one.",
    tests: ["Stockfish's best alternative gave check or made a capture"],
  },
];

const MECHANISM_BY_ID = new Map(MECHANISMS.map((mechanism) => [mechanism.id, mechanism]));
const GROUPING_PRIORITY = [
  "safe-piece-into-attack",
  "undefended-destination",
  "opens-new-check",
  "opens-new-capture",
  "missed-check",
  "missed-capture",
  "moves-safe-piece-into-attack",
  "opponent-forcing-reply",
  "own-forcing-option",
];

const CONTEXTS = [
  { id: "all", label: "", matches: () => true },
  { id: "phase", label: (item) => ` in the ${item.phase}`, matches: (item, seed) => item.phase === seed.phase },
  { id: "piece", label: (item) => ` after ${item.piece} moves`, matches: (item, seed) => item.piece === seed.piece },
  { id: "phase-piece", label: (item) => ` in the ${item.phase} after ${item.piece} moves`, matches: (item, seed) => item.phase === seed.phase && item.piece === seed.piece },
];

function rate(events, opportunities) {
  return opportunities ? events / opportunities : 0;
}

function candidatesForMechanism(mechanism, observations, opportunities, splitAt) {
  const trainingErrors = observations.filter((item) => item.gameIndex < splitAt);
  const laterErrors = observations.filter((item) => item.gameIndex >= splitAt);
  const trainingMoves = opportunities.filter((item) => item.gameIndex < splitAt);
  const laterMoves = opportunities.filter((item) => item.gameIndex >= splitAt);
  const trainingBaseline = rate(trainingErrors.length, trainingMoves.length);
  const laterBaseline = rate(laterErrors.length, laterMoves.length);
  const mechanismErrors = observations.filter((item) => item.mechanisms.includes(mechanism.id));
  const seeds = mechanismErrors.length ? mechanismErrors : [];
  return CONTEXTS.flatMap((context) => {
    const contextSeeds = context.id === "all" ? [null] : seeds;
    return contextSeeds.map((seed) => {
      const matchesContext = (item) => context.id === "all" || context.matches(item, seed);
      const earlier = trainingErrors.filter((item) => item.mechanisms.includes(mechanism.id) && matchesContext(item));
      const later = laterErrors.filter((item) => item.mechanisms.includes(mechanism.id) && matchesContext(item));
      const earlierMoves = trainingMoves.filter(matchesContext);
      const laterContextMoves = laterMoves.filter(matchesContext);
      const earlierRate = rate(earlier.length, earlierMoves.length);
      const laterRate = rate(later.length, laterContextMoves.length);
      return {
        ...mechanism,
        context: context.id === "all" ? null : { phase: seed.phase, piece: seed.piece, label: context.label(seed) },
        earlier,
        later,
        earlierMoves: earlierMoves.length,
        laterMoves: laterContextMoves.length,
        earlierRate,
        laterRate,
        earlierLift: trainingBaseline ? earlierRate / trainingBaseline : 0,
        laterLift: laterBaseline ? laterRate / laterBaseline : 0,
      };
    });
  });
}

export function findVerifiedTrigger(observations, opportunities, gameCount) {
  const splitAt = Math.max(1, Math.floor(gameCount * 0.75));
  const candidateMap = new Map();
  for (const candidate of MECHANISMS.flatMap((mechanism) => candidatesForMechanism(mechanism, observations, opportunities, splitAt))) {
    const key = `${candidate.id}:${candidate.context?.phase || "all"}:${candidate.context?.piece || "all"}`;
    if (!candidateMap.has(key)) candidateMap.set(key, candidate);
  }
  const candidates = [...candidateMap.values()]
    .filter((trigger) => (
      trigger.earlier.length >= 4
      && trigger.later.length >= 2
      && trigger.earlierMoves >= 8
      && trigger.laterMoves >= 4
      && trigger.earlierLift >= 1.25
      && trigger.laterLift >= 0.75
    ));
  if (!candidates.length) return null;
  candidates.sort((left, right) => (
    right.later.length - left.later.length
    || right.earlierLift - left.earlierLift
    || Number(Boolean(right.context)) - Number(Boolean(left.context))
  ));
  return candidates[0];
}

function allContextCandidates(mechanism, observations, opportunities) {
  const mechanismErrors = observations.filter((item) => item.mechanisms.includes(mechanism.id));
  const baseline = rate(observations.length, opportunities.length);
  const candidates = [];
  for (const context of CONTEXTS) {
    const seeds = context.id === "all" ? [null] : mechanismErrors;
    for (const seed of seeds) {
      const matches = (item) => context.id === "all" || context.matches(item, seed);
      const errors = mechanismErrors.filter(matches);
      const moves = opportunities.filter(matches);
      const errorRate = rate(errors.length, moves.length);
      candidates.push({
        ...mechanism,
        context: context.id === "all" ? null : { phase: seed.phase, piece: seed.piece, label: context.label(seed) },
        errors,
        moves: moves.length,
        errorRate,
        lift: baseline ? errorRate / baseline : 0,
      });
    }
  }
  const unique = new Map();
  for (const candidate of candidates) {
    const key = `${candidate.id}:${candidate.context?.phase || "all"}:${candidate.context?.piece || "all"}`;
    if (!unique.has(key)) unique.set(key, candidate);
  }
  return [...unique.values()];
}

export function findObservedFocusAreas(observations, opportunities, limit = 2) {
  const candidates = MECHANISMS.flatMap((mechanism) => allContextCandidates(mechanism, observations, opportunities))
    .filter((candidate) => candidate.errors.length >= 3 && candidate.moves >= 6)
    .filter((candidate) => candidate.context === null || candidate.lift >= 1.1)
    .sort((left, right) => (
      right.errors.length - left.errors.length
      || right.lift - left.lift
      || Number(Boolean(right.context)) - Number(Boolean(left.context))
    ));
  const selected = [];
  for (const candidate of candidates) {
    if (selected.some((item) => item.id === candidate.id)) continue;
    selected.push(candidate);
    if (selected.length === limit) break;
  }
  return selected;
}

export function buildErrorGroups(observations) {
  const groups = new Map();
  for (const observation of observations) {
    const mechanisms = Array.isArray(observation.mechanisms) ? observation.mechanisms : [];
    const mechanismId = GROUPING_PRIORITY.find((id) => mechanisms.includes(id)) || "engine-review";
    const mechanism = MECHANISM_BY_ID.get(mechanismId) || {
      id: "engine-review",
      title: "Engine-confirmed positions to review",
      description: "Stockfish found a costly move, but the current rule set did not assign one narrow tactical mechanism.",
      cue: "Use the real position to compare your intended idea with the opponent's strongest reply.",
      tests: ["The move passed the deeper Stockfish evaluation check"],
    };
    const key = `${mechanism.id}:${observation.phase}`;
    const existing = groups.get(key) || {
      id: key,
      ...mechanism,
      phase: observation.phase,
      observations: [],
    };
    existing.observations.push(observation);
    groups.set(key, existing);
  }
  return [...groups.values()]
    .map((group) => {
      const pieces = group.observations.reduce((counts, item) => {
        counts.set(item.piece, (counts.get(item.piece) || 0) + 1);
        return counts;
      }, new Map());
      const mainPiece = [...pieces.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || "piece";
      const averageDrop = Math.round(group.observations.reduce((total, item) => total + item.evalDropCp, 0) / group.observations.length);
      return {
        ...group,
        count: group.observations.length,
        averageDrop,
        mainPiece,
        sample: [...group.observations].sort((left, right) => right.evalDropCp - left.evalDropCp)[0],
      };
    })
    .sort((left, right) => right.count - left.count || right.averageDrop - left.averageDrop);
}

function numberDistance(left, right, scale) {
  return Math.min(Math.abs((left || 0) - (right || 0)) / scale, 1);
}

function densityDistance(left, right) {
  // Mechanism labels are intentionally excluded. Clusters are discovered from
  // the board context and engine outcome, then explained afterwards.
  const parts = [
    [left.phase !== right.phase, 0.14],
    [left.piece !== right.piece, 0.14],
    [left.playedIsCapture !== right.playedIsCapture, 0.07],
    [left.playedGivesCheck !== right.playedGivesCheck, 0.07],
    [left.sourceSafe !== right.sourceSafe, 0.07],
    [left.destinationAttacked !== right.destinationAttacked, 0.11],
    [left.replyCapturesMovedPiece !== right.replyCapturesMovedPiece, 0.10],
    [left.replyIsCapture !== right.replyIsCapture, 0.08],
    [left.replyGivesCheck !== right.replyGivesCheck, 0.08],
    [left.bestIsCapture !== right.bestIsCapture, 0.07],
    [left.bestGivesCheck !== right.bestGivesCheck, 0.07],
    [numberDistance(left.destinationDefenders, right.destinationDefenders, 3), 0.05],
    [numberDistance(left.evalDropCp, right.evalDropCp, 700), 0.05],
  ];
  return parts.reduce((total, [difference, weight]) => total + Number(difference) * weight, 0);
}

function dbscan(observations, epsilon, minimumPoints) {
  const labels = Array(observations.length).fill(undefined);
  const visited = Array(observations.length).fill(false);
  const neighborsOf = (index) => observations
    .map((item, candidate) => (densityDistance(observations[index], item) <= epsilon ? candidate : -1))
    .filter((candidate) => candidate >= 0);
  let clusterId = 0;
  for (let index = 0; index < observations.length; index += 1) {
    if (visited[index]) continue;
    visited[index] = true;
    const neighbors = neighborsOf(index);
    if (neighbors.length < minimumPoints) {
      labels[index] = -1;
      continue;
    }
    labels[index] = clusterId;
    const queue = [...neighbors];
    for (let position = 0; position < queue.length; position += 1) {
      const candidate = queue[position];
      if (!visited[candidate]) {
        visited[candidate] = true;
        const candidateNeighbors = neighborsOf(candidate);
        if (candidateNeighbors.length >= minimumPoints) {
          for (const neighbor of candidateNeighbors) if (!queue.includes(neighbor)) queue.push(neighbor);
        }
      }
      if (labels[candidate] === undefined || labels[candidate] === -1) labels[candidate] = clusterId;
    }
    clusterId += 1;
  }
  return labels.map((label) => label ?? -1);
}

function mode(values, fallback) {
  const counts = new Map();
  for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
  return [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || fallback;
}

export function clusterConfirmedErrors(observations) {
  if (observations.length < 8) return { clusters: [], noiseCount: observations.length, epsilon: 0.36, minimumPoints: 4 };
  const minimumPoints = observations.length >= 60 ? 5 : 4;
  const epsilon = 0.36;
  const labels = dbscan(observations, epsilon, minimumPoints);
  const membersById = new Map();
  labels.forEach((label, index) => {
    if (label === -1) return;
    const members = membersById.get(label) || [];
    members.push(observations[index]);
    membersById.set(label, members);
  });
  const maximumSpecificCluster = Math.floor(observations.length * 0.35);
  const kept = [...membersById.entries()].filter(([, members]) => members.length <= maximumSpecificCluster);
  const rejectedMembers = [...membersById.entries()]
    .filter(([, members]) => members.length > maximumSpecificCluster)
    .reduce((total, [, members]) => total + members.length, 0);
  const clusters = kept.map(([id, members]) => {
    const phase = mode(members.map((item) => item.phase), "mixed");
    const piece = mode(members.map((item) => item.piece), "piece");
    const averageDrop = Math.round(members.reduce((total, item) => total + item.evalDropCp, 0) / members.length);
    const sample = [...members].sort((left, right) => right.evalDropCp - left.evalDropCp)[0];
    const mechanismId = mode(members.flatMap((item) => item.mechanisms || []), null);
    const mechanism = MECHANISM_BY_ID.get(mechanismId);
    return {
      id: `density-${id}`,
      title: `${phase[0].toUpperCase()}${phase.slice(1)} ${piece} decision cluster`,
      description: `${members.length} engine-confirmed errors are close together in the model's board-context feature space.`,
      phase,
      piece,
      count: members.length,
      averageDrop,
      sample,
      members,
      explanation: mechanism?.title || "No single tactical explanation dominates this cluster",
      cue: mechanism?.cue || "Compare your intended move with the opponent's strongest reply in each example.",
    };
  }).sort((left, right) => right.count - left.count || right.averageDrop - left.averageDrop);
  return {
    clusters,
    noiseCount: labels.filter((label) => label === -1).length + rejectedMembers,
    epsilon,
    minimumPoints,
  };
}

export function boardSquares(fen) {
  const ranks = fen.split(" ")[0].split("/");
  return ranks.flatMap((rank) => {
    const squares = [];
    for (const char of rank) {
      if (/\d/.test(char)) squares.push(...Array(Number(char)).fill(""));
      else squares.push(PIECE_GLYPHS[char] || "");
    }
    return squares;
  });
}
