"""Sensitivity of policies A, C and D on one seed (synthetic data, estimate distances):
road factor and fuel cost per km re-solve every instance; delivery reliability replays the base
plans with seeded failed deliveries (the same agents fail under every policy).

A failed delivery leaves the agent stocked out from its expected stockout until the horizon, as
if it had been skipped: its lateness cost is replaced by its skip penalty.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from app.rules.van_routing.cost import EPS, due_h, skip_penalty
from app.rules.van_routing.models import Solution, Stop, VanConfig
from ml.data_gen.dataset import Dataset
from ml.van import backtest
from ml.van.baselines import POLICIES

COMPARED = ("A_separate_trips", "C_hard_deadline", "D_full_model")
FACTORS: dict[str, tuple[float, ...]] = {"road_factor": (1.2, 1.5),
                                         "cost_per_km_bdt": (20.0, 30.0)}
RELIABILITY = (0.9, 0.95)


def _brief(rows: list[dict[str, Any]]) -> dict[str, float]:
    s = backtest.summarise(rows)
    return {k: float(s[k]) for k in ("total_bdt", "van_bdt", "km", "stockout_h",
                                      "service_rate", "deadline_hit_rate")}


def _solve(inst: Sequence[backtest.Instance], cfg: VanConfig, seed: int
           ) -> dict[str, list[Solution]]:
    return {name: [POLICIES[name](i.stops, i.m, cfg, seed * 1000 + k)
                   for k, i in enumerate(inst)] for name in COMPARED}


def _unreliable(sol: Solution, stops: list[Stop], cfg: VanConfig, r: float, seed: int,
                k: int) -> dict[str, Any]:
    row = backtest.measure(sol, stops, cfg)
    for route in sol.routes:
        for v in route.visits:
            s = stops[v.stop]
            u = np.random.default_rng([seed, k, s.agent_id]).random()
            if u <= r:
                continue
            row["total_bdt"] += skip_penalty(s, cfg) - v.late_penalty_bdt
            row["lost_value_bdt"] += skip_penalty(s, cfg) - v.late_penalty_bdt
            row["stockout_h"] += max(cfg.horizon_h - due_h(s), 0.0) - v.late_h
            row["served"] -= 1
            row["on_time"] -= v.late_h <= EPS
    return row


def run(seed: int, cfg: VanConfig, ds: Dataset) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for factor, values in FACTORS.items():
        for value in values:
            c = replace(cfg, **{factor: value})
            inst = [i for i in backtest.instances(ds, c, {}) if i.stops]
            sols = _solve(inst, c, seed)
            rows.append({"factor": factor, "value": value, "policies": {
                name: _brief([backtest.measure(x, i.stops, c)
                              for x, i in zip(s, inst, strict=True)])
                for name, s in sols.items()}})
    inst = [i for i in backtest.instances(ds, cfg, {}) if i.stops]
    sols = _solve(inst, cfg, seed)
    for r in RELIABILITY:
        rows.append({"factor": "delivery_reliability", "value": r, "policies": {
            name: _brief([_unreliable(x, i.stops, cfg, r, seed, k)
                          for k, (x, i) in enumerate(zip(s, inst, strict=True))])
            for name, s in sols.items()}})
    return rows
