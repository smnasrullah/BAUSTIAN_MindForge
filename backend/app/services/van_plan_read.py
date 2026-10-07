"""Van plan reads: role scope, list, detail. Distributors see their own plans, admins all (read
only); agents never see route details (the API refuses them before this runs)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Agent, Distributor, User, VanPlan, VanRoute, VanStop
from app.models.enums import UserRole
from app.schemas.van_plan import (
    PlanStatus,
    VanComparison,
    VanDepot,
    VanFairnessGroup,
    VanLeg,
    VanObjective,
    VanPlanOut,
    VanPlanPage,
    VanPlanSummary,
    VanRouteOut,
    VanStopOut,
)
from app.services import van_geometry
from app.services.forecast import _utc


class VanPlanError(Exception):
    """forbidden (403); already_decided, plan_not_approved, stop_not_planned (409)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def scoped(user: User) -> Select[tuple[VanPlan]]:
    query = select(VanPlan)
    if user.role == UserRole.distributor:
        return query.where(VanPlan.distributor_id == user.distributor_id)
    if user.role == UserRole.admin:
        return query
    raise VanPlanError("forbidden")


def load(session: Session, user: User, plan_id: int, lock: bool = False) -> VanPlan:
    """Unknown and out-of-scope ids both raise forbidden, so ids cannot be probed."""
    query = scoped(user).where(VanPlan.id == plan_id)
    found = session.scalar(query.with_for_update() if lock else query)
    if found is None:
        raise VanPlanError("forbidden")
    return found


def _ts(ts: datetime | None) -> datetime | None:
    return None if ts is None else _utc(ts)


def summary(p: VanPlan) -> VanPlanSummary:
    o = p.objective
    return VanPlanSummary(
        id=p.id, distributor_id=p.distributor_id, status=p.status, planned_at=_utc(p.planned_at),
        clock_origin=_utc(p.clock_origin), horizon_h=p.horizon_h, solver=p.solver,
        stopped_by=p.stopped_by, solve_ms=p.solve_ms, distance_source=p.distance_source,
        model_version=p.model_version, generated_at=_utc(p.created_at), input_hash=p.input_hash,
        served=o["served"], dropped=o["dropped"], trips=o["trips"], km=o["km"],
        total_bdt=o["total_bdt"])


def page(session: Session, user: User, status: PlanStatus | None, distributor_id: int | None,
         page_no: int, page_size: int) -> VanPlanPage:
    query = scoped(user)
    if status is not None:
        query = query.where(VanPlan.status == status)
    if distributor_id is not None:
        query = query.where(VanPlan.distributor_id == distributor_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(VanPlan.created_at.desc(), VanPlan.id.desc())
                           .offset((page_no - 1) * page_size).limit(page_size)).all()
    return VanPlanPage(items=[summary(p) for p in rows], total=total, page=page_no,
                       page_size=page_size)


def _stop(s: VanStop, a: Agent) -> VanStopOut:
    d: dict[str, Any] = s.details
    return VanStopOut(
        id=s.id, seq=s.seq, agent_id=a.id, agent_code=a.code, agent_name=a.name, lat=a.lat,
        lng=a.lng, group=d.get("group", ""), amount_bdt=float(s.amount),
        source_quantile=s.source_quantile, eta_lo=_ts(s.eta_lo), eta_hi=_ts(s.eta_hi),
        deadline=_ts(s.deadline), late_h=d.get("late_h"), penalty_bdt=float(s.penalty_bdt),
        lost_per_h_bdt=d.get("lost_per_h_bdt", 0.0),
        stockout_before_arrival_p=None if s.stockout_before_arrival_p is None
        else float(s.stockout_before_arrival_p),
        status=s.status, reason=s.reason, delivered_at=_ts(s.delivered_at),
        delivered_amount_bdt=None if s.delivered_amount is None else float(s.delivered_amount),
        stockout_risk_flag=d.get("stockout_flag"), pin=d.get("pin"),
        fairness_forced=bool(d.get("fairness_forced", False)),
        deadline_rule=d.get("deadline_rule"))


def _legs(r: VanRoute) -> list[VanLeg]:
    lines = van_geometry.load().polylines
    return [VanLeg(**leg, polyline=lines.get((leg["from_key"], leg["to_key"]))) for leg in r.legs]


def detail(session: Session, p: VanPlan, reused: bool = False) -> VanPlanOut:
    routes: Sequence[VanRoute] = session.scalars(
        select(VanRoute).where(VanRoute.plan_id == p.id).order_by(VanRoute.vehicle_no)).all()
    stops = session.execute(
        select(VanStop, Agent).join(Agent, Agent.id == VanStop.agent_id)
        .where(VanStop.plan_id == p.id).order_by(VanStop.route_id, VanStop.seq, VanStop.id)
    ).tuples().all()
    by_route: dict[int | None, list[VanStopOut]] = {}
    for s, a in stops:
        by_route.setdefault(s.route_id, []).append(_stop(s, a))
    o = p.objective
    hub = session.get(Distributor, p.distributor_id)
    assert hub is not None  # van_plans.distributor_id is a foreign key
    return VanPlanOut(
        **summary(p).model_dump(), reused=reused, params=p.params,
        depot=VanDepot(code=hub.code, name=hub.name, lat=hub.hub_lat, lng=hub.hub_lng),
        objective=VanObjective(**o["breakdown"]), separate_trips=VanComparison(**o["separate"]),
        routes=[VanRouteOut(id=r.id, vehicle_no=r.vehicle_no, km=float(r.km),
                            minutes=float(r.minutes), cash_load_bdt=float(r.cash_load),
                            cost_bdt=float(r.cost_bdt), legs=_legs(r),
                            stops=by_route.get(r.id, [])) for r in routes],
        unrouted=by_route.get(None, []),
        decided_by=None if p.decided_by is None else str(p.decided_by),
        decided_at=_ts(p.decided_at), note=p.note,
        fairness=[VanFairnessGroup(**g) for g in o.get("fairness", [])],
        fairness_short=o.get("fairness_short", []),
        stockout_p_limit=p.params.get("stockout_p_limit"), flagged=o.get("flagged", 0),
        choice=o.get("choice"))
