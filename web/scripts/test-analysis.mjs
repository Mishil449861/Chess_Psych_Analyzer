import assert from "node:assert/strict";
import { clusterConfirmedErrors, findObservedFocusAreas, findVerifiedTrigger, selectBlitzGames } from "../src/analysis.js";

const username = "playerx";
const games = [
  { white: { username }, black: { username: "opponent" }, rated: true, rules: "chess", time_class: "blitz", time_control: "300", end_time: 2 },
  { white: { username }, black: { username: "opponent" }, rated: true, rules: "chess", time_class: "blitz", time_control: "180", end_time: 1 },
  { white: { username }, black: { username: "opponent" }, rated: true, rules: "chess", time_class: "bullet", time_control: "60", end_time: 3 },
];
assert.equal(selectBlitzGames(games, username).length, 2);

const opportunities = [];
for (let gameIndex = 0; gameIndex < 40; gameIndex += 1) {
  const matching = gameIndex < 10 || (gameIndex >= 30 && gameIndex < 38);
  opportunities.push({ gameIndex, phase: matching ? "middlegame" : "opening", piece: matching ? "knight" : "pawn" });
}

const observations = [0, 2, 5, 8, 31, 35].map((gameIndex) => ({
  gameIndex,
  phase: "middlegame",
  piece: "knight",
  evalDropCp: 220,
  mechanisms: ["safe-piece-into-attack"],
}));

const trigger = findVerifiedTrigger(observations, opportunities, 40);
assert.ok(trigger, "the repeated mechanism should survive the holdout test");
assert.equal(trigger.id, "safe-piece-into-attack");
assert.equal(trigger.context?.phase, "middlegame");
assert.equal(trigger.context?.piece, "knight");

const focusAreas = findObservedFocusAreas(observations, opportunities);
assert.equal(focusAreas.length, 1, "repeated evidence should remain useful before a personal claim");
assert.equal(focusAreas[0].id, "safe-piece-into-attack");

const clusterInput = [
  { phase: "middlegame", piece: "knight", sourceSafe: true, destinationAttacked: true, replyCapturesMovedPiece: true, replyIsCapture: true, replyGivesCheck: false, bestIsCapture: false, bestGivesCheck: false },
  { phase: "opening", piece: "pawn", sourceSafe: false, destinationAttacked: false, replyCapturesMovedPiece: false, replyIsCapture: false, replyGivesCheck: true, bestIsCapture: true, bestGivesCheck: true },
  { phase: "endgame", piece: "king", sourceSafe: true, destinationAttacked: false, replyCapturesMovedPiece: false, replyIsCapture: true, replyGivesCheck: true, bestIsCapture: false, bestGivesCheck: true },
  { phase: "middlegame", piece: "rook", sourceSafe: false, destinationAttacked: true, replyCapturesMovedPiece: false, replyIsCapture: false, replyGivesCheck: false, bestIsCapture: true, bestGivesCheck: false },
].flatMap((shape) => Array.from({ length: 5 }, (_, index) => ({
  ...shape,
  mechanisms: ["safe-piece-into-attack"],
  evalDropCp: 220 + index,
})));
const clustering = clusterConfirmedErrors(clusterInput);
assert.equal(clustering.clusters.length, 4, "separate dense regions should become actual clusters");
assert.equal(clustering.clusters[0].count, 5);

const noTrigger = findVerifiedTrigger(observations.slice(0, 4), opportunities, 40);
assert.equal(noTrigger, null, "a pattern without later repeats must be withheld");

console.log("Browser analysis contracts passed.");
