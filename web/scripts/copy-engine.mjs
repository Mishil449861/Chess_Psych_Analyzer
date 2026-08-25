import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(root, "node_modules/stockfish/bin");
const destination = resolve(root, "public/engine");

rmSync(destination, { recursive: true, force: true });
mkdirSync(destination, { recursive: true });
for (const file of [
  "stockfish-18-lite-single.js",
  "stockfish-18-lite-single.wasm",
  "../Copying.txt",
]) {
  const target = file === "../Copying.txt" ? "LICENSE.txt" : file;
  cpSync(resolve(source, file), resolve(destination, target));
}
// Makes the copied UCI worker testable from Node too. Browsers ignore this.
writeFileSync(resolve(destination, "package.json"), '{"type":"commonjs"}\n');
