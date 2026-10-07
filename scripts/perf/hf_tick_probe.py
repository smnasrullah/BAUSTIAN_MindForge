"""Latency of 4 read endpoints, sequential, for a fixed time (run while a tick executes).
Usage (verify network): python hf_tick_probe.py --base http://backend:8000 --seconds 90 [--van PATH]"""
import argparse, statistics, time
import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://backend:8000")
ap.add_argument("--seconds", type=int, default=90)
ap.add_argument("--van", default="")
a = ap.parse_args()
c = httpx.Client(base_url=a.base, timeout=60)
def tok(role): return {"Authorization": "Bearer " + c.post("/api/v1/auth/demo-login", json={"role": role}).json()["access_token"]}
d, ag = tok("distributor"), tok("agent")
cases = [("risk[dist]", "/api/v1/agents/risk?horizon=24", d), ("map[dist]", "/api/v1/map/agents", d),
         ("forecast[agent]", "/api/v1/agents/1/forecast?horizon_hours=72", ag), ("notif[agent]", "/api/v1/notifications", ag)]
if a.van: cases.append(("van[dist]", a.van, d))
res = {n: [] for n, _, _ in cases}
end = time.time() + a.seconds
while time.time() < end:
    for n, p, h in cases:
        t = time.perf_counter(); r = c.get(p, headers=h); res[n].append(((time.perf_counter() - t) * 1000, r.status_code))
for n, v in res.items():
    ms = sorted(x for x, _ in v); bad = sum(1 for _, s in v if s >= 400)
    print(f"{n:16} n={len(ms):4} p50={statistics.median(ms):7.1f} p95={ms[int(len(ms)*0.95)-1]:8.1f} max={ms[-1]:8.1f} errs={bad}")
