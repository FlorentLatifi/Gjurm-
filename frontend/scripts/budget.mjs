// Bundle budgets (docs/architecture/frontend_system.md §3), checked in CI after `npm run build`.
// Walks Vite's manifest from the entry and from each route, gzips what a visit downloads, and
// fails when a budget is exceeded. Run: node scripts/budget.mjs [--json]
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const DIST = new URL("../dist/", import.meta.url);
const budgets = JSON.parse(readFileSync(new URL("../budgets.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL(".vite/manifest.json", DIST), "utf8"));
const gz = new Map();
const size = (file) => {
  if (!gz.has(file)) gz.set(file, gzipSync(readFileSync(new URL(file, DIST)), { level: 9 }).length);
  return gz.get(file);
};

/** Every file a chunk pulls in eagerly: its JS, its static imports, and their CSS. */
function closure(key, seen = new Set()) {
  const chunk = manifest[key];
  if (!chunk || seen.has(chunk.file)) return seen;
  seen.add(chunk.file);
  for (const css of chunk.css ?? []) seen.add(css);
  for (const dep of chunk.imports ?? []) closure(dep, seen);
  return seen;
}
const total = (files) => [...files].reduce((sum, f) => sum + size(f), 0);
const kb = (bytes) => `${(bytes / 1024).toFixed(1)} KB`;

const entryKey = Object.keys(manifest).find((k) => manifest[k].isEntry);
const entry = closure(entryKey);
const results = [];
const check = (name, bytes, limit) => results.push({ name, bytes, limit, ok: bytes <= limit });

check("entry (JS + CSS, every page)", total(entry), budgets.entry);
const routes = Object.keys(manifest).filter((k) => manifest[k].isDynamicEntry && k.includes("/pages/"));
for (const route of routes) {
  const extra = [...closure(route)].filter((f) => !entry.has(f));
  const charts = extra.some((f) => /recharts/.test(f));
  const name = route.replace(/^src\/features\//, "").replace(/\.tsx$/, "");
  check(`route ${name}${charts ? " (charts)" : ""}`, total(extra), charts ? budgets.chartRoute : budgets.route);
  if (route.endsWith("stories/pages/Feed.tsx")) check("home page total", total(entry) + total(extra), budgets.home);
}
const fonts = Object.values(manifest)
  .flatMap((c) => c.assets ?? [])
  .filter((f, i, all) => f.endsWith(".woff2") && all.indexOf(f) === i);
check(`fonts (${fonts.length} woff2 files, all subsets)`, fonts.reduce((s, f) => s + readFileSync(new URL(f, DIST)).length, 0), budgets.fonts);

if (process.argv.includes("--json")) console.log(JSON.stringify(results, null, 2));
else for (const r of results) console.log(`${r.ok ? "ok  " : "OVER"} ${r.name.padEnd(48)} ${kb(r.bytes).padStart(9)} / ${kb(r.limit)}`);
const over = results.filter((r) => !r.ok);
if (over.length) {
  console.error(`\n${over.length} budget(s) exceeded. Shrink the change, or raise budgets.json in the same PR and say why.`);
  process.exit(1);
}
