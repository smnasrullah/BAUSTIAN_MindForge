"""Van route optimizer: OR-Tools capacitated routing with soft deadlines and optional stops.

Pure and deterministic (same inputs -> same plan): one search thread and a fixed solution budget;
the time limit is only a safety net and, when it is what stopped the search, the result says so.
Falls back to nearest-neighbour + 2-opt (solver "fallback") when OR-Tools cannot be imported or
finds no solution. All reported numbers are recomputed by cost.py from the final routes.

solve(): the search alone (policy C in hard mode). plan(): the full model (policy D and the served
plan): soft windows, then the fairness guard, then a seeded near-optimal order (safety).
Route index k is always van k + 1, so a stop locked to a van keeps that van number.
"""

import time
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from app.rules.van_routing import fairness, safety
from app.rules.van_routing import heuristics as h
from app.rules.van_routing.cost import classify, drop_cost, due_h, evaluate, objective
from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import Solution, SolverName, Stop, VanConfig, WindowMode

SCALE = 100  # OR-Tools needs integer costs: 1 unit = 0.01 BDT
SEARCH_SHARE = 0.85  # of the time limit; the rest is left for repair, reasons and costs


def solve(stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
          mode: WindowMode = "soft") -> Solution:
    """mode "soft": late arrivals cost lost value (full model); "hard": no late arrival at all
    (policy C), a stop that cannot make its deadline is dropped."""
    t0 = time.perf_counter()
    if not stops:
        return finish([], [], stops, m, cfg, mode, "ortools", "empty", t0)
    seqs, dropped, solver, stopped_by, notes = _search(stops, m, cfg, mode)
    return finish(seqs, dropped, stops, m, cfg, mode, solver, stopped_by, t0, notes)


def plan(stops: Sequence[Stop], m: Matrix, cfg: VanConfig, seed: int = 0) -> Solution:
    """The full model: solve (soft), lift groups under the service bound, then pick a seeded
    order among those within near_optimal_pct of the best cost."""
    t0 = time.perf_counter()
    if not stops:
        return finish([], [], stops, m, cfg, "soft", "ortools", "empty", t0)
    seqs, dropped, solver, stopped_by, notes = _search(stops, m, cfg, "soft")
    forced, short = fairness.enforce(seqs, dropped, stops, m, cfg)
    seqs, choice = safety.near_optimal(seqs, stops, m, cfg, seed)
    sol = finish(seqs, dropped, stops, m, cfg, "soft", solver, stopped_by, t0, notes)
    return replace(sol, forced=tuple(forced), fairness_short=tuple(short), choice=choice)


def _search(stops: Sequence[Stop], m: Matrix, cfg: VanConfig, mode: WindowMode
            ) -> tuple[list[list[int]], list[int], SolverName, str, tuple[str, ...]]:
    notes: tuple[str, ...] = ()
    try:
        found = _ortools(stops, m, cfg, mode)
    except ImportError:
        found, notes = None, ("ortools_unavailable",)
    solver: SolverName
    if found is None:
        seqs, dropped = h.fallback(stops, m, cfg, mode)
        solver, stopped_by = "fallback", "heuristic"
        notes = notes or ("ortools_no_solution",)
    else:
        (seqs, dropped, stopped_by), solver = found, "ortools"
    h.repair(seqs, dropped, stops, m, cfg, mode)
    return seqs, dropped, solver, stopped_by, notes


def finish(seqs: Sequence[Sequence[int]], dropped: Sequence[int], stops: Sequence[Stop],
           m: Matrix, cfg: VanConfig, mode: WindowMode, solver: SolverName, stopped_by: str,
           t0: float, notes: tuple[str, ...] = ()) -> Solution:
    lists = [list(s) for s in seqs]
    routes = tuple(evaluate(n + 1, s, stops, m, cfg) for n, s in enumerate(lists) if s)
    drops = classify(sorted(dropped), lists, stops, m, cfg, mode)
    return Solution(routes=routes, drops=drops, objective=objective(routes, drops, cfg),
                    solver=solver, stopped_by=stopped_by,
                    solve_ms=(time.perf_counter() - t0) * 1000, notes=notes)


def _ortools(stops: Sequence[Stop], m: Matrix, cfg: VanConfig, mode: WindowMode
             ) -> tuple[list[list[int]], list[int], str] | None:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    n = len(stops) + 1
    service = [0.0] + [cfg.minutes_per_stop] * len(stops)
    per_min = cfg.cost_per_hour_bdt / 60
    cost = [[round((m.km[i][j] * cfg.cost_per_km_bdt + (m.minutes[i][j] + service[i]) * per_min)
                   * SCALE) for j in range(n)] for i in range(n)]
    secs = [[round((m.minutes[i][j] + service[i]) * 60) for j in range(n)] for i in range(n)]
    demand = [0] + [round(s.amount_bdt) for s in stops]

    manager = pywrapcp.RoutingIndexManager(n, cfg.vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    # Native matrices (no Python callbacks): about 10x more search steps per second.
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitMatrix(cost))
    routing.SetFixedCostOfAllVehicles(round(cfg.fixed_trip_bdt * SCALE))
    routing.AddDimensionWithVehicleCapacity(routing.RegisterUnaryTransitVector(demand), 0,
                                            [int(cfg.load_cap_bdt)] * cfg.vehicles, True, "cash")
    routing.AddDimension(routing.RegisterTransitMatrix(secs), 0, round(cfg.shift_h * 3600), True,
                         "time")
    clock: Any = routing.GetDimensionOrDie("time")
    wait_s = round(cfg.max_wait_h * 3600)  # fairness guard: no arrival after the max wait
    for i, s in enumerate(stops):
        index = manager.NodeToIndex(i + 1)
        due_s = round(due_h(s) * 3600)
        if mode == "hard":
            clock.CumulVar(index).SetMax(min(due_s, wait_s))
        else:
            clock.CumulVar(index).SetMax(wait_s)
            if s.lost_per_h_bdt > 0:
                per_s = max(1, round(s.lost_per_h_bdt / 3600 * SCALE))
                clock.SetCumulVarSoftUpperBound(index, due_s, per_s)
        if s.vehicle is not None and 1 <= s.vehicle <= cfg.vehicles:
            routing.VehicleVar(index).SetValues([-1, s.vehicle - 1])  # -1: left out
        routing.AddDisjunction([index], round(drop_cost(s, cfg) * SCALE))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    params.time_limit.FromMilliseconds(int(cfg.time_limit_s * SEARCH_SHARE * 1000))
    params.solution_limit = cfg.solution_limit
    t0 = time.perf_counter()
    sol = routing.SolveWithParameters(params)
    elapsed = time.perf_counter() - t0
    if sol is None:
        return None
    seqs: list[list[int]] = []
    for v in range(cfg.vehicles):
        seq: list[int] = []
        index = sol.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(index):
            seq.append(int(manager.IndexToNode(index)) - 1)
            index = sol.Value(routing.NextVar(index))
        seqs.append(seq)
    served = {i for seq in seqs for i in seq}
    dropped = [i for i in range(len(stops)) if i not in served]
    stopped_by = ("time_limit" if elapsed >= cfg.time_limit_s * SEARCH_SHARE * 0.95
                  else "solution_limit")
    return seqs, dropped, stopped_by
