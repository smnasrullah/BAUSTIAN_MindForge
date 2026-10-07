"""Van rules, should stage: fairness bounds, near-optimal seeded pick, pins and freeze, ETA range
and stockout curve (pure, no database)."""

import sys
from dataclasses import replace

import pytest

from app.rules.van_routing import fairness, heuristics, robust, safety, solver, stability
from app.rules.van_routing.cost import EPS, evaluate, fits, route_total
from app.rules.van_routing.models import Solution, Stop, VanConfig
from app.rules.van_routing.stability import Pin
from tests.van_helpers import DEPOT, estimate, stops

CFG = VanConfig(time_limit_s=5)


def _served(sol: Solution) -> list[int]:
    return [v.stop for r in sol.routes for v in r.visits]


def _total(seqs: list[list[int]], s: list[Stop], cfg: VanConfig) -> float:
    m = estimate(s, cfg)
    return sum(route_total(evaluate(0, q, s, m, cfg)) for q in seqs if q)


def _far_rural(n: int) -> list[Stop]:
    """Rural agents far out with little value: plain cost-benefit would skip them."""
    return [Stop(agent_id=100 + k, lat=DEPOT.lat + 0.25 + 0.01 * k, lng=DEPOT.lng + 0.2,
                 amount_bdt=20_000, deadline_h=6.0, lost_per_h_bdt=10, group="rural/tier3")
            for k in range(n)]


def test_fairness_guard_lifts_a_skipped_group() -> None:
    urban = [replace(x, group="urban/tier1") for x in stops(10, seed=3)]
    s = urban + _far_rural(4)
    m = estimate(s, CFG)
    plain = solver.solve(s, m, CFG)
    rural = {i for i, x in enumerate(s) if fairness.area(x) == "rural"}
    assert not rural & set(_served(plain)), "cost-benefit alone skips the rural agents"
    sol = solver.plan(s, m, CFG)
    report = {g["group"]: g for g in fairness.report(sol, s, CFG)}
    assert report["rural"]["service_rate"] >= CFG.min_service_rate and report["rural"]["ok"]
    assert set(sol.forced) <= rural and len(sol.forced) >= 2 and not sol.fairness_short
    assert all(g["max_wait_h"] <= CFG.max_wait_h + EPS for g in report.values())


def test_fairness_reports_a_group_no_van_can_reach() -> None:
    cfg = replace(CFG, max_wait_h=1.0)  # the rural cluster is about 1.5 h away
    s = [replace(x, group="urban/tier1") for x in stops(6, seed=2)] + _far_rural(2)
    sol = solver.plan(s, estimate(s, cfg), cfg)
    assert "rural" in sol.fairness_short
    report = {g["group"]: g for g in fairness.report(sol, s, cfg)}
    assert report["rural"]["served"] == 0 and not report["rural"]["ok"]
    assert all(v.arrival_h <= cfg.max_wait_h + EPS for r in sol.routes for v in r.visits)


def test_max_wait_is_a_hard_bound() -> None:
    cfg = replace(CFG, max_wait_h=1.0, min_service_rate=0.0)
    s = stops(25, seed=9)
    for sol in (solver.solve(s, estimate(s, cfg), cfg), solver.plan(s, estimate(s, cfg), cfg)):
        assert all(v.arrival_h <= 1.0 + EPS for r in sol.routes for v in r.visits)


def test_near_optimal_pick_is_seeded_and_within_tolerance() -> None:
    s = stops(20, seed=4, deadline=(20.0, 23.0))  # no lateness: a reversed route costs the same
    m = estimate(s, CFG)
    best = solver.solve(s, m, CFG)
    seqs = [[v.stop for v in r.visits] for r in best.routes]
    picks = {safety.near_optimal(seqs, s, m, CFG, k)[1] for k in range(30)}
    assert len(picks) > 1, "different seeds can pick different near-optimal orders"
    a = solver.plan(s, m, CFG, seed=7)
    b = solver.plan(s, m, CFG, seed=7)
    assert (a.routes, a.drops, a.objective, a.choice) == (b.routes, b.drops, b.objective,
                                                          b.choice)
    for k in range(10):
        chosen, _ = safety.near_optimal(seqs, s, m, CFG, k)
        assert _total(chosen, s, CFG) <= _total(seqs, s, CFG) * (1 + CFG.near_optimal_pct) + EPS
        assert sorted(i for q in chosen for i in q) == sorted(i for q in seqs for i in q)
        assert all(fits(evaluate(0, q, s, m, CFG), CFG) for q in chosen if q)


def test_zero_tolerance_keeps_the_best_cost() -> None:
    cfg = replace(CFG, near_optimal_pct=0.0, min_service_rate=0.0)
    s = stops(15, seed=6)
    m = estimate(s, cfg)
    assert solver.plan(s, m, cfg, seed=3).objective.total_bdt <= \
        solver.solve(s, m, cfg).objective.total_bdt + EPS


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_full_model_not_above_separate_trips(seed: int) -> None:
    s = stops(20, seed=seed)
    m = estimate(s, CFG)
    sol = solver.plan(s, m, CFG, seed)
    seqs, dropped = heuristics.separate_trips(s, m, CFG)
    base = solver.finish(seqs, dropped, s, m, CFG, "soft", "separate_trips", "heuristic", 0.0)
    assert sol.objective.total_bdt <= base.objective.total_bdt + EPS
    for r in sol.routes:
        assert r.cash_load_bdt <= CFG.load_cap_bdt + EPS


def test_pins_lock_include_exclude() -> None:
    s = stops(12, seed=5)
    lock_id, incl_id, excl_id = s[0].agent_id, s[1].agent_id, s[2].agent_id
    pins = {lock_id: Pin("lock", 2), incl_id: Pin("include"), excl_id: Pin("exclude")}
    applied = stability.apply(s, pins, {}, CFG.vehicles)
    assert applied.excluded == [2] and 2 not in applied.index
    sol = solver.plan(applied.stops, estimate(applied.stops, CFG), CFG)
    van = {applied.stops[v.stop].agent_id: r.vehicle_no for r in sol.routes for v in r.visits}
    assert van[lock_id] == 2 and incl_id in van and excl_id not in van


def test_include_beats_cost_but_not_capacity() -> None:
    cheap = Stop(agent_id=1, lat=DEPOT.lat + 0.3, lng=DEPOT.lng + 0.3, amount_bdt=10_000,
                 deadline_h=20, lost_per_h_bdt=1)
    huge = Stop(agent_id=2, lat=DEPOT.lat, lng=DEPOT.lng + 0.01, amount_bdt=9_000_000,
                deadline_h=1, lost_per_h_bdt=1)
    applied = stability.apply([cheap, huge], {1: Pin("include"), 2: Pin("include")}, {}, 2)
    sol = solver.plan(applied.stops, estimate(applied.stops, CFG), CFG)
    assert _served(sol) == [0]
    assert {d.stop: d.reason for d in sol.drops} == {1: "capacity"}


def test_frozen_stops_keep_their_van_over_pins() -> None:
    assert stability.frozen([(1, 2, 0.2), (2, 1, 0.9), (3, 1, -0.1)], 0.5) == {1: 2}
    s = stops(8, seed=1)
    applied = stability.apply(s, {s[0].agent_id: Pin("exclude")}, {s[0].agent_id: 2}, 2)
    assert applied.frozen == [0] and applied.excluded == []
    assert applied.stops[0].must_serve and applied.stops[0].vehicle == 2
    gone = stability.apply(s, {}, {s[1].agent_id: 5}, 2)  # van 5 no longer in the fleet
    assert gone.stops[1].must_serve and gone.stops[1].vehicle is None


def test_pins_hold_in_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ortools", "ortools.constraint_solver"):
        monkeypatch.setitem(sys.modules, name, None)
    s = stops(15, seed=8)
    applied = stability.apply(s, {s[3].agent_id: Pin("lock", 2)}, {}, CFG.vehicles)
    sol = solver.plan(applied.stops, estimate(applied.stops, CFG), CFG)
    assert sol.solver == "fallback"
    assert any(r.vehicle_no == 2 and any(v.stop == 3 for v in r.visits) for r in sol.routes)


def test_eta_range_and_stockout_curve() -> None:
    s = stops(6, seed=2)
    m = estimate(s, CFG)
    sol = solver.solve(s, m, CFG)
    for r in sol.routes:
        for v, (lo, hi) in zip(r.visits, robust.eta_range(r, m, CFG), strict=True):
            assert lo < v.arrival_h < hi
    curve = [0.0, 0.2, 0.6, 1.0]
    assert robust.p_at(curve, 1.5) == pytest.approx(0.4)
    assert robust.p_at(curve, 9.0) == 1.0 and robust.p_at(curve, -1.0) == 0.0
    assert robust.p_crossing(curve, 0.4) == pytest.approx(1.5)
    assert robust.p_crossing(curve, 0.0) == 0.0 and robust.p_crossing([0.1, 0.2], 0.5) is None
