from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.deps import CurrentUser, SessionDep, require_roles
from app.core.params import IdPath, PageQuery
from app.models import User
from app.models.enums import RequestStatus, UserRole
from app.schemas.recommendation_request import (
    RequestDecisionIn,
    RequestItem,
    RequestNoteIn,
    RequestPage,
)
from app.services import recommendation_requests as requests
from app.services.recommendation_requests import Action, RequestError

router = APIRouter(tags=["recommendation-requests"])

Distributor = Annotated[User, Depends(require_roles(UserRole.distributor))]
AgentUser = Annotated[User, Depends(require_roles(UserRole.agent))]
_STATUS = {"forbidden": status.HTTP_403_FORBIDDEN}


def _http(exc: RequestError) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, status.HTTP_409_CONFLICT), detail=exc.code)


def _act(session: SessionDep, user: User, request_id: int, action: Action,
         note: str | None) -> RequestItem:
    try:
        item = requests.transition(session, user, request_id, action, note)
    except RequestError as exc:
        raise _http(exc) from exc
    session.commit()
    return item


@router.post("/recommendations/{recommendation_id}/request", response_model=RequestItem,
             status_code=status.HTTP_201_CREATED,
             responses={200: {"model": RequestItem, "description": "Already requested: the "
                              "existing request"}})
def create_request(recommendation_id: IdPath, user: AgentUser, session: SessionDep,
                   response: Response) -> RequestItem:
    """Agent asks the distributor to act on own recommendation. A repeat call returns the
    existing request (200)."""
    try:
        item, created = requests.create(session, user, recommendation_id)
    except RequestError as exc:
        raise _http(exc) from exc
    session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return item


@router.get("/recommendation-requests", response_model=RequestPage)
def list_requests(
    user: CurrentUser,
    session: SessionDep,
    request_status: Annotated[RequestStatus | None, Query(alias="status")] = None,
    page: PageQuery = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RequestPage:
    """Requests in scope (agent: own; distributor: own agents; admin: all), newest first."""
    return requests.page(session, user, request_status, page, page_size)


@router.post("/recommendation-requests/{request_id}/decision", response_model=RequestItem)
def decide(request_id: IdPath, body: RequestDecisionIn, user: Distributor,
           session: SessionDep) -> RequestItem:
    """Distributor approves or declines a requested item with a note (audit_log)."""
    return _act(session, user, request_id, body.decision, body.note)


@router.post("/recommendation-requests/{request_id}/fulfil", response_model=RequestItem)
def fulfil(request_id: IdPath, user: Distributor, session: SessionDep,
           body: RequestNoteIn | None = None) -> RequestItem:
    """Distributor records that an approved request was delivered (audit_log)."""
    return _act(session, user, request_id, "fulfil", body.note if body else None)


@router.post("/recommendation-requests/{request_id}/cancel", response_model=RequestItem)
def cancel(request_id: IdPath, user: AgentUser, session: SessionDep,
           body: RequestNoteIn | None = None) -> RequestItem:
    """Agent withdraws own request while it is still awaiting a decision (audit_log)."""
    return _act(session, user, request_id, "cancel", body.note if body else None)
