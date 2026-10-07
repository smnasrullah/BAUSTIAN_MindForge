"""Admin console: role gate, overview, users (create / role + link / disable), audit log."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import AuditLog, Distributor, RefreshToken, User
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, agent_id, bearer

API = "/api/v1/admin"
ADMIN_GETS = ("/overview", "/users", "/org", "/audit-log", "/audit-log/export.csv", "/data",
              "/data/assumptions", "/models", "/drift", "/jobs", "/llm/logs", "/llm/usage")
NEW_PW = "fresh-password-123"


def _dist_id(code: str) -> int:
    with Session(get_engine()) as session:
        found = session.scalar(select(Distributor.id).where(Distributor.code == code))
        assert found is not None
        return found


def _actions(entity_type: str) -> list[str]:
    with Session(get_engine()) as session:
        return list(session.scalars(select(AuditLog.action).where(
            AuditLog.entity_type == entity_type).order_by(AuditLog.id)))


@pytest.mark.parametrize("email", [AGENT_MIRPUR, DIST_DHAKA])
def test_non_admins_are_forbidden(client: TestClient, seeded: Path, email: str) -> None:
    h = bearer(client, email)
    for path in ADMIN_GETS:
        assert client.get(f"{API}{path}", headers=h).status_code == 403, path
    assert client.post(f"{API}/users", json={}, headers=h).status_code == 403
    assert client.post(f"{API}/jobs", json={"kind": "generate_data"}, headers=h).status_code == 403
    assert client.get(f"{API}/overview").status_code == 401


def test_overview(client: TestClient, seeded: Path) -> None:
    res = client.get(f"{API}/overview", headers=bearer(client, ADMIN))
    assert res.status_code == 200, res.text
    body = res.json()
    roles = {r["role"]: r for r in body["users"]}
    assert set(roles) == {"agent", "distributor", "admin"}
    assert sum(r["total"] for r in roles.values()) == 7
    assert all(0 <= r["active"] <= r["total"] for r in roles.values())
    assert roles["admin"]["total"] >= 1 and roles["admin"]["active"] >= 1
    assert body["agents"] == 3 and body["distributors"] == 3
    assert body["latest_job"] is None and body["llm_daily_cap"] > 0
    assert any(a["action"] == "auth.login" for a in body["recent_audit"]) or \
        isinstance(body["recent_audit"], list)


def test_create_agent_user_and_sign_in(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    body = {"email": "New.Agent@Example.org", "full_name": "New agent", "role": "agent",
            "agent_id": agent_id("AGT-0001"), "password": NEW_PW}
    res = client.post(f"{API}/users", json=body, headers=h)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["email"] == "new.agent@example.org"
    assert (created["agent_code"], created["distributor_code"]) == ("AGT-0001", "DST-DHK")
    assert client.post(f"{API}/users", json=body, headers=h).json()["detail"] == "email_taken"
    login = client.post("/api/v1/auth/login",
                        json={"email": "new.agent@example.org", "password": NEW_PW})
    assert login.status_code == 200 and login.json()["user"]["role"] == "agent"
    assert _actions("user") == ["user.create"]
    with Session(get_engine()) as session:
        payload = session.scalars(select(AuditLog.payload)).all()
    assert all(NEW_PW not in str(p) for p in payload)


@pytest.mark.parametrize(("body", "code"), [
    ({"role": "agent"}, "agent_required"),
    ({"role": "agent", "agent_id": 99999}, "unknown_agent"),
    ({"role": "distributor"}, "distributor_required"),
    ({"role": "distributor", "distributor_id": 99999}, "unknown_distributor"),
])
def test_create_requires_valid_link(client: TestClient, seeded: Path, body: dict[str, object],
                                    code: str) -> None:
    full = {"email": "x@example.org", "full_name": "X", "password": NEW_PW, **body}
    res = client.post(f"{API}/users", json=full, headers=bearer(client, ADMIN))
    assert (res.status_code, res.json()["detail"]) == (422, code)


def test_create_validates_body(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    bad = {"email": "not-an-email", "full_name": "X", "role": "admin", "password": "short"}
    assert client.post(f"{API}/users", json=bad, headers=h).status_code == 422


def test_change_role_link_and_disable(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    page = client.get(f"{API}/users", params={"q": "mirpur"}, headers=h).json()
    assert page["total"] == 1
    target = page["items"][0]
    url = f"{API}/users/{target['id']}"
    # Role change re-checks the link.
    res = client.patch(url, json={"role": "distributor"}, headers=h)
    assert res.json()["detail"] == "distributor_required"
    dist = _dist_id("DST-DHK")
    res = client.patch(url, json={"role": "distributor", "distributor_id": dist}, headers=h)
    assert res.status_code == 200, res.text
    assert (res.json()["role"], res.json()["agent_id"], res.json()["distributor_code"]) == (
        "distributor", None, "DST-DHK")
    # Disable: sessions revoked, sign-in refused, audit with note.
    with Session(get_engine()) as session, session.begin():
        uid = session.scalar(select(User.id).where(User.email == AGENT_MIRPUR))
        assert uid is not None
        session.add(RefreshToken(user_id=uid, token_hash="h",
                                 expires_at=datetime.now(UTC) + timedelta(days=1)))
    res = client.patch(url, json={"is_active": False, "note": "left the network"}, headers=h)
    assert res.status_code == 200 and res.json()["is_active"] is False
    with Session(get_engine()) as session:
        tokens = session.scalars(select(RefreshToken).where(RefreshToken.token_hash == "h")).all()
        assert all(t.revoked_at is not None for t in tokens)
        note = session.scalar(select(AuditLog.note).where(AuditLog.action == "user.disable"))
    assert note == "left the network"
    assert _actions("user") == ["user.update", "user.disable"]
    assert client.get(f"{API}/users", params={"status": "disabled"},
                      headers=h).json()["total"] == 1
    login = client.post("/api/v1/auth/login",
                        json={"email": AGENT_MIRPUR, "password": "test-agent-pw"})
    assert login.status_code == 401
    assert client.patch(url, json={"is_active": True}, headers=h).json()["is_active"] is True
    assert _actions("user")[-1] == "user.enable"


def test_admin_cannot_lock_themselves_out(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    me = client.get(f"{API}/users", params={"role": "admin"}, headers=h).json()["items"][0]
    for body in ({"is_active": False}, {"role": "agent", "agent_id": agent_id("AGT-0001")}):
        res = client.patch(f"{API}/users/{me['id']}", json=body, headers=h)
        assert (res.status_code, res.json()["detail"]) == (409, "cannot_change_self")
    unknown = "00000000-0000-0000-0000-000000000000"
    assert client.patch(f"{API}/users/{unknown}", json={"full_name": "Y"},
                        headers=h).status_code == 404


def test_org_directory(client: TestClient, seeded: Path) -> None:
    body = client.get(f"{API}/org", headers=bearer(client, ADMIN)).json()
    assert [d["code"] for d in body["distributors"]] == ["DST-CTG", "DST-DHK", "DST-SYL"]
    assert len(body["agents"]) == 3 and {"id", "code", "name", "distributor_id"} <= set(
        body["agents"][0])


def test_audit_log_filters_and_export(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    for i in range(3):
        client.post(f"{API}/users", json={"email": f"u{i}@example.org", "full_name": f"=U{i}",
                                          "role": "admin", "password": NEW_PW}, headers=h)
    page = client.get(f"{API}/audit-log", params={"action": "user.create", "page_size": 2},
                      headers=h).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert "user.create" in page["actions"] and "user" in page["entity_types"]
    assert page["items"][0]["user_email"] == ADMIN
    assert page["items"][0]["id"] > page["items"][1]["id"]  # newest first
    none = client.get(f"{API}/audit-log", params={"user": "nobody@"}, headers=h).json()
    assert none["total"] == 0
    future = client.get(f"{API}/audit-log", params={"from": "2999-01-01T00:00:00Z"},
                        headers=h).json()
    assert future["total"] == 0
    csv = client.get(f"{API}/audit-log/export.csv", params={"action": "user.create"}, headers=h)
    assert csv.status_code == 200
    lines = csv.text.lstrip("﻿").strip().splitlines()
    assert len(lines) == 4 and lines[0].startswith("id,created_at")
