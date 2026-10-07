"""Login with lockout, refresh rotation with family reuse detection, logout, password change."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import AuditLog, LoginFailure, RefreshToken, User
from app.models.enums import UserRole
from app.services.seed import DEMO_ACCOUNTS

USER_AGENT_MAX = 256
# Bound on the rotation chain walked when a reused token revokes its family.
FAMILY_WALK_LIMIT = 10_000
# A rotated token presented again this soon, while its successor is still unused, is a retry
# whose answer never reached the browser (reload mid-request, dropped mobile connection).
REFRESH_RETRY_GRACE = timedelta(seconds=30)


class AuthError(Exception):
    """`code`: invalid_credentials, too_many_attempts, invalid_refresh_token,
    wrong_password, same_password, demo_mode_off, demo_account_missing, signup_rejected or
    invalid_reset_token."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IssuedTokens:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_max_age: int


def _aware(ts: datetime) -> datetime:
    # SQLite drops tzinfo; stored values are always UTC.
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _find(session: Session, raw_token: str, lock: bool = False) -> RefreshToken | None:
    query = select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    # Row lock (Postgres): two refreshes of one token run one after the other.
    return session.scalar(query.with_for_update() if lock else query)


def _issue(
    session: Session, user: User, settings: Settings, now: datetime, user_agent: str | None
) -> tuple[IssuedTokens, RefreshToken]:
    access, expires_in = create_access_token(user.id, user.role.value, settings, now)
    raw_refresh = new_refresh_token()
    ttl = timedelta(days=settings.jwt_refresh_ttl_days)
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=now + ttl,
        user_agent=(user_agent or "")[:USER_AGENT_MAX] or None,
    )
    session.add(row)
    tokens = IssuedTokens(user, access, raw_refresh, expires_in, int(ttl.total_seconds()))
    return tokens, row


def _recent_failures(session: Session, email: str, ip: str, since: datetime) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(LoginFailure)
        .where(LoginFailure.email == email, LoginFailure.ip == ip, LoginFailure.created_at >= since)
    )
    return int(count or 0)


def login(
    session: Session,
    email: str,
    password: str,
    ip: str,
    user_agent: str | None,
    settings: Settings,
) -> IssuedTokens:
    """Lockout is per (email, ip) and applies to unknown emails too, so it reveals nothing."""
    now = datetime.now(UTC)
    email = email.strip().lower()
    window_start = now - timedelta(minutes=settings.login_lockout_min)
    if _recent_failures(session, email, ip, window_start) >= settings.login_max_failures:
        raise AuthError("too_many_attempts")
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        burn_password_check(password)
    ok = user is not None and verify_password(password, user.password_hash) and user.is_active
    if user is None or not ok:
        session.add(LoginFailure(email=email, ip=ip, created_at=now))
        session.commit()
        raise AuthError("invalid_credentials")
    session.execute(delete(LoginFailure).where(LoginFailure.email == email, LoginFailure.ip == ip))
    user.last_login_at = now
    tokens, _ = _issue(session, user, settings, now, user_agent)
    session.commit()
    return tokens


def clear_login_failures(session: Session, email: str) -> int:
    """Forget recent failed logins for `email` (all IPs). CLI only: e2e reruns within the window."""
    result = session.execute(delete(LoginFailure).where(LoginFailure.email == email.lower()))
    return int(getattr(result, "rowcount", 0) or 0)


DemoOutcome = Literal["success", "denied", "rate_limited"]


def record_demo_attempt(session: Session, role: UserRole, ip: str, outcome: DemoOutcome,
                        user: User | None = None) -> None:
    """audit_log row for one demo-login attempt (account, IP, outcome; created_at is the time).
    Never passwords or tokens. The caller commits."""
    account = DEMO_ACCOUNTS[role]
    if user is None:
        user = session.scalar(select(User).where(User.email == account))
    session.add(AuditLog(user_id=user.id if user else None, action="auth.demo_login",
                         entity_type="user", entity_id=account, note=None,
                         payload={"account": account, "role": role.value, "ip": ip,
                                  "outcome": outcome}))


def demo_login(
    session: Session, role: UserRole, ip: str, user_agent: str | None, settings: Settings
) -> IssuedTokens:
    """DEMO_MODE only: sign in as the seeded demo account of `role`, no password.

    Only active is_demo accounts; a missing, inactive or non-demo account gets the same
    `demo_login_denied`. Every attempt is audited.
    """
    if not settings.demo_mode:
        raise AuthError("demo_mode_off")
    user = session.scalar(select(User).where(User.email == DEMO_ACCOUNTS[role]))
    if user is None or not user.is_active or not user.is_demo:
        record_demo_attempt(session, role, ip, "denied", user)
        session.commit()
        raise AuthError("demo_login_denied")
    now = datetime.now(UTC)
    user.last_login_at = now
    tokens, _ = _issue(session, user, settings, now, user_agent)
    record_demo_attempt(session, role, ip, "success", user)
    session.commit()
    return tokens


def _revoke_family_from(session: Session, start: RefreshToken, now: datetime) -> None:
    """Revoke `start` and every token it was rotated into."""
    row: RefreshToken | None = start
    for _ in range(FAMILY_WALK_LIMIT):
        if row is None:
            return
        if row.revoked_at is None:
            row.revoked_at = now
        row = session.get(RefreshToken, row.replaced_by) if row.replaced_by else None


def refresh(
    session: Session, raw_token: str | None, user_agent: str | None, settings: Settings
) -> IssuedTokens:
    now = datetime.now(UTC)
    row = _find(session, raw_token, lock=True) if raw_token else None
    if row is None:
        raise AuthError("invalid_refresh_token")
    if row.revoked_at is not None:
        successor = session.get(RefreshToken, row.replaced_by) if row.replaced_by else None
        retry = (successor is not None and successor.revoked_at is None
                 and now - _aware(row.revoked_at) <= REFRESH_RETRY_GRACE)
        if retry and successor is not None:
            # The browser never got `successor` (nobody has used it): replace it, keep the session.
            successor.revoked_at = now
        else:
            if row.replaced_by is not None:
                # A rotated token came back: assume theft and end that whole session family.
                _revoke_family_from(session, row, now)
                session.commit()
            raise AuthError("invalid_refresh_token")
    user = session.get(User, row.user_id)
    if _aware(row.expires_at) <= now or user is None or not user.is_active:
        raise AuthError("invalid_refresh_token")
    tokens, successor = _issue(session, user, settings, now, user_agent or row.user_agent)
    session.flush()
    row.revoked_at = row.revoked_at or now
    row.replaced_by = successor.id
    session.commit()
    return tokens


def logout(session: Session, raw_token: str | None) -> None:
    """Revoke the presented refresh token; unknown or missing tokens are ignored."""
    row = _find(session, raw_token) if raw_token else None
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        session.commit()


def change_password(
    session: Session, user: User, old: str, new: str, current_refresh: str | None
) -> int:
    """Verify `old`, store `new`, revoke every other session. Returns sessions revoked."""
    if not verify_password(old, user.password_hash):
        raise AuthError("wrong_password")
    if old == new:
        raise AuthError("same_password")
    user.password_hash = hash_password(new)
    keep = _find(session, current_refresh) if current_refresh else None
    query = update(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
    )
    if keep is not None and keep.user_id == user.id:
        query = query.where(RefreshToken.id != keep.id)
    result = session.execute(query.values(revoked_at=datetime.now(UTC)))
    session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
