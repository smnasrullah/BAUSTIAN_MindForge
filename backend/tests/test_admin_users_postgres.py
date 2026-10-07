"""Admin and input edge cases on a real Postgres (skipped unless TEST_POSTGRES_URL):
- two admins approve and reject the same pending signup at once: exactly one decision wins,
  the account ends in one consistent state, and the audit log holds one decision;
- a NUL character in a text filter (found by fuzzing) is a 422, not a 500.
"""

import threading

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import AuditLog, User
from app.schemas.admin import AdminUserUpdate
from app.services import admin_users
from app.services.admin_users import UserAdminError
from tests.auth_helpers import ADMIN, DIST_DHAKA, agent_id, bearer
from tests.test_help_postgres import pg, pg_client, pytestmark  # noqa: F401 - fixtures + skip

ROUNDS = 5


def _pending(client: TestClient, n: int) -> User:
    email = f"race.{n}@example.org"
    body = {"full_name": "Race Person", "email": email, "password": "race-pass-2026"}
    assert client.post("/api/v1/auth/signup", json=body).status_code == 202
    with Session(get_engine()) as session:
        u = session.scalar(select(User).where(User.email == email))
        assert u is not None and u.is_pending
        return u


def test_approve_and_reject_at_once_have_one_winner(pg_client: TestClient) -> None:  # noqa: F811
    aid = agent_id("AGT-0001")
    for n in range(ROUNDS):
        uid = _pending(pg_client, n).id
        barrier = threading.Barrier(2)
        outcome: dict[str, str] = {}

        def act(kind: str, uid: object = uid, barrier: threading.Barrier = barrier,
                outcome: dict[str, str] = outcome) -> None:
            with Session(get_engine()) as session:  # its own pooled connection
                admin = session.scalar(select(User).where(User.email == ADMIN))
                assert admin is not None
                barrier.wait()
                try:
                    if kind == "approve":
                        admin_users.update_user(session, admin, uid,  # type: ignore[arg-type]
                                                AdminUserUpdate(is_active=True, agent_id=aid))
                    else:
                        admin_users.reject(session, admin, uid, "duplicate shop")  # type: ignore[arg-type]
                    session.commit()
                    outcome[kind] = "ok"
                except UserAdminError as exc:
                    session.rollback()
                    outcome[kind] = exc.code

        threads = [threading.Thread(target=act, args=(k,)) for k in ("approve", "reject")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert sorted(outcome.values()).count("ok") == 1, outcome
        with Session(get_engine()) as session:
            u = session.get(User, uid)
            assert u is not None and not u.is_pending
            if outcome["approve"] == "ok":
                assert (u.is_active, u.is_rejected, u.agent_id) == (True, False, aid)
            else:
                assert (u.is_active, u.is_rejected) == (False, True)
            decisions = session.scalars(select(AuditLog.action).where(
                AuditLog.entity_type == "user", AuditLog.entity_id == str(uid))).all()
            assert sum(a in ("user.approve", "user.reject") for a in decisions) == 1, decisions


def test_nul_character_in_a_filter_is_422(pg_client: TestClient) -> None:  # noqa: F811
    res = pg_client.get("/api/v1/events", params={"district": "Dhaka\x00"},
                        headers=bearer(pg_client, DIST_DHAKA))
    assert (res.status_code, res.json()["detail"]) == (422, "invalid_value")
