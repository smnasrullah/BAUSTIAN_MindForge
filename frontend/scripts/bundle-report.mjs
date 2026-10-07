// Bundle report for a build made with --manifest: chunk count, initial JS (entry + static imports)
// gzip size, and per key route the extra JS files and KB a first visit fetches after the initial
// set (HTTP/1.1 fetches six at a time, so the file count matters on slow networks).
//   npx vite build --manifest && node scripts/bundle-report.mjs [distDir]
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const dist = process.argv[2] ?? "dist";
const manifest = JSON.parse(readFileSync(join(dist, ".vite", "manifest.json"), "utf8"));
const gz = (file) => gzipSync(readFileSync(join(dist, file)), { level: 9 }).length;
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;

/** Files a chunk needs: itself plus its static imports, transitively. */
function closure(keys, seen = new Set()) {
  for (const key of keys) {
    const c = manifest[key];
    if (!c || seen.has(c.file)) continue;
    seen.add(c.file);
    closure(c.imports ?? [], seen);
  }
  return seen;
}

const entryKey = Object.keys(manifest).find((k) => manifest[k].isEntry);
const initial = closure([entryKey]);
const allJs = readdirSync(join(dist, "assets")).filter((f) => f.endsWith(".js"));
const initialGz = [...initial].reduce((s, f) => s + gz(f), 0);
console.log(`chunks=${allJs.length} initial=${initial.size} files ${kb(initialGz)} gz`);

const ROUTES = {
  landing: ["LandingPage", "bn.json"],
  login: ["LoginPage", "bn.json"],
  agentHome: ["AppShell", "AgentHomePage"],
  controlRoom: ["AppShell", "ControlRoomPage"],
  adminOverview: ["AppShell", "AdminOverviewPage"],
};
for (const [route, names] of Object.entries(ROUTES)) {
  const keys = names.map((n) => Object.keys(manifest).find((k) => k.endsWith(`/${n}.tsx`) || k.endsWith(`/${n}`))).filter(Boolean);
  if (keys.length !== names.length) {
    console.log(`${route.padEnd(14)} (page module not found)`);
    continue;
  }
  const extra = [...closure(keys)].filter((f) => !initial.has(f));
  console.log(`${route.padEnd(14)} +${String(extra.length).padStart(3)} files ${kb(extra.reduce((s, f) => s + gz(f), 0))} gz`);
}
