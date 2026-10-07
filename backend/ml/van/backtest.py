"""Van evaluation: routing policies A-D on held-out synthetic days (synthetic data).

Instances: every held-out day at 08:00 local, per distributor, the agents whose simulated cash
would run out within the horizon given the synthetic demand that then happened (oracle need).
This isolates routing quality from forecast error (the forecaster only runs on the seeded
database, so other seeds cannot be forecast; docs/DECISIONS.md). Amount and deadline follow the
rebalance rule (assess/advise), lost value per hour is the agent's mean cash-out over the
horizon. Day factors are not applied here. Multi-seed + sensitivity: ml/van/evaluate.py.

    python -m ml.van.backtest --out ml/van/van_v1_eval.json
"""

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np

from app.rules.rebalance_rules import RebalanceConfig, advise, assess
from app.rules.van_routing import matrix
from app.rules.van_routing.cost import EPS, due_h
from app.rules.van_routing.fairness import area
from app.rules.van_routing.matrix import Point, RoadCache
from app.rules.van_routing.models import Solution, Stop, VanConfig
from app.services.seed import DISTRIBUTORS
from ml.data_gen.dataset import Dataset, build_dataset
from ml.data_gen.timeline import HOLDOUT_DAYS, HOLDOUT_START, N_HOURS, hour_index
from ml.van.baselines import POLICIES

DECISION_HOUR = 8


@dataclass(frozen=True)
class Instance:
    day: int
    distributor: str
    stops: list[Stop]
    m: matrix.Matrix


def instances(ds: Dataset, cfg: VanConfig, cache: RoadCache) -> list[Instance]:
    horizon = int(cfg.horizon_h)
    rcfg = RebalanceConfig(horizon_h=horizon)
    start = hour_index(HOLDOUT_START)
    out: list[Instance] = []
    for day in range(HOLDOUT_DAYS):
        t0 = start + day * 24 + DECISION_HOUR
        if t0 + horizon > N_HOURS:
            continue
        now = HOLDOUT_START + timedelta(hours=day * 24 + DECISION_HOUR)
        for d in DISTRIBUTORS:
            stops: list[Stop] = []
            for i, a in enumerate(ds.agents):
                if a.distributor_code != d.code:
                    continue
                drain = ds.demand.amt_out[i, t0:t0 + horizon]
                need = assess(float(ds.floats.cash[i, t0]), float(a.cash_capacity), drain,
                              ds.demand.amt_in[i, t0:t0 + horizon], rcfg)
                advice = advise(need, now, None, rcfg)
                if advice is None or advice.amount <= 0 or need.crossing_h is None:
                    continue
                stops.append(Stop(agent_id=i, lat=a.lat, lng=a.lng, amount_bdt=advice.amount,
                                  deadline_h=need.crossing_h,
                                  lost_per_h_bdt=float(np.mean(drain)), district=a.district,
                                  group=f"{a.area.value}/tier{a.tier}"))
            points = [Point(f"depot:{d.code}", d.hub_lat, d.hub_lng)]
            points += [Point(f"agent:{ds.agents[s.agent_id].code}", s.lat, s.lng) for s in stops]
            out.append(Instance(day, d.code, stops, matrix.build(points, cache, cfg)))
    return out


def measure(sol: Solution, stops: list[Stop], cfg: VanConfig) -> dict[str, Any]:
    visits = [v for r in sol.routes for v in r.visits]
    late_h = sum(v.late_h for v in visits)
    skipped_h = sum(max(cfg.horizon_h - due_h(stops[d.stop]), 0.0) for d in sol.drops)
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    areas: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in stops:
        groups[s.group][0] += 1
        areas[area(s)][0] += 1
    for v in visits:
        groups[stops[v.stop].group][1] += 1
        areas[area(stops[v.stop])][1] += 1
    reasons: dict[str, int] = defaultdict(int)
    for d in sol.drops:
        reasons[d.reason] += 1
    o = sol.objective
    return {"km": sol.km, "trips": sol.trips, "van_bdt": o.van_bdt, "total_bdt": o.total_bdt,
            "stockout_h": late_h + skipped_h,
            "lost_value_bdt": o.late_penalty_bdt + o.skip_penalty_bdt,
            "on_time": sum(1 for v in visits if v.late_h <= EPS), "served": len(visits),
            "needed": len(stops), "solve_ms": sol.solve_ms, "groups": dict(groups),
            "areas": dict(areas), "drop_reasons": dict(reasons), "stopped_by": sol.stopped_by}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def total(k: str) -> float:
        return round(float(sum(r[k] for r in rows)), 2)

    needed = sum(r["needed"] for r in rows) or 1
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    areas: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    reasons: dict[str, int] = defaultdict(int)
    for r in rows:
        for g, (n, s) in r["groups"].items():
            groups[g][0] += n
            groups[g][1] += s
        for g, (n, s) in r["areas"].items():
            areas[g][0] += n
            areas[g][1] += s
        for k, n in r["drop_reasons"].items():
            reasons[k] += n
    ms = [r["solve_ms"] for r in rows]
    return {"km": total("km"), "trips": int(total("trips")), "van_bdt": total("van_bdt"),
            "total_bdt": total("total_bdt"), "stockout_h": total("stockout_h"),
            "lost_value_bdt": total("lost_value_bdt"),
            "deadline_hit_rate": round(sum(r["on_time"] for r in rows) / needed, 4),
            "service_rate": round(sum(r["served"] for r in rows) / needed, 4),
            "service_rate_by_group": {g: round(s / n, 4) for g, (n, s) in sorted(groups.items())},
            "service_rate_by_area": {g: round(s / n, 4) for g, (n, s) in sorted(areas.items())},
            "drop_reasons": dict(sorted(reasons.items())),
            "solve_ms_mean": round(float(np.mean(ms)), 1) if ms else 0.0,
            "solve_ms_max": round(float(np.max(ms)), 1) if ms else 0.0,
            "time_limit_hits": sum(1 for r in rows if r["stopped_by"] == "time_limit")}


def run(seed: int, cfg: VanConfig, cache: RoadCache, ds: Dataset | None = None
        ) -> dict[str, Any]:
    """`cache` = {} gives estimate distances (other seeds place agents elsewhere)."""
    inst = [i for i in instances(ds or build_dataset(seed), cfg, cache) if i.stops]
    per: dict[str, list[dict[str, Any]]] = {name: [] for name in POLICIES}
    for k, i in enumerate(inst):
        for name, policy in POLICIES.items():
            per[name].append(measure(policy(i.stops, i.m, cfg, seed * 1000 + k), i.stops, cfg))
    a = per["A_separate_trips"]
    d = per["D_full_model"]
    saving = [x["total_bdt"] - y["total_bdt"] for x, y in zip(a, d, strict=True)]
    return {"label": "synthetic data", "seed": seed, "decision_hour_local": DECISION_HOUR,
            "config": asdict(cfg), "instances": len(inst),
            "stops": sum(len(i.stops) for i in inst),
            "distance_source": "road_cache" if inst and all(
                i.m.source == "road_cache" for i in inst) else "estimate",
            "policies": {name: summarise(rows) for name, rows in per.items()},
            "d_vs_a_saving_bdt_per_instance": {
                "mean": round(float(np.mean(saving)), 2) if saving else 0.0,
                "p5": round(float(np.percentile(saving, 5)), 2) if saving else 0.0,
                "p95": round(float(np.percentile(saving, 95)), 2) if saving else 0.0}}


def main() -> None:
    from app.core.config import get_settings
    from app.services import van_geometry

    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=get_settings().seed)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = run(args.seed, VanConfig(), van_geometry.load().legs)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "config"}, indent=1))


if __name__ == "__main__":
    main()
