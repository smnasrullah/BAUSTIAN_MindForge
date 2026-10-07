import math

import pytest

from app.rules.swap_rules import haversine_km
from app.rules.van_routing import matrix
from app.rules.van_routing.cost import (
    classify,
    evaluate,
    late_penalty,
    objective,
    skip_penalty,
    van_cost,
)
from app.rules.van_routing.matrix import Point
from app.rules.van_routing.models import Stop, VanConfig
from tests.van_helpers import DEPOT, estimate, points, stops

CFG = VanConfig()


def test_cache_miss_is_labelled_estimate() -> None:
    s = stops(3)
    pts = points(s)
    full = {(a.key, b.key): (10.0, 30.0) for a in pts for b in pts if a is not b}
    assert matrix.build(pts, full, CFG).source == "road_cache"
    missing = dict(full)
    del missing[(pts[1].key, pts[2].key)]
    m = matrix.build(pts, missing, CFG)
    assert m.source == "estimate" and m.estimated_legs == 1
    assert (m.km[0][1], m.minutes[0][1], m.cached[0][1]) == (10.0, 30.0, True)
    est = haversine_km(pts[1].lat, pts[1].lng, pts[2].lat, pts[2].lng) * CFG.road_factor
    assert m.km[1][2] == pytest.approx(est) and not m.cached[1][2]
    assert m.minutes[1][2] == pytest.approx(est / CFG.speed_kmh * 60)


def test_day_factor_slows_the_leg() -> None:
    slow = Point("agent:9", DEPOT.lat + 0.05, DEPOT.lng, time_factor=1.5)
    plain = matrix.build([DEPOT, Point("agent:9", slow.lat, slow.lng)], {}, CFG)
    m = matrix.build([DEPOT, slow], {}, CFG)
    assert m.km == plain.km and m.minutes[0][1] == pytest.approx(plain.minutes[0][1] * 1.5)


def test_soft_window_penalty_is_applied() -> None:
    far = Stop(agent_id=1, lat=DEPOT.lat + 0.2, lng=DEPOT.lng, amount_bdt=50_000,
               deadline_h=0.25, lost_per_h_bdt=2_000)
    m = estimate([far], CFG)
    r = evaluate(1, [0], [far], m, CFG)
    (v,) = r.visits
    assert v.arrival_h == pytest.approx(m.minutes[0][1] / 60)
    assert v.late_h == pytest.approx(v.arrival_h - 0.25) and v.late_h > 0
    assert v.late_penalty_bdt == pytest.approx(2_000 * v.late_h)
    assert v.late_penalty_bdt == pytest.approx(late_penalty(far, v.arrival_h))
    obj = objective([r], [], CFG)
    assert obj.late_penalty_bdt == pytest.approx(v.late_penalty_bdt)
    assert obj.total_bdt == pytest.approx(r.cost_bdt + v.late_penalty_bdt)


def test_van_cost_and_skip_penalty_units() -> None:
    s = Stop(agent_id=1, lat=0, lng=0, amount_bdt=1, deadline_h=-3, lost_per_h_bdt=1_000)
    # Already stocked out: skipping costs the whole horizon.
    assert skip_penalty(s, CFG) == pytest.approx(1_000 * CFG.horizon_h)
    assert van_cost(10, 60, CFG) == pytest.approx(
        CFG.fixed_trip_bdt + 10 * CFG.cost_per_km_bdt + CFG.cost_per_hour_bdt)
    route = evaluate(1, [], [s], estimate([s], CFG), CFG)
    assert route.cost_bdt == 0 and route.km == 0


def test_drop_reasons() -> None:
    cfg = VanConfig(cash_cap_bdt=100_000)
    big = Stop(agent_id=1, lat=DEPOT.lat, lng=DEPOT.lng + 0.01, amount_bdt=150_000,
               deadline_h=2, lost_per_h_bdt=5_000)
    free = Stop(agent_id=2, lat=DEPOT.lat, lng=DEPOT.lng + 0.02, amount_bdt=10_000,
                deadline_h=2, lost_per_h_bdt=0)
    m = estimate([big, free], cfg)
    by = {d.stop: d for d in classify([0, 1], [], [big, free], m, cfg)}
    assert by[0].reason == "capacity" and by[0].insertion_cost_bdt is None
    assert by[1].reason == "cost_gt_value" and by[1].skip_penalty_bdt == 0
    assert by[1].insertion_cost_bdt is not None and by[1].insertion_cost_bdt > 0


def test_config_rejects_bad_values() -> None:
    for bad in ({"vehicles": 0}, {"capacity_bdt": 0}, {"road_factor": 0.9},
                {"cost_per_km_bdt": -1}, {"solution_limit": 0}):
        with pytest.raises(ValueError):
            VanConfig(**bad)  # type: ignore[arg-type]
    assert VanConfig(capacity_bdt=5, cash_cap_bdt=3).load_cap_bdt == 3
    assert not math.isnan(VanConfig().load_cap_bdt)
