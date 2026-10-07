"""Van plans: solved on demand for one distributor (never inside the hourly tick), cached by
input hash, persisted for a human decision. Advisory: nothing here moves money.

Inputs: app/services/van_inputs.py. Optimizer: app/rules/van_routing (pure). Road distances:
app/services/van_geometry.py. Storage: app/services/van_plan_store.py.
Spec: docs/VAN_ROUTING_SPEC.md (core + should stage).
"""

import hashlib
import json
import time
from dataclasses import asdict, replace
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings, get_settings
from app.models import Distributor, User, VanPlan, VanRoute, VanStop
from app.rules.van_routing import heuristics, matrix, solver, stability
from app.rules.van_routing.matrix import Point
from app.rules.van_routing.models import Stop, VanConfig
from app.rules.van_routing.stability import Pin
from app.schemas.van_plan import VanPlanCreate, VanPlanOut
from app.services import van_geometry, van_inputs, van_plan_store
from app.services.forecast import _utc
from app.services.van_inputs import Inputs
from app.services.van_plan_read import VanPlanError, detail

RULES_VERSION = "van-rules-2"


def config(s: Settings, body: VanPlanCreate, horizon_h: int) -> VanConfig:
    v = body.vehicles
    return VanConfig(
        vehicles=v.count or s.van_count, capacity_bdt=v.capacity_bdt or s.van_capacity_bdt,
        cash_cap_bdt=v.cash_cap_bdt or s.van_cash_cap_bdt, shift_h=s.van_shift_h,
        cost_per_km_bdt=s.van_cost_per_km_bdt, cost_per_hour_bdt=s.van_cost_per_hour_bdt,
        fixed_trip_bdt=s.van_cost_per_trip_bdt, minutes_per_stop=s.van_minutes_per_stop,
        speed_kmh=s.van_speed_kmh, road_factor=s.van_road_factor, horizon_h=float(horizon_h),
        time_limit_s=body.options.time_limit_s or s.van_time_limit_s,
        solution_limit=s.van_solution_limit, max_wait_h=s.van_fair_max_wait_h,
        min_service_rate=s.van_fair_min_service_rate, near_optimal_pct=s.van_near_optimal_pct,
        eta_lo_factor=s.van_eta_lo_factor, eta_hi_factor=s.van_eta_hi_factor)


def pins_from(raw: dict[str, Any]) -> dict[int, Pin]:
    return {int(k): Pin(v["action"], v.get("vehicle_no")) for k, v in raw.items()}


def pins_json(pins: dict[int, Pin]) -> dict[str, dict[str, Any]]:
    return {str(k): asdict(p) for k, p in sorted(pins.items())}


def _frozen(session: Session, distributor: Distributor, s: Settings) -> dict[int, int]:
    """Agent id -> van number for the open stops of the latest approved plan that its van
    reaches within the freeze window."""
    approved = session.scalar(select(VanPlan.id).where(
        VanPlan.distributor_id == distributor.id, VanPlan.status == "approved")
        .order_by(VanPlan.decided_at.desc(), VanPlan.id.desc()))
    if approved is None:
        return {}
    now = clock.now()
    rows = session.execute(
        select(VanStop.agent_id, VanRoute.vehicle_no, VanStop.eta_lo)
        .join(VanRoute, VanRoute.id == VanStop.route_id)
        .where(VanStop.plan_id == approved, VanStop.status == "planned")).tuples().all()
    planned = [(a, int(v), (_utc(eta) - now).total_seconds() / 3600)
               for a, v, eta in rows if eta is not None]
    return stability.frozen(planned, s.van_freeze_min / 60)


def _hash(d: Distributor, inputs: Inputs, cfg: VanConfig, cache_version: str,
          pins: dict[int, Pin], frozen: dict[int, int], limit: float) -> str:
    doc = {"distributor": d.id, "origin": inputs.origin.isoformat(),
           "hour": clock.hour_floor(inputs.now).isoformat(), "config": asdict(cfg),
           "stops": inputs.fingerprint(), "road_cache": cache_version, "rules": RULES_VERSION,
           "pins": pins_json(pins), "frozen": sorted(frozen.items()), "p_limit": limit}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def create(session: Session, user: User, body: VanPlanCreate,
           pins: dict[int, Pin] | None = None) -> VanPlanOut:
    distributor = (None if user.distributor_id is None
                   else session.get(Distributor, user.distributor_id))
    if distributor is None:
        raise VanPlanError("forbidden")
    s = get_settings()
    pins = pins or {}
    horizon = body.horizon_h or s.van_horizon_h
    inputs = van_inputs.gather(session, distributor, horizon, s, clock.now())
    cfg = config(s, body, horizon)
    cache = van_geometry.load()
    frozen = _frozen(session, distributor, s)
    limit = s.van_stockout_p_limit
    input_hash = _hash(distributor, inputs, cfg, cache.version, pins, frozen, limit)
    same = session.scalar(select(VanPlan).where(
        VanPlan.distributor_id == distributor.id, VanPlan.input_hash == input_hash,
        VanPlan.status == "pending").order_by(VanPlan.id.desc()))
    if same is not None:
        return detail(session, same, reused=True)
    applied = stability.apply(
        [Stop(agent_id=c.agent.id, lat=c.agent.lat, lng=c.agent.lng, amount_bdt=c.amount_bdt,
              deadline_h=c.deadline_h, lost_per_h_bdt=c.lost_per_h_bdt,
              district=c.agent.district, group=van_plan_store.group(c))
         for c in inputs.routable], pins, frozen, cfg.vehicles)
    cands = [inputs.routable[i] for i in applied.index]
    points = [Point(van_geometry.depot_key(distributor.code), distributor.hub_lat,
                    distributor.hub_lng)]
    points += [Point(van_geometry.agent_key(c.agent.code), c.agent.lat, c.agent.lng,
                     c.time_factor) for c in cands]
    m = matrix.build(points, cache.legs, cfg)
    seed = int(input_hash[:8], 16)  # same inputs -> same near-optimal pick
    sol = solver.plan(applied.stops, m, cfg, seed)
    plain = [replace(x, must_serve=False, vehicle=None) for x in applied.stops]
    seqs, dropped = heuristics.separate_trips(plain, m, cfg)
    base = solver.finish(seqs, dropped, plain, m, cfg, "soft", "separate_trips", "heuristic",
                         time.perf_counter())
    session.execute(update(VanPlan).where(VanPlan.distributor_id == distributor.id,
                                          VanPlan.status == "pending")
                    .values(status="superseded"))
    flagged = van_plan_store.flagged(sol, cands, inputs, m, cfg, limit)
    plan = VanPlan(
        distributor_id=distributor.id, clock_origin=inputs.origin, planned_at=inputs.now,
        horizon_h=horizon, params={"config": asdict(cfg), "rules": RULES_VERSION,
                                   "road_cache": cache.version,
                                   "estimated_legs": m.estimated_legs,
                                   "request": body.model_dump(mode="json"),
                                   "pins": pins_json(pins),
                                   "frozen": {str(a): v for a, v in sorted(frozen.items())},
                                   "stockout_p_limit": limit, "seed": seed},
        objective=van_plan_store.objective(
            sol, base, applied.stops, cfg, len(inputs.swapped) + len(applied.excluded), flagged),
        status="pending", input_hash=input_hash, distance_source=m.source, solver=sol.solver,
        stopped_by=sol.stopped_by, solve_ms=round(sol.solve_ms), model_version=inputs.model_version,
        created_by=user.id)
    session.add(plan)
    session.flush()
    van_plan_store.persist(session, plan, sol, inputs, applied, points, m, cfg, limit, pins)
    session.flush()
    return detail(session, plan)
