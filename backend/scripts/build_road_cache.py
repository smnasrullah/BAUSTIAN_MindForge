"""Dev only, needs internet: road distance/time matrix + depot-agent polylines from public OSRM.

    docker compose -p agentpulse-verify --profile tools run --rm --no-deps backend-tools \
        python -m scripts.build_road_cache

Writes backend/data/road_cache/<distributor code>.json (committed, read by
app/services/van_geometry.py). The app never calls the internet: a missing pair is estimated
(haversine x VAN_ROAD_FACTOR) and labelled `estimate`. OSRM snaps each synthetic point to the
nearest road. Durations are OSRM free-flow car times; the planner multiplies them by the day
factors (Eid, rain, hat-bazar). Rate: one request per --pause seconds (OSRM demo server policy).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.services.seed import DISTRIBUTORS
from app.services.van_geometry import CACHE_DIR, agent_key, depot_key
from ml.data_gen.agents import build_agents
from ml.data_gen.dataset import N_AGENTS

BLOCK = 50  # two blocks per request stay under the demo server's 100-coordinate table limit
Pt = tuple[str, float, float]  # key, lat, lng


SKIPPED: list[str] = []  # requests OSRM refused (HTTP 4xx): those pairs stay `estimate`


def _get(url: str, pause: float) -> dict[str, Any] | None:
    """None when OSRM refuses this one request (e.g. a point it cannot snap); network errors
    still abort the whole run."""
    time.sleep(pause)
    req = urllib.request.Request(url, headers={"User-Agent": "agentpulse-road-cache/1 (dev)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            doc: dict[str, Any] = json.load(res)
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            body = exc.read(300).decode(errors="replace")
            SKIPPED.append(f"HTTP {exc.code}: {body}")
            return None
        raise
    if doc.get("code") != "Ok":
        SKIPPED.append(f"{doc.get('code')}: {doc.get('message')}")
        return None
    return doc


def _coords(points: list[Pt]) -> str:
    return ";".join(f"{lng:.6f},{lat:.6f}" for _, lat, lng in points)


def _table(base: str, points: list[Pt], pause: float) -> dict[str, list[float]]:
    legs: dict[str, list[float]] = {}
    blocks = [points[i:i + BLOCK] for i in range(0, len(points), BLOCK)]
    for src in blocks:
        for dst in blocks:
            both = src + [p for p in dst if p not in src]
            if len(both) < 2:  # a one-point block against itself has no pair to ask for
                continue
            idx = {p[0]: i for i, p in enumerate(both)}
            url = (f"{base}/table/v1/driving/{_coords(both)}?annotations=distance,duration"
                   f"&sources={';'.join(str(idx[p[0]]) for p in src)}"
                   f"&destinations={';'.join(str(idx[p[0]]) for p in dst)}")
            doc = _get(url, pause)
            if doc is None:
                continue
            for i, a in enumerate(src):
                for j, b in enumerate(dst):
                    km, sec = doc["distances"][i][j], doc["durations"][i][j]
                    if a[0] != b[0] and km is not None and sec is not None:
                        legs[f"{a[0]}|{b[0]}"] = [round(km / 1000, 3), round(sec / 60, 2)]
    return legs


def _polylines(base: str, depot: Pt, agents: list[Pt], pause: float) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in agents:
        for x, y in ((depot, a), (a, depot)):
            url = (f"{base}/route/v1/driving/{_coords([x, y])}"
                   "?overview=simplified&geometries=polyline")
            doc = _get(url, pause)
            if doc is not None:
                out[f"{x[0]}|{y[0]}"] = doc["routes"][0]["geometry"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=get_settings().seed)
    ap.add_argument("--base-url", default="https://router.project-osrm.org")
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=CACHE_DIR)
    args = ap.parse_args()
    world = np.random.default_rng(np.random.SeedSequence(args.seed).spawn(5)[0])
    agents = build_agents(N_AGENTS, world)
    started = time.perf_counter()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        for d in DISTRIBUTORS:
            depot: Pt = (depot_key(d.code), d.hub_lat, d.hub_lng)
            mine: list[Pt] = [(agent_key(a.code), a.lat, a.lng) for a in agents
                              if a.distributor_code == d.code]
            doc = {"version": 1, "source": "osrm", "base_url": args.base_url, "seed": args.seed,
                   "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                   "legs": _table(args.base_url, [depot, *mine], args.pause),
                   "polylines": _polylines(args.base_url, depot, mine, args.pause)}
            # Written per distributor: a later network failure keeps the finished ones.
            (args.out / f"{d.code}.json").write_text(json.dumps(doc, separators=(",", ":")),
                                                     encoding="utf-8")
            print(f"{d.code}: {len(mine)} agents, {len(doc['legs'])} legs, "
                  f"{len(doc['polylines'])} polylines", flush=True)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"road cache stopped ({exc}); missing pairs use the estimate path")
        return 2
    size = sum(p.stat().st_size for p in args.out.glob("*.json"))
    print(f"wrote {size / 1e6:.2f} MB in {time.perf_counter() - started:.0f} s; "
          f"{len(SKIPPED)} refused requests (pairs left to the estimate)")
    for msg in SKIPPED[:5]:
        print("  refused:", msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
