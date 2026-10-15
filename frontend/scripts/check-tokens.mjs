// Every colour lives in src/design/tokens/ (docs/architecture/frontend_system.md §4): a raw hex,
// rgb() or hsl() anywhere else bypasses the validated palettes and dark mode. CI runs this.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;
const ALLOWED = ["design/tokens/", "shared/api/"]; // tokens; generated API schema text
const RAW = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else if (/\.(css|tsx?)$/.test(name)) yield path;
  }
}

const hits = [];
for (const file of files(SRC)) {
  const rel = relative(SRC, file);
  if (ALLOWED.some((a) => rel.startsWith(a))) continue;
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (RAW.test(line)) hits.push(`src/${rel}:${i + 1}: ${line.trim()}`);
  });
}
if (hits.length) {
  console.error(`Raw colours outside src/design/tokens/ — use a token:\n${hits.join("\n")}`);
  process.exit(1);
}
console.log("ok: every colour comes from a design token");
