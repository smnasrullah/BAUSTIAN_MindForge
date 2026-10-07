"""Human actions on a van plan (distributor only) and its narrative. Every action is audited.

Approving only records that the distributor agreed to the plan; nothing here moves money.
A pin (lock / include / exclude) re-solves the plan as a new pending plan; the old one is
superseded. The narrative is LLM wording of the stored plan numbers through the guarded service
(numbers guard, llm_call_log, template fallback).
"""

from collections import Counter
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.llm import service, van_template
from app.llm.packs import Pack
from app.llm.templates import Draft
from app.models import AuditLog, User, VanPlan, VanRoute, VanStop
from app.models.enums import Lang, LlmIntent
from app.rules.van_routing.stability import Pin
from app.schemas.van_plan import (
    PinAction,
    VanDeliveredIn,
    VanNarrativeOut,
    VanPlanCreate,
    VanPlanOut,
)
from app.services import van_plan
from app.services.forecast import _utc
from app.services.van_plan_read import VanPlanError, detail, load

ENTITY = "van_plan"


def _audit(session: Session, user: User, action: str, p: VanPlan, note: str | None,
           **extra: Any) -> None:
    o = p.objective
    session.add(AuditLog(user_id=user.id, action=action, entity_type=ENTITY,
                         entity_id=str(p.id), note=note, payload={
                             "distributor_id": p.distributor_id, "input_hash": p.input_hash,
                             "trips": o["trips"], "served": o["served"],
                             "dropped": o["dropped"], "total_bdt": o["total_bdt"],
                             "solver": p.solver, "distance_source": p.distance_source,
                             **extra}))


def decide(session: Session, user: User, plan_id: int, decision: Literal["approve", "reject"],
           note: str) -> VanPlanOut:
    p = load(session, user, plan_id, lock=True)
    if p.status != "pending":
        raise VanPlanError("already_decided")
    p.status = "approved" if decision == "approve" else "rejected"
    p.decided_by, p.decided_at, p.note = user.id, clock.now(), note
    _audit(session, user, f"van_plan.{decision}", p, note, status=p.status)
    session.flush()
    return detail(session, p)


def delivered(session: Session, user: User, plan_id: int, stop_id: int,
              body: VanDeliveredIn) -> VanPlanOut:
    """Plan-vs-actual feedback for a stop of an approved plan."""
    p = load(session, user, plan_id, lock=True)
    stop = session.scalar(select(VanStop).where(VanStop.id == stop_id, VanStop.plan_id == p.id))
    if stop is None:
        raise VanPlanError("forbidden")
    if p.status != "approved":
        raise VanPlanError("plan_not_approved")
    if stop.status != "planned":
        raise VanPlanError("stop_not_planned")
    stop.status, stop.delivered_at = "delivered", clock.now()
    stop.delivered_amount = Decimal(str(round(body.delivered_amount_bdt, 2)))
    _audit(session, user, "van_plan.stop_delivered", p, body.note, stop_id=stop.id,
           agent_id=stop.agent_id, planned_bdt=float(stop.amount),
           delivered_bdt=body.delivered_amount_bdt,
           eta=None if stop.eta_lo is None else _utc(stop.eta_lo).isoformat())
    session.flush()
    return detail(session, p)


def _request(p: VanPlan) -> VanPlanCreate:
    """The plan's own request (V1 plans: rebuilt from the stored config)."""
    if "request" in p.params:
        return VanPlanCreate.model_validate(p.params["request"])
    c = p.params["config"]
    return VanPlanCreate.model_validate({
        "horizon_h": p.horizon_h, "options": {"time_limit_s": c["time_limit_s"]},
        "vehicles": {"count": c["vehicles"], "capacity_bdt": c["capacity_bdt"],
                     "cash_cap_bdt": c["cash_cap_bdt"]}})


def pin(session: Session, user: User, plan_id: int, stop_id: int, action: PinAction,
        note: str | None) -> VanPlanOut:
    """Lock (same van, served), include (served) or exclude one stop, then re-solve."""
    p = load(session, user, plan_id, lock=True)
    stop = session.scalar(select(VanStop).where(VanStop.id == stop_id, VanStop.plan_id == p.id))
    if stop is None:
        raise VanPlanError("forbidden")
    if p.status != "pending":
        raise VanPlanError("plan_not_pending")
    if stop.reason == "swap_suggested":
        raise VanPlanError("swap_covered")
    vehicle = None
    if action == "lock":
        if stop.route_id is None:
            raise VanPlanError("stop_not_routed")
        vehicle = session.scalar(select(VanRoute.vehicle_no).where(VanRoute.id == stop.route_id))
    pins = van_plan.pins_from(p.params.get("pins", {}))
    pins[stop.agent_id] = Pin(action, vehicle)
    out = van_plan.create(session, user, _request(p), pins)
    _audit(session, user, f"van_plan.stop_{action}", p, note, stop_id=stop.id,
           agent_id=stop.agent_id, new_plan_id=out.id)
    session.flush()
    return out


def evidence(session: Session, p: VanPlan) -> dict[str, Any]:
    """Numbers the narrative may use, all from the stored plan (no recomputation)."""
    reasons = Counter(session.scalars(select(VanStop.reason).where(
        VanStop.plan_id == p.id, VanStop.status == "dropped")))
    o = p.objective
    return {"trips": o["trips"], "served": o["served"], "dropped": o["dropped"],
            "km": o["km"], "total_bdt": o["total_bdt"],
            "separate_total_bdt": o["separate"]["total_bdt"],
            "separate_trips": o["separate"]["trips"],
            "swap_suggested": reasons.get("swap_suggested", 0),
            "cost_gt_value": reasons.get("cost_gt_value", 0),
            "capacity": reasons.get("capacity", 0), "excluded": reasons.get("excluded", 0),
            "flagged": o.get("flagged", 0), "fairness_forced": o.get("fairness_forced", 0),
            "fairness_short": o.get("fairness_short", []), "distance_source": p.distance_source}


def narrative(session: Session, user: User, plan_id: int, lang: Lang) -> VanNarrativeOut:
    """The LLM rewrites the template draft (no new numbers); any failure serves the template."""
    p = load(session, user, plan_id)
    data = evidence(session, p)
    draft = Draft(van_template.render(data, lang), [])
    out = service.generate(session, get_settings(), user,
                           Pack(LlmIntent.van_narrative, data, p.model_version), lang, draft=draft)
    return VanNarrativeOut(plan_id=p.id, lang=lang, text=out.text, generated_by=out.generated_by,
                           model_version=p.model_version, generated_at=_utc(p.created_at),
                           distance_source=p.distance_source,
                           fallback_reason=out.fallback_reason, no_api_key=out.no_api_key)
