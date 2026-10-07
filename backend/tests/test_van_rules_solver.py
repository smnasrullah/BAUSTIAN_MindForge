import sys

import pytest

from app.rules.van_routing import heuristics, solver
from app.rules.van_routing.cost import EPS, fits
from app.rules.van_routing.models import Solution, Stop, VanConfig
from tests.van_helpers import DEPOT, estimate, stops

CFG = VanConfig(time_limit_s=5)
REASONS = {"cost_gt_value", "capacity"}


def _served(sol: Solution) -> list[int]:
    return [v.stop for r in sol.routes for v in r.visits]


def _check(sol: Solution, n: int, cfg: VanConfig) -> None:
    served, dropped = _served(sol), [d.stop for d in sol.drops]
    assert sorted(served + dropped) == list(range(n)), "every stop is served xor dropped"
    assert all(d.reason in REASONS for d in sol.drops)
    assert len(sol.routes) <= cfg.vehicles
    for r in sol.routes:
        assert r.cash_load_bdt <= cfg.load_cap_bdt + EPS
        assert r.cash_load_bdt <= cfg.cash_cap_bdt + EPS
        assert r.minutes <= cfg.shift_h * 60 + EPS
        assert fits(r, cfg)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_stop_served_or_dropped_with_reason(seed: int) -> None:
    s = stops(25, seed=seed)
    sol = solver.solve(s, estimate(s, CFG), CFG)
    assert sol.solver == "ortools"
    _check(sol, 25, CFG)


def test_capacity_and_cash_cap_hold() -> None:
    cfg = VanConfig(vehicles=2, capacity_bdt=600_000, cash_cap_bdt=400_000, time_limit_s=5)
    s = stops(20, seed=4, amount=(50_000, 150_000))
    s.append(Stop(agent_id=99, lat=DEPOT.lat, lng=DEPOT.lng + 0.01, amount_bdt=450_000,
                  deadline_h=1, lost_per_h_bdt=50_000))
    sol = solver.solve(s, estimate(s, cfg), cfg)
    _check(sol, 21, cfg)
    assert sum(x.amount_bdt for x in s) > 2 * cfg.load_cap_bdt
    assert any(d.reason == "capacity" for d in sol.drops)
    assert {d.stop: d.reason for d in sol.drops}[20] == "capacity"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_optimised_cost_not_above_separate_trips(seed: int) -> None:
    s = stops(20, seed=seed)
    m = estimate(s, CFG)
    best = solver.solve(s, m, CFG)
    seqs, dropped = heuristics.separate_trips(s, m, CFG)
    base = solver.finish(seqs, dropped, s, m, CFG, "soft", "separate_trips", "heuristic", 0.0)
    assert best.objective.total_bdt <= base.objective.total_bdt + EPS
    assert best.objective.van_bdt < base.objective.van_bdt


def test_deterministic_for_fixed_input() -> None:
    s = stops(30, seed=5)
    m = estimate(s, CFG)
    a, b = solver.solve(s, m, CFG), solver.solve(s, m, CFG)
    assert (a.routes, a.drops, a.objective) == (b.routes, b.drops, b.objective)
    assert a.stopped_by == "solution_limit"


def test_empty_single_and_infeasible() -> None:
    empty = solver.solve([], estimate([], CFG), CFG)
    assert (empty.routes, empty.drops, empty.objective.total_bdt) == ((), (), 0)
    one = stops(1)
    sol = solver.solve(one, estimate(one, CFG), CFG)
    assert _served(sol) == [0] and sol.trips == 1
    late = [Stop(agent_id=1, lat=DEPOT.lat + 0.05, lng=DEPOT.lng, amount_bdt=10_000,
                 deadline_h=-2, lost_per_h_bdt=3_000)]
    sol = solver.solve(late, estimate(late, CFG), CFG)
    assert _served(sol) == [0] and sol.objective.late_penalty_bdt > 0
    tiny = VanConfig(capacity_bdt=1_000, time_limit_s=5)
    s = stops(5)
    sol = solver.solve(s, estimate(s, tiny), tiny)
    assert sol.routes == () and {d.reason for d in sol.drops} == {"capacity"}


def test_hard_deadlines_drop_late_stops() -> None:
    s = stops(15, seed=6, deadline=(-1.0, 3.0))
    m = estimate(s, CFG)
    hard = solver.solve(s, m, CFG, mode="hard")
    assert all(v.late_h <= EPS for r in hard.routes for v in r.visits)
    assert any(d.reason == "deadline_missed" for d in hard.drops)
    soft = solver.solve(s, m, CFG)
    assert len(_served(soft)) >= len(_served(hard))


def test_solve_finishes_under_time_limit() -> None:
    cfg = VanConfig(time_limit_s=3)
    s = stops(60, seed=8)
    sol = solver.solve(s, estimate(s, cfg), cfg)
    assert sol.solve_ms < cfg.time_limit_s * 1000
    _check(sol, 60, cfg)


def test_fallback_when_ortools_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ortools", "ortools.constraint_solver"):
        monkeypatch.setitem(sys.modules, name, None)
    s = stops(20, seed=2)
    m = estimate(s, CFG)
    sol = solver.solve(s, m, CFG)
    assert (sol.solver, sol.stopped_by, sol.notes) == ("fallback", "heuristic",
                                                       ("ortools_unavailable",))
    _check(sol, 20, CFG)
    seqs, dropped = heuristics.separate_trips(s, m, CFG)
    base = solver.finish(seqs, dropped, s, m, CFG, "soft", "separate_trips", "heuristic", 0.0)
    assert sol.objective.total_bdt <= base.objective.total_bdt + EPS
