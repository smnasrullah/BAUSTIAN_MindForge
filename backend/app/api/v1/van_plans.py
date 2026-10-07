"""Van route plans (F14). Distributor: create, read, decide, stop feedback (own agents only).
Admin: read only. Agents: no access (they never see route details). Advisory: no money moves."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import SessionDep, require_roles
from app.core.params import IdPath, PageQuery
from app.models import User
from app.models.enums import Lang, UserRole
from app.schemas.van_plan import (
    PinAction,
    PlanStatus,
    VanDecisionIn,
    VanDeliveredIn,
    VanNarrativeOut,
    VanPinIn,
    VanPlanCreate,
    VanPlanOut,
    VanPlanPage,
)
from app.services import van_plan, van_plan_actions, van_plan_read
from app.services.van_inputs import VanInputError
from app.services.van_plan_read import VanPlanError

router = APIRouter(prefix="/distributor/van-plans", tags=["van-plans"])

Distributor = Annotated[User, Depends(require_roles(UserRole.distributor))]
Reader = Annotated[User, Depends(require_roles(UserRole.distributor, UserRole.admin))]
_STATUS = {"forbidden": status.HTTP_403_FORBIDDEN}


def _http(exc: VanPlanError) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, status.HTTP_409_CONFLICT), detail=exc.code)


@router.post("", response_model=VanPlanOut, status_code=status.HTTP_201_CREATED)
def create(body: VanPlanCreate, user: Distributor, session: SessionDep) -> VanPlanOut:
    """Solve a plan for the caller's agents now (same inputs as a pending plan: that plan)."""
    try:
        plan = van_plan.create(session, user, body)
    except VanInputError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="van_not_ready") from exc
    except VanPlanError as exc:
        raise _http(exc) from exc
    session.commit()
    return plan


@router.get("", response_model=VanPlanPage)
def list_plans(
    user: Reader,
    session: SessionDep,
    plan_status: Annotated[PlanStatus | None, Query(alias="status")] = None,
    distributor_id: Annotated[int | None, Query(ge=1)] = None,
    page: PageQuery = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> VanPlanPage:
    """Plans in scope, newest first (distributor: own; admin: all, optional distributor filter)."""
    return van_plan_read.page(session, user, plan_status, distributor_id, page, page_size)


@router.get("/{plan_id}", response_model=VanPlanOut)
def get_plan(plan_id: IdPath, user: Reader, session: SessionDep) -> VanPlanOut:
    try:
        return van_plan_read.detail(session, van_plan_read.load(session, user, plan_id))
    except VanPlanError as exc:
        raise _http(exc) from exc


@router.post("/{plan_id}/decision", response_model=VanPlanOut)
def decide(plan_id: IdPath, body: VanDecisionIn, user: Distributor,
           session: SessionDep) -> VanPlanOut:
    """Approve or reject with a mandatory note (audit_log). Advisory: no money moves."""
    try:
        out = van_plan_actions.decide(session, user, plan_id, body.decision, body.note)
    except VanPlanError as exc:
        raise _http(exc) from exc
    session.commit()
    return out


@router.post("/{plan_id}/stops/{stop_id}/delivered", response_model=VanPlanOut)
def delivered(plan_id: IdPath, stop_id: IdPath, body: VanDeliveredIn, user: Distributor,
              session: SessionDep) -> VanPlanOut:
    """Plan-vs-actual feedback for a stop of an approved plan (audit_log)."""
    try:
        out = van_plan_actions.delivered(session, user, plan_id, stop_id, body)
    except VanPlanError as exc:
        raise _http(exc) from exc
    session.commit()
    return out


@router.post("/{plan_id}/stops/{stop_id}/{action}", response_model=VanPlanOut,
             status_code=status.HTTP_201_CREATED)
def pin(plan_id: IdPath, stop_id: IdPath, action: PinAction, user: Distributor,
        session: SessionDep, body: VanPinIn | None = None) -> VanPlanOut:
    """Lock (same van), include or exclude one stop of a pending plan: re-solved as a new
    pending plan (audit_log); the old plan is superseded."""
    try:
        out = van_plan_actions.pin(session, user, plan_id, stop_id, action,
                                   None if body is None else body.note)
    except VanInputError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="van_not_ready") from exc
    except VanPlanError as exc:
        raise _http(exc) from exc
    session.commit()
    return out


@router.get("/{plan_id}/narrative", response_model=VanNarrativeOut)
def narrative(plan_id: IdPath, user: Reader, session: SessionDep,
              lang: Lang = Lang.en) -> VanNarrativeOut:
    """'Why this order?' in bn/en: LLM wording of the plan's evidence through the guarded
    service, template on any failure (labelled generated_by)."""
    try:
        out = van_plan_actions.narrative(session, user, plan_id, lang)
    except VanPlanError as exc:
        raise _http(exc) from exc
    session.commit()  # llm_call_log + llm_cache rows
    return out
