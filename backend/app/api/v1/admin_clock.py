"""Admin: the data clock (mode, now, last / next tick, catch-up) and "Run tick now"."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import get_settings
from app.core.deps import SessionDep, require_roles
from app.models import User
from app.models.enums import UserRole
from app.schemas.admin_clock import AdminClock, TickRequestOut
from app.services import admin_clock
from app.services.admin_clock import ClockError

router = APIRouter(prefix="/admin/clock", tags=["admin"])

Admin = Annotated[User, Depends(require_roles(UserRole.admin))]


@router.get("", response_model=AdminClock)
def get_clock(_user: Admin, session: SessionDep) -> AdminClock:
    """Clock mode and now, data hour, last tick (duration per stage), next tick, catch-up."""
    return admin_clock.overview(session, get_settings())


@router.post("/tick", response_model=TickRequestOut, status_code=status.HTTP_202_ACCEPTED)
def run_tick(user: Admin, session: SessionDep) -> TickRequestOut:
    """Ask the data clock to tick now (live clock only; 409 clock_fixed otherwise). The leader
    process runs it within one check interval; the result shows on GET /admin/clock. Audited."""
    try:
        at = admin_clock.request_tick(session, user)
    except ClockError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.code) from exc
    session.commit()
    return TickRequestOut(requested_at=at)
