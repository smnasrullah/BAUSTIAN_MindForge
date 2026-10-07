from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import require_roles
from app.models import User
from app.models.enums import UserRole
from app.schemas.evidence import PainPointsOut
from app.services import pain_points

router = APIRouter(prefix="/evidence", tags=["evidence"])

Viewer = Annotated[User, Depends(require_roles(UserRole.distributor, UserRole.admin))]


@router.get("/pain-points", response_model=PainPointsOut)
def get_pain_points(user: Viewer) -> PainPointsOut:
    """Ranked liquidity pain points by source type (FIELD, LITERATURE, SIMULATED), no database."""
    return pain_points.build()
