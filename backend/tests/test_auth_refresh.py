from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.security import hash_refresh_token
from app.models import RefreshToken
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, login, post_refresh, refresh_cookie

API = "/api/v1"


def _row(raw: str) -> RefreshToken:
    with Session(get_engine()) as session:
        row = session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
        )
        assert row is not None
        return row


def test_login_sets_scoped_httponly_cookie(client: TestClient, seeded: Path) -> None:
    res = client.post(
        f"{API}/auth/login", json={"email": ADMIN, "password": "test-admin-pw"},
        headers={"User-Agent": "pytest-browser"},
    )
    cookie = res.headers["set-cookie"]
    assert cookie.startswith("ap_refresh=")
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "refresh_token" not in res.json()
    assert _row(refresh_cookie(client)).user_agent == "pytest-browser"


def test_refresh_rotates_token_and_links_chain(client: TestClient, seeded: Path) -> None:
    login(client, AGENT_MIRPUR)
    first = refresh_cookie(client)
    res = client.post(f"{API}/auth/refresh")
    assert res.status_code == 200
    second = refresh_cookie(client)
    assert second != first
    old = _row(first)
    assert old.revoked_at is not None
    assert old.replaced_by == _row(second).id
    me = client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}
    )
    assert me.status_code == 200


def test_reuse_revokes_whole_family_only(client: TestClient, seeded: Path) -> None:
    login(client, AGENT_MIRPUR)
    other_session = refresh_cookie(client)
    login(client, AGENT_MIRPUR)
    first = refresh_cookie(client)
    second = post_refresh(client, first)
    assert second.status_code == 200
    second_raw = refresh_cookie(client)
    third = post_refresh(client, second_raw)
    assert third.status_code == 200
    latest = refresh_cookie(client)

    reuse = post_refresh(client, first)
    assert reuse.status_code == 401
    assert reuse.json()["detail"] == "invalid_refresh_token"
    assert post_refresh(client, latest).status_code == 401
    # A separate login of the same user is a different family and survives.
    assert post_refresh(client, other_session).status_code == 200


def test_retry_whose_answer_was_lost_keeps_the_session(client: TestClient,
                                                      seeded: Path) -> None:
    """Reload or dropped connection mid-refresh: the server rotated, the browser kept the old
    cookie. Presenting it again soon, before anyone used the successor, is not theft."""
    login(client, AGENT_MIRPUR)
    first = refresh_cookie(client)
    assert post_refresh(client, first).status_code == 200
    lost = refresh_cookie(client)  # the answer the browser never stored

    retry = post_refresh(client, first)
    assert retry.status_code == 200
    kept = refresh_cookie(client)
    assert kept not in (first, lost)
    assert _row(lost).revoked_at is not None and _row(lost).replaced_by is None
    assert _row(first).replaced_by == _row(kept).id
    assert post_refresh(client, kept).status_code == 200
    newest = refresh_cookie(client)
    # The replaced token never works again, and it is not mistaken for a stolen one.
    assert post_refresh(client, lost).status_code == 401
    assert post_refresh(client, newest).status_code == 200


def test_old_token_after_the_grace_window_revokes_the_family(client: TestClient,
                                                              seeded: Path) -> None:
    login(client, AGENT_MIRPUR)
    first = refresh_cookie(client)
    assert post_refresh(client, first).status_code == 200
    successor = refresh_cookie(client)
    with Session(get_engine()) as session, session.begin():
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(first))
            .values(revoked_at=datetime.now(UTC) - timedelta(minutes=5))
        )
    assert post_refresh(client, first).status_code == 401
    assert post_refresh(client, successor).status_code == 401


def test_refresh_without_cookie_rejected(client: TestClient, seeded: Path) -> None:
    res = client.post(f"{API}/auth/refresh")
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid_refresh_token"


def test_failed_refresh_clears_cookie(client: TestClient, seeded: Path) -> None:
    res = post_refresh(client, "x" * 64)
    assert res.status_code == 401
    assert 'ap_refresh=""' in res.headers["set-cookie"]


def test_expired_refresh_token_rejected(client: TestClient, seeded: Path) -> None:
    login(client, ADMIN)
    raw = refresh_cookie(client)
    with Session(get_engine()) as session, session.begin():
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert post_refresh(client, raw).status_code == 401


def test_access_token_cannot_be_used_as_refresh(client: TestClient, seeded: Path) -> None:
    access = str(login(client, ADMIN)["access_token"])
    assert post_refresh(client, access).status_code == 401


def test_logout_revokes_and_clears_cookie(client: TestClient, seeded: Path) -> None:
    login(client, ADMIN)
    raw = refresh_cookie(client)
    res = client.post(f"{API}/auth/logout")
    assert res.status_code == 204
    assert 'ap_refresh=""' in res.headers["set-cookie"]
    assert _row(raw).revoked_at is not None
    assert post_refresh(client, raw).status_code == 401


def test_logout_without_session_is_harmless(client: TestClient, seeded: Path) -> None:
    assert client.post(f"{API}/auth/logout").status_code == 204


def test_refresh_token_stored_hashed(client: TestClient, seeded: Path) -> None:
    login(client, ADMIN)
    raw = refresh_cookie(client)
    with Session(get_engine()) as session:
        hashes = session.scalars(select(RefreshToken.token_hash)).all()
    assert raw not in hashes
    assert hash_refresh_token(raw) in hashes
