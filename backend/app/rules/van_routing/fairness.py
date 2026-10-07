"""Fairness guard: per area group (urban / peri_urban / rural) a maximum wait and a minimum
service rate.

The wait bound is a hard limit inside every route (cost.fits, solver time windows). The service
bound is enforced after the search: while a group is below it, the dropped stop of that group
that is cheapest to add (insertion cost minus its value) is inserted; a group no van can lift is
reported as short. Both bounds and the service rate per group are reported with the plan.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from app.rules.van_routing.cost import EPS, cheapest_insertion, skip_penalty
from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import Solution, Stop, VanConfig

Seqs = list[list[int]]


def area(s: Stop) -> str:
    return s.group.split("/")[0] or "all"


def _below(seqs: Seqs, stops: Sequence[Stop], cfg: VanConfig) -> list[str]:
    served = {i for seq in seqs for i in seq}
    count: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for i, s in enumerate(stops):
        count[area(s)][0] += 1
        count[area(s)][1] += i in served
    return sorted(g for g, (n, k) in count.items() if k / n < cfg.min_service_rate - EPS)


def enforce(seqs: Seqs, dropped: list[int], stops: Sequence[Stop], m: Matrix,
            cfg: VanConfig) -> tuple[list[int], list[str]]:
    """Insert stops until every group meets the service bound (in place).
    Returns (stops inserted by the guard, groups that stay short)."""
    forced: list[int] = []
    short: set[str] = set()
    while todo := [g for g in _below(seqs, stops, cfg) if g not in short]:
        group = todo[0]
        best: tuple[tuple[float, int], tuple[float, int, int]] | None = None
        for i in sorted(dropped):
            if area(stops[i]) != group:
                continue
            ins = cheapest_insertion(i, seqs, stops, m, cfg)
            if ins is None:
                continue
            key = (ins[0] - skip_penalty(stops[i], cfg), i)
            if best is None or key < best[0]:
                best = (key, ins)
        if best is None:
            short.add(group)
            continue
        (_, i), (_, r_idx, pos) = best
        if r_idx == len(seqs):
            seqs.append([])
        seqs[r_idx].insert(pos, i)
        dropped.remove(i)
        forced.append(i)
    return forced, sorted(short)


def report(sol: Solution, stops: Sequence[Stop], cfg: VanConfig) -> list[dict[str, Any]]:
    """Service rate and longest wait per area group, against the bounds."""
    rows: dict[str, dict[str, Any]] = {}
    for s in stops:
        row = rows.setdefault(area(s), {"needed": 0, "served": 0, "max_wait_h": 0.0})
        row["needed"] += 1
    for r in sol.routes:
        for v in r.visits:
            row = rows[area(stops[v.stop])]
            row["served"] += 1
            row["max_wait_h"] = max(row["max_wait_h"], v.arrival_h)
    out: list[dict[str, Any]] = []
    for g, row in sorted(rows.items()):
        rate = row["served"] / row["needed"]
        out.append({"group": g, "needed": row["needed"], "served": row["served"],
                    "service_rate": round(rate, 4), "max_wait_h": round(row["max_wait_h"], 3),
                    "min_service_rate": cfg.min_service_rate, "max_wait_bound_h": cfg.max_wait_h,
                    "ok": rate >= cfg.min_service_rate - EPS
                    and row["max_wait_h"] <= cfg.max_wait_h + EPS})
    return out
