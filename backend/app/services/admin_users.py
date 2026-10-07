"""Admin user management: list, create, change role / link, disable / enable.

Every change writes audit_log (user.create / user.update / user.disable / user.enable /
user.approve / user.reject). Approving a pending self-signup is `is_active: true` on that user;
rejecting it keeps the row (inactive, `is_rejected`), so it can never sign in and a new signup
with that e-mail gets the same reply as any taken e-mail.
Disabling revokes the user's refresh tokens; the 15-minute access token then fails at the next
request because get_current_user checks is_active.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Agent, AuditLog, Distributor, RefreshToken, User
from app.models.enums import UserRole
from app.schemas.admin import (
    AdminUser,
    AdminUserCreate,
    AdminUserPage,
    AdminUserUpdate,
    OrgAgent,
    OrgDirectory,
    OrgDistributor,
    UserStatus,
)

ENTITY = "user"


class UserAdminError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


Codes = tuple[str | None, str | None]


def _item(session: Session, u: User, codes: Codes | None = None) -> AdminUser:
    """`codes` (agent, distributor) come joined from the list query; single rows look them up."""
    if codes is None:
        agent = session.get(Agent, u.agent_id) if u.agent_id else None
        dist = session.get(Distributor, u.distributor_id) if u.distributor_id else None
        codes = (agent.code if agent else None, dist.code if dist else None)
    agent_code, dist_code = codes
    created = _utc(u.created_at)
    assert created is not None
    return AdminUser(id=u.id, email=u.email, full_name=u.full_name, role=u.role,
                     agent_id=u.agent_id, agent_code=agent_code, distributor_id=u.distributor_id,
                     distributor_code=dist_code, is_active=u.is_active, is_demo=u.is_demo,
                     is_pending=u.is_pending, is_rejected=u.is_rejected,
                     last_login_at=_utc(u.last_login_at),
                     created_at=created)


def user_page(session: Session, role: UserRole | None, status: UserStatus | None, q: str | None,
              page: int, page_size: int) -> AdminUserPage:
    query = select(User)
    if role is not None:
        query = query.where(User.role == role)
    if status == "active":
        query = query.where(User.is_active.is_(True))
    elif status == "pending":
        query = query.where(User.is_pending.is_(True))
    elif status == "rejected":
        query = query.where(User.is_rejected.is_(True))
    elif status == "disabled":
        query = query.where(User.is_active.is_(False), User.is_pending.is_(False),
                            User.is_rejected.is_(False))
    if q:
        query = query.where(or_(User.email.icontains(q, autoescape=True),
                                User.full_name.icontains(q, autoescape=True)))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    # One query for the page: agent / distributor codes joined in, not fetched per row.
    rows = session.execute(
        query.add_columns(Agent.code, Distributor.code)
        .outerjoin(Agent, Agent.id == User.agent_id)
        .outerjoin(Distributor, Distributor.id == User.distributor_id)
        .order_by(User.role, User.email).offset((page - 1) * page_size).limit(page_size)
    ).tuples()
    return AdminUserPage(items=[_item(session, u, (a, d)) for u, a, d in rows], total=total,
                         page=page, page_size=page_size)


def directory(session: Session) -> OrgDirectory:
    dists = session.scalars(select(Distributor).order_by(Distributor.code))
    agents = session.scalars(select(Agent).order_by(Agent.code))
    return OrgDirectory(
        distributors=[OrgDistributor(id=d.id, code=d.code, name=d.name) for d in dists],
        agents=[OrgAgent(id=a.id, code=a.code, name=a.name, distributor_id=a.distributor_id)
                for a in agents])


def _links(session: Session, role: UserRole, agent_id: int | None,
           distributor_id: int | None) -> tuple[int | None, int | None]:
    """The (agent_id, distributor_id) pair a role keeps; unknown ids are rejected.

    An agent user's distributor is derived from the agent row (as in the reference seed)."""
    if role == UserRole.agent:
        if agent_id is None:
            raise UserAdminError("agent_required")
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise UserAdminError("unknown_agent")
        return agent_id, agent.distributor_id
    if role == UserRole.distributor:
        if distributor_id is None:
            raise UserAdminError("distributor_required")
        if session.get(Distributor, distributor_id) is None:
            raise UserAdminError("unknown_distributor")
        return None, distributor_id
    return None, None


def _snapshot(u: User) -> dict[str, Any]:
    return {"email": u.email, "full_name": u.full_name, "role": u.role.value,
            "agent_id": u.agent_id, "distributor_id": u.distributor_id, "is_active": u.is_active,
            "is_pending": u.is_pending}


def _audit(session: Session, actor: User, action: str, target: User, note: str | None,
           payload: dict[str, Any]) -> None:
    session.add(AuditLog(user_id=actor.id, action=f"{ENTITY}.{action}", entity_type=ENTITY,
                         entity_id=str(target.id), note=note, payload=payload))


def create(session: Session, actor: User, body: AdminUserCreate) -> AdminUser:
    if session.scalar(select(User.id).where(func.lower(User.email) == body.email)) is not None:
        raise UserAdminError("email_taken")
    agent_id, distributor_id = _links(session, body.role, body.agent_id, body.distributor_id)
    u = User(email=body.email, full_name=body.full_name, role=body.role, agent_id=agent_id,
             distributor_id=distributor_id, password_hash=hash_password(body.password),
             is_active=True, is_demo=False)
    session.add(u)
    session.flush()
    _audit(session, actor, "create", u, None, {"after": _snapshot(u)})  # never the password
    return _item(session, u)


def _revoke_sessions(session: Session, user_id: uuid.UUID) -> None:
    session.execute(update(RefreshToken).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC)))


def _change_action(before: dict[str, Any], after: dict[str, Any]) -> str:
    if before["is_pending"] and not after["is_pending"]:
        return "approve"
    if before["is_active"] != after["is_active"]:
        return "enable" if after["is_active"] else "disable"
    return "update"


def update_user(session: Session, actor: User, user_id: uuid.UUID,
                body: AdminUserUpdate) -> AdminUser:
    # Row lock: two admins approving and rejecting the same signup at once must not both pass
    # the "pending" check (Postgres; tests/test_admin_users_postgres.py).
    u = session.get(User, user_id, with_for_update=True)
    if u is None:
        raise UserAdminError("user_not_found")
    sent = body.model_fields_set
    if u.id == actor.id and (("role" in sent and body.role != u.role)
                             or ("is_active" in sent and body.is_active is False)):
        raise UserAdminError("cannot_change_self")  # an admin cannot lock themselves out
    if u.is_rejected and body.is_active:
        raise UserAdminError("user_rejected")  # a rejected signup is never activated
    before = _snapshot(u)
    if body.full_name is not None:
        u.full_name = body.full_name
    if {"role", "agent_id", "distributor_id"} & sent:
        role = body.role or u.role
        # A new role takes only the links sent with it; otherwise unsent links are kept.
        keep = role == u.role
        agent_id = body.agent_id if "agent_id" in sent or not keep else u.agent_id
        dist_id = (body.distributor_id if "distributor_id" in sent or not keep
                   else u.distributor_id)
        u.role = role
        u.agent_id, u.distributor_id = _links(session, role, agent_id, dist_id)
    if body.is_active is not None and body.is_active != u.is_active:
        u.is_active = body.is_active
        if u.is_active:
            u.is_pending = False  # activation is the approval of a pending signup
        else:
            _revoke_sessions(session, u.id)
    if u.role == UserRole.agent and u.agent_id is None and not u.is_pending:
        raise UserAdminError("agent_required")  # approve with the agent this account runs
    session.flush()
    after = _snapshot(u)
    if after != before:
        action = _change_action(before, after)
        _audit(session, actor, action, u, body.note, {"before": before, "after": after})
    return _item(session, u)


def reject(session: Session, actor: User, user_id: uuid.UUID, note: str | None) -> AdminUser:
    """Reject a pending self-signup: inactive, no longer pending, kept for the audit trail."""
    u = session.get(User, user_id, with_for_update=True)
    if u is None:
        raise UserAdminError("user_not_found")
    if not u.is_pending:
        raise UserAdminError("not_pending")
    before = _snapshot(u)
    u.is_pending, u.is_active, u.is_rejected = False, False, True
    _revoke_sessions(session, u.id)  # none expected; a pending account never signed in
    session.flush()
    _audit(session, actor, "reject", u, note,
           {"before": before, "after": _snapshot(u), "outcome": "rejected"})
    return _item(session, u)
