"""The BDT objective: van cost (fixed + km + time) + lateness penalty + skip penalty.

This file is the single source of every reported number; the solvers only search. A late
arrival costs the agent's lost value for each hour after the expected stockout (soft window); a
skipped agent costs it until the planning horizon. Already-late agents (deadline <= 0) count
from departure.
"""

from collections.abc import Sequence

from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import (
    Drop,
    DropReason,
    Objective,
    Route,
    Stop,
    VanConfig,
    Visit,
    WindowMode,
)

EPS = 1e-6
MUST_SERVE_BDT = 100_000_000.0  # search-only price of dropping a locked/included stop


def due_h(s: Stop) -> float:
    return max(s.deadline_h, 0.0)


def skip_penalty(s: Stop, cfg: VanConfig) -> float:
    return s.lost_per_h_bdt * max(cfg.horizon_h - due_h(s), 0.0)


def drop_cost(s: Stop, cfg: VanConfig) -> float:
    """What the search pays for leaving a stop out; reported numbers use skip_penalty."""
    return MUST_SERVE_BDT if s.must_serve else skip_penalty(s, cfg)


def late_penalty(s: Stop, arrival_h: float) -> float:
    return s.lost_per_h_bdt * max(arrival_h - due_h(s), 0.0)


def evaluate(vehicle_no: int, seq: Sequence[int], stops: Sequence[Stop], m: Matrix,
             cfg: VanConfig) -> Route:
    """Depot -> stops in order -> depot. Arrival is before the stop's service minutes."""
    km = minutes = load = 0.0
    prev = 0
    visits: list[Visit] = []
    for i in seq:
        node = i + 1
        km += m.km[prev][node]
        minutes += m.minutes[prev][node]
        arrival = minutes / 60
        s = stops[i]
        visits.append(Visit(stop=i, arrival_h=arrival, late_h=max(arrival - due_h(s), 0.0),
                            late_penalty_bdt=late_penalty(s, arrival)))
        minutes += cfg.minutes_per_stop
        load += s.amount_bdt
        prev = node
    km += m.km[prev][0]
    minutes += m.minutes[prev][0]
    cost = van_cost(km, minutes, cfg) if seq else 0.0
    return Route(vehicle_no=vehicle_no, visits=tuple(visits), km=km, minutes=minutes,
                 cash_load_bdt=load, cost_bdt=cost)


def van_cost(km: float, minutes: float, cfg: VanConfig) -> float:
    return cfg.fixed_trip_bdt + km * cfg.cost_per_km_bdt + minutes / 60 * cfg.cost_per_hour_bdt


def route_total(r: Route) -> float:
    return r.cost_bdt + sum(v.late_penalty_bdt for v in r.visits)


def fits(r: Route, cfg: VanConfig, mode: WindowMode = "soft") -> bool:
    if r.cash_load_bdt > cfg.load_cap_bdt + EPS or r.minutes > cfg.shift_h * 60 + EPS:
        return False
    if any(v.arrival_h > cfg.max_wait_h + EPS for v in r.visits):
        return False
    return mode == "soft" or all(v.late_h <= EPS for v in r.visits)


def cheapest_insertion(i: int, seqs: Sequence[Sequence[int]], stops: Sequence[Stop], m: Matrix,
                       cfg: VanConfig, mode: WindowMode = "soft"
                       ) -> tuple[float, int, int] | None:
    """(extra BDT, route index, position) of the cheapest feasible insertion; an unused van is
    route index len(seqs). Route index k is van k + 1, so a stop locked to a van only goes
    there. None when no van can take the stop."""
    best: tuple[float, int, int] | None = None
    options = list(seqs) + ([[]] if len(seqs) < cfg.vehicles else [])
    pinned = stops[i].vehicle
    for r_idx, seq in enumerate(options):
        if pinned is not None and r_idx + 1 != pinned:
            continue
        before = route_total(evaluate(0, seq, stops, m, cfg)) if seq else 0.0
        for pos in range(len(seq) + 1):
            cand = evaluate(0, [*seq[:pos], i, *seq[pos:]], stops, m, cfg)
            if not fits(cand, cfg, mode):
                continue
            extra = route_total(cand) - before
            if best is None or extra < best[0] - EPS:
                best = (extra, r_idx, pos)
    return best


def classify(dropped: Sequence[int], seqs: Sequence[Sequence[int]], stops: Sequence[Stop],
             m: Matrix, cfg: VanConfig, mode: WindowMode = "soft") -> tuple[Drop, ...]:
    """Every dropped stop gets a reason: no van can take it (capacity) or serving it would cost
    more than skipping it (cost_gt_value). Hard mode: a stop a van could take, only late, is
    deadline_missed."""
    out: list[Drop] = []
    for i in dropped:
        ins = cheapest_insertion(i, seqs, stops, m, cfg, mode)
        reason: DropReason = "cost_gt_value"
        if ins is None:
            on_late = mode == "hard" and cheapest_insertion(i, seqs, stops, m, cfg) is not None
            reason = "deadline_missed" if on_late else "capacity"
        out.append(Drop(stop=i, reason=reason,
                        skip_penalty_bdt=skip_penalty(stops[i], cfg),
                        insertion_cost_bdt=None if ins is None else ins[0]))
    return tuple(out)


def objective(routes: Sequence[Route], drops: Sequence[Drop], cfg: VanConfig) -> Objective:
    used = [r for r in routes if r.visits]
    return Objective(
        van_fixed_bdt=cfg.fixed_trip_bdt * len(used),
        van_km_bdt=sum(r.km for r in used) * cfg.cost_per_km_bdt,
        van_time_bdt=sum(r.minutes for r in used) / 60 * cfg.cost_per_hour_bdt,
        late_penalty_bdt=sum(v.late_penalty_bdt for r in used for v in r.visits),
        skip_penalty_bdt=sum(d.skip_penalty_bdt for d in drops))
