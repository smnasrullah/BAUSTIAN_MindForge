// k6 load test on the main read paths (verify stack only; it generates load).
//   docker run --rm --network agentpulse-verify_default -v ./scripts/perf:/w grafana/k6 run /w/load.js
// Env: BASE (default http://frontend, i.e. through nginx), VUS (50), DURATION (2m),
//      THINK_MIN / THINK_MAX seconds between page loads (3 / 6: a person reading the page;
//      THINK_MIN=1 THINK_MAX=1 is the aggressive profile).
// Pass criteria: zero errors, p95 within the docs/PERFORMANCE.md budgets.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE || "http://frontend";
const API = `${BASE}/api/v1`;

export const options = {
  scenarios: {
    read_paths: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 50),
      duration: __ENV.DURATION || "2m",
    },
  },
  thresholds: {
    http_req_failed: ["rate==0"],
    "http_req_duration{kind:read}": ["p(95)<300"],
    "http_req_duration{kind:heavy}": ["p(95)<500"],
    "http_req_duration{kind:whatif}": ["p(95)<300"],
    http_req_duration: ["max<1000"],
  },
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};

function login(role) {
  const r = http.post(`${API}/auth/demo-login`, JSON.stringify({ role }), {
    headers: { "Content-Type": "application/json" },
  });
  if (r.status !== 200) throw new Error(`demo-login ${role}: ${r.status}`);
  return r.json("access_token");
}

export function setup() {
  return { agent: login("agent"), distributor: login("distributor"), admin: login("admin") };
}

const AGENT_PATHS = [
  ["read", "/agents/1/summary"],
  ["read", "/agents/1/forecast?horizon_hours=72"],
  ["heavy", "/agents/1/stockout"],
  ["read", "/agents/1/risk"],
  ["read", "/agents/1/recommendation"],
  ["read", "/agents/1/explanations?target=cash&lang=bn"],
  ["read", "/notifications"],
  ["read", "/liquidity-requests/inbox"],
  ["read", "/system/freshness"],
];
const DIST_PATHS = [
  ["heavy", "/agents/risk?horizon=24"],
  ["heavy", "/map/agents"],
  ["read", "/swaps"],
  ["read", "/anomalies"],
  ["read", "/impact/summary"],
  ["read", "/distributor/briefing?lang=en"],
  ["read", "/notifications"],
];
const ADMIN_PATHS = [
  ["read", "/admin/overview"],
  ["read", "/admin/users"],
  ["heavy", "/admin/audit-log"],
];

function get(token, [kind, path]) {
  const r = http.get(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    tags: { kind, name: path.split("?")[0] },
  });
  check(r, { "status 200": (x) => x.status === 200 });
}

export default function (tokens) {
  const roll = __VU % 10;
  if (roll < 5) {
    for (const p of AGENT_PATHS) get(tokens.agent, p);
    const r = http.post(
      `${API}/agents/1/whatif`,
      JSON.stringify({ float_type: "cash", delta_amount: 20000 }),
      {
        headers: { Authorization: `Bearer ${tokens.agent}`, "Content-Type": "application/json" },
        tags: { kind: "whatif", name: "/agents/1/whatif" },
      },
    );
    check(r, { "status 200": (x) => x.status === 200 });
  } else if (roll < 9) {
    for (const p of DIST_PATHS) get(tokens.distributor, p);
  } else {
    for (const p of ADMIN_PATHS) get(tokens.admin, p);
  }
  get(tokens.agent, ["read", "/system/status"]);
  const lo = Number(__ENV.THINK_MIN || 3);
  const hi = Number(__ENV.THINK_MAX || 6);
  sleep(lo + Math.random() * (hi - lo));
}
