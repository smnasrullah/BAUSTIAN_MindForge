"""Copilot conversations: per-user scoping, redaction before saving, LLM history trimmed to 10."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.llm.copilot import support
from app.models import User
from app.services import copilot_history as history
from tests.auth_helpers import AGENT_MIRPUR, AGENT_PATIYA, bearer

BASE = "/api/v1/copilot/conversations"


def test_conversations_are_scoped_to_owner(client: TestClient, seeded: Path) -> None:
    owner, other = bearer(client, AGENT_MIRPUR), bearer(client, AGENT_PATIYA)
    conv = client.post(BASE, json={"title": "Cash-out failed"}, headers=owner).json()
    assert client.post(f"{BASE}/{conv['id']}/messages", headers=owner,
                       json={"role": "user", "content": "cash-out failed"}).status_code == 201
    assert [c["id"] for c in client.get(BASE, headers=owner).json()] == [conv["id"]]
    assert client.get(BASE, headers=other).json() == []
    assert client.get(f"{BASE}/{conv['id']}/messages", headers=other).status_code == 404
    assert client.post(f"{BASE}/{conv['id']}/messages", headers=other,
                       json={"role": "user", "content": "hi"}).status_code == 404


def test_phone_pin_otp_redacted_before_saving(client: TestClient, seeded: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    conv = client.post(BASE, json={}, headers=h).json()
    text = "Customer 01712345678 said my PIN is 4821 and OTP: ৫৫৬৬৭৭, cash-out 5000 failed"
    client.post(f"{BASE}/{conv['id']}/messages", json={"role": "user", "content": text}, headers=h)
    saved = client.get(f"{BASE}/{conv['id']}/messages", headers=h).json()[0]["content"]
    for secret in ("01712345678", "4821", "৫৫৬৬৭৭"):
        assert secret not in saved
    assert "5000" in saved  # amounts are kept
    assert support.redact("+880 1812-345678") == "[phone]"


def test_llm_history_keeps_last_ten(seeded: Path) -> None:
    with Session(get_engine()) as session:
        user = session.scalars(select(User).where(User.email == AGENT_MIRPUR)).one()
        conv = history.create(session, user.id)
        for i in range(14):
            history.append(session, conv, "user" if i % 2 == 0 else "assistant", f"turn {i}")
        lines = (history.llm_history(session, conv) or "").splitlines()
        session.rollback()
    assert len(lines) == history.LLM_HISTORY
    assert lines[0].endswith("turn 4") and lines[-1].endswith("turn 13")
