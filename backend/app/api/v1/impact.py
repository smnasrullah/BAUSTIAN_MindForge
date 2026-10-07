from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import SessionDep, require_roles
from app.models import User
from app.models.enums import UserRole
from app.schemas.impact import ImpactComparison, ImpactSummary
from app.schemas.van_plan import VanEvalOut
from app.services import impact_read, van_eval_read

router = APIRouter(prefix="/impact", tags=["impact"])

Viewer = Annotated[User, Depends(require_roles(UserRole.distributor, UserRole.admin))]
VanCost = Annotated[float | None, Query(ge=0, le=100_000,
                                        description="BDT per van trip; default from settings")]


def _not_ready() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="impact_not_ready")


@router.get("/summary", response_model=ImpactSummary)
def get_summary(user: Viewer, session: SessionDep, van_cost: VanCost = None) -> ImpactSummary:
    """AI vs fixed-threshold baseline over the 14 held-out days (own agents for a distributor)."""
    result = impact_read.summary(session, user, van_cost)
    if result is None:
        raise _not_ready()
    return result


@router.get("/comparison", response_model=ImpactComparison)
def get_comparison(
    user: Viewer,
    session: SessionDep,
    start: Annotated[date | None, Query(alias="from", description="first local day")] = None,
    end: Annotated[date | None, Query(alias="to", description="last local day, inclusive")] = None,
    van_cost: VanCost = None,
) -> ImpactComparison:
    """Day-by-day AI vs baseline inside [from, to] (clipped to the holdout) + range totals."""
    if start is not None and end is not None and start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="from_after_to")
    result = impact_read.comparison(session, user, start, end, van_cost)
    if result is None:
        raise _not_ready()
    return result


@router.get("/van-comparison", response_model=VanEvalOut)
def get_van_comparison(user: Viewer) -> VanEvalOut:
    """Van routing policies A-D on held-out synthetic days: >= 5 seeds with 95% intervals, the
    D vs C and D vs A contrasts, and sensitivity (road factor, fuel cost, delivery reliability)."""
    result = van_eval_read.load()
    if result is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="van_eval_missing")
    return result
