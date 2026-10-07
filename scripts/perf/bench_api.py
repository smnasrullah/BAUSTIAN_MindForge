"""API latency bench: every read endpoint as the right role, N timed calls each (after warm-up).

Runs inside a container on the verify stack network (needs httpx, stdlib otherwise):
  docker run --rm --network agentpulse-verify_default -v ./scripts/perf:/w --entrypoint python \
      agentpulse-verify-backend /w/bench_api.py --base http://backend:8000 --out /w/out/api.json
Reports p50/p95/max ms, SQL query count (Server-Timing, PERF_HEADERS=true) and response size.
Exit 1 when --check is given and any endpoint misses its budget (see BUDGETS).
"""

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# p95 budgets in ms (docs/PERFORMANCE.md). Default for reads; heavier pages have their own.
READ_BUDGET = 300
HEAVY_BUDGET = 500
LLM_BUDGET = 1000  # template/replay path; live LLM is excluded on the verify stack
WARMUP = 8  # untimed calls first: two per worker process (4 by default)
HEAVY = ("/agents/risk", "/map/agents", "/stockout", "export.csv", "/admin/audit-log")
LLM = ("briefing", "narrative", "/copilot/", "/narrate", "/explanations")
_TIMING = re.compile(r'db;desc="(\d+) queries";dur=([\d.]+), app;dur=([\d.]+)')


@dataclass
class Case:
    role: str
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    @property
    def label(self) -> str:
        q = "&".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.method} {self.path}" + (f"?{q}" if q else "") + f" [{self.role}]"

    @property
    def budget(self) -> int:
        if any(s in self.path for s in LLM):
            return LLM_BUDGET
        if any(s in self.path for s in HEAVY) or self.method == "POST" and "whatif" not in self.path:
            return HEAVY_BUDGET
        return READ_BUDGET


def login(client: httpx.Client, role: str) -> str:
    r = client.post("/api/v1/auth/demo-login", json={"role": role})
    r.raise_for_status()
    return str(r.json()["access_token"])


def first_id(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> Any:
    r = client.get(path, params=params)
    if r.status_code != 200:
        return None
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    return items[0]["id"] if items else None


def build_cases(base: str) -> list[Case]:
    v = "/api/v1"
    hdr = {}
    with httpx.Client(base_url=base, timeout=30) as c:
        for role in ("agent", "distributor", "admin"):
            hdr[role] = {"Authorization": f"Bearer {login(c, role)}"}
        c.headers.update(hdr["agent"])
        aid = c.get(f"{v}/auth/me").json()["agent_id"]
        c.headers.update(hdr["distributor"])
        anomaly = first_id(c, f"{v}/anomalies")
        c.headers.update(hdr["admin"])
        job = first_id(c, f"{v}/admin/jobs")
        lr = first_id(c, f"{v}/admin/liquidity-requests")
    # Mutating endpoints are covered by the fuzz and e2e runs, not timed here.
    a, d, ad = "agent", "distributor", "admin"
    cases = [
        Case("public", "GET", f"{v}/health"),
        Case("public", "GET", f"{v}/system/health"),
        Case("public", "GET", f"{v}/system/status"),
        Case(a, "GET", f"{v}/system/freshness"),
        Case(a, "GET", f"{v}/auth/me"),
        Case(a, "GET", f"{v}/users/me/profile"),
        Case(a, "GET", f"{v}/notifications"),
        Case(d, "GET", f"{v}/notifications"),
        Case(d, "GET", f"{v}/search", {"q": "mir"}),
        Case(a, "GET", f"{v}/agents/{aid}/summary"),
        Case(a, "GET", f"{v}/agents/{aid}"),
        Case(a, "GET", f"{v}/agents/{aid}/forecast", {"horizon_hours": 72}),
        Case(a, "GET", f"{v}/agents/{aid}/stockout"),
        Case(a, "GET", f"{v}/agents/{aid}/risk"),
        Case(a, "GET", f"{v}/agents/{aid}/recommendation"),
        Case(a, "GET", f"{v}/agents/{aid}/explanations", {"target": "cash", "lang": "bn"}),
        Case(a, "POST", f"{v}/agents/{aid}/whatif", body={"float_type": "cash",
                                                          "delta_amount": 20000}),
        Case(a, "GET", f"{v}/agents/{aid}/briefing", {"lang": "bn"}),
        Case(a, "GET", f"{v}/copilot/suggestions", {"lang": "bn"}),
        Case(a, "POST", f"{v}/explanations/narrate", body={"agent_id": aid, "lang": "en"}),
        Case(a, "GET", f"{v}/swaps"),
        Case(a, "GET", f"{v}/recommendation-requests"),
        Case(a, "GET", f"{v}/liquidity-requests/mine"),
        Case(a, "GET", f"{v}/liquidity-requests/inbox"),
        Case(a, "GET", f"{v}/liquidity-requests/opt-out"),
        Case(a, "GET", f"{v}/responsible-ai/model-card", {"lang": "en"}),
        Case(d, "GET", f"{v}/agents"),
        Case(d, "GET", f"{v}/agents/risk", {"horizon": 24}),
        Case(d, "GET", f"{v}/agents/risk", {"horizon": 72, "sort": "risk", "page_size": 100}),
        Case(d, "GET", f"{v}/agents/risk/export.csv", {"horizon": 24}),
        Case(d, "GET", f"{v}/map/agents"),
        Case(d, "GET", f"{v}/map/agents", {"at_hour": 18}),
        Case(d, "GET", f"{v}/agents/{aid}/forecast", {"horizon_hours": 72}),
        Case(d, "GET", f"{v}/agents/{aid}/stockout"),
        Case(d, "GET", f"{v}/swaps"),
        Case(d, "GET", f"{v}/swaps/export.csv"),
        Case(d, "GET", f"{v}/recommendation-requests"),
        Case(d, "GET", f"{v}/anomalies"),
        Case(d, "GET", f"{v}/impact/summary"),
        Case(d, "GET", f"{v}/impact/comparison"),
        Case(d, "GET", f"{v}/responsible-ai/fairness"),
        Case(d, "GET", f"{v}/distributor/briefing", {"lang": "en"}),
        Case(d, "GET", f"{v}/events"),
        Case(d, "GET", f"{v}/liquidity-requests/inbox"),
        Case(d, "GET", f"{v}/llm/status"),
        Case(ad, "GET", f"{v}/admin/overview"),
        Case(ad, "GET", f"{v}/admin/users"),
        Case(ad, "GET", f"{v}/admin/org"),
        Case(ad, "GET", f"{v}/admin/audit-log"),
        Case(ad, "GET", f"{v}/admin/audit-log/export.csv"),
        Case(ad, "GET", f"{v}/admin/data"),
        Case(ad, "GET", f"{v}/admin/data/assumptions"),
        Case(ad, "GET", f"{v}/admin/models"),
        Case(ad, "GET", f"{v}/admin/drift"),
        Case(ad, "GET", f"{v}/admin/jobs"),
        Case(ad, "GET", f"{v}/admin/llm/logs"),
        Case(ad, "GET", f"{v}/admin/llm/usage"),
        Case(ad, "GET", f"{v}/admin/liquidity-requests"),
        Case(ad, "GET", f"{v}/admin/liquidity-requests/settings"),
        Case(ad, "GET", f"{v}/admin/liquidity-requests/trigger-settings"),
        Case(ad, "GET", f"{v}/admin/liquidity-requests/demo"),
    ]
    if anomaly is not None:
        cases += [Case(d, "GET", f"{v}/anomalies/{anomaly}"),
                  Case(d, "GET", f"{v}/anomalies/{anomaly}/narrative", {"lang": "en"})]
    if job is not None:
        cases.append(Case(ad, "GET", f"{v}/admin/jobs/{job}"))
    if lr is not None:
        cases.append(Case(ad, "GET", f"{v}/liquidity-requests/{lr}"))
    build_cases.headers = hdr  # type: ignore[attr-defined]
    return cases


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(p * (len(s) - 1)))]


def run(base: str, n: int, only: str | None) -> list[dict[str, Any]]:
    cases = build_cases(base)
    hdr: dict[str, dict[str, str]] = build_cases.headers  # type: ignore[attr-defined]
    rows = []
    with httpx.Client(base_url=base, timeout=30) as c:
        for case in cases:
            if only and only not in case.path:
                continue
            headers = hdr.get(case.role, {})
            times, queries, statuses, size = [], [], set(), 0
            for i in range(n + WARMUP):
                t0 = time.perf_counter()
                r = c.request(case.method, case.path, params=case.params, json=case.body,
                              headers=headers)
                dt = (time.perf_counter() - t0) * 1000
                if i < WARMUP:
                    continue  # warm-up
                times.append(dt)
                statuses.add(r.status_code)
                size = len(r.content)
                m = _TIMING.search(r.headers.get("server-timing", ""))
                if m:
                    queries.append(int(m.group(1)))
            rows.append({
                "endpoint": case.label, "budget": case.budget,
                "p50": round(statistics.median(times), 1), "p95": round(pct(times, 0.95), 1),
                "max": round(max(times), 1),
                "queries": max(queries) if queries else None, "bytes": size,
                "status": sorted(statuses),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://backend:8000")
    ap.add_argument("-n", type=int, default=30)
    ap.add_argument("--only")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    rows = run(args.base, args.n, args.only)
    bad = [r for r in rows if r["p95"] > r["budget"] or any(s >= 500 for s in r["status"])]
    for r in sorted(rows, key=lambda r: -r["p95"]):
        flag = "OVER" if r in bad else "ok  "
        print(f"{flag} p50={r['p50']:7.1f} p95={r['p95']:7.1f} q={r['queries']!s:>4} "
              f"{r['bytes']:>8}B {r['status']} {r['endpoint']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
    print(f"{len(rows)} endpoints, {len(bad)} over budget or 5xx")
    return 1 if args.check and bad else 0


if __name__ == "__main__":
    sys.exit(main())
