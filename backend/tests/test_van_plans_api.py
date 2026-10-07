import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import AuditLog, User
from app.rules.van_routing.cost import EPS
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, agent_id, bearer
from tests.van_api_helpers import SHORT, build_van_market

API = "/api/v1/distributor/van-plans"
DIST_CTG = "dist.chattogram@agentpulse.demo"
BODY = {"options": {"time_limit_s": 5}}


@pytest.fixture
def van_market(seeded: Path) -> Path:
    build_van_market()
    return seeded


def _create(client: TestClient, email: str = DIST_DHAKA, **body: Any) -> dict[str, Any]:
    res = client.post(API, json=BODY | body, headers=bearer(client, email))
    assert res.status_code == 201, res.text
    out: dict[str, Any] = res.json()
    return out


def _stops(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for r in plan["routes"] for s in r["stops"]] + plan["unrouted"]


def _audit(plan_id: int) -> list[AuditLog]:
    with Session(get_engine()) as session:
        return list(session.scalars(select(AuditLog).where(
            AuditLog.entity_type == "van_plan", AuditLog.entity_id == str(plan_id))
            .order_by(AuditLog.id)))


def test_plan_serves_own_agents_with_reasons(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    assert plan["status"] == "pending" and plan["advisory"] is True and not plan["reused"]
    assert plan["model_version"] == "test-flat" and plan["generated_at"]
    assert plan["distance_source"] == "estimate"  # test agents are not in the road cache
    assert all(leg["source"] == "estimate" for r in plan["routes"] for leg in r["legs"])
    assert plan["solver"] == "ortools" and plan["solve_ms"] < 5_000
    assert plan["depot"]["code"] == "DST-DHK" and plan["depot"]["name"]
    assert -90 < plan["depot"]["lat"] < 90 and -180 < plan["depot"]["lng"] < 180
    codes = {s["agent_code"]: s for s in _stops(plan)}
    assert set(codes) == set(SHORT) | {"AGT-0001"}, "own agents only (AGT-0002 is Chattogram)"
    assert codes["AGT-0001"]["status"] == "dropped"
    assert codes["AGT-0001"]["reason"] == "swap_suggested"
    for s in _stops(plan):
        assert (s["status"] == "planned") != (s["reason"] is not None)
        assert s["source_quantile"] in ("q50", "q90") and s["deadline"]
        if s["agent_code"] in SHORT:
            assert s["source_quantile"] == "q90", "red risk: pessimistic q90 amount"
    cfg = plan["params"]["config"]
    assert cfg["vehicles"] >= 2
    for r in plan["routes"]:
        assert r["cash_load_bdt"] <= min(cfg["capacity_bdt"], cfg["cash_cap_bdt"]) + EPS
        assert [s["seq"] for s in r["stops"]] == list(range(1, len(r["stops"]) + 1))
        assert all(s["eta_lo"] < s["eta_hi"] for s in r["stops"]), "ETA is a range"
    o, base = plan["objective"], plan["separate_trips"]
    assert o["total_bdt"] <= base["total_bdt"] + EPS and plan["trips"] <= 2
    assert plan["served"] + plan["dropped"] == len(codes)
    assert plan["fairness"] and all(g["ok"] for g in plan["fairness"])
    assert plan["stockout_p_limit"] == 0.3 and plan["choice"]


def test_same_inputs_reuse_the_pending_plan(client: TestClient, van_market: Path) -> None:
    first = _create(client)
    again = _create(client)
    assert again["reused"] and again["id"] == first["id"]
    other = _create(client, vehicles={"count": 3})
    assert other["id"] != first["id"] and not other["reused"]
    h = bearer(client, DIST_DHAKA)
    old = client.get(f"{API}/{first['id']}", headers=h).json()
    assert old["status"] == "superseded"


def test_role_scoping(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    url = f"{API}/{plan['id']}"
    admin, agent, ctg = (bearer(client, e) for e in (ADMIN, AGENT_MIRPUR, DIST_CTG))
    # Admin: read only.
    assert client.get(API, headers=admin).json()["total"] == 1
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(f"{url}/narrative", headers=admin).status_code == 200
    assert client.post(API, json=BODY, headers=admin).status_code == 403
    assert client.post(f"{url}/decision", json={"decision": "approve", "note": "x"},
                       headers=admin).status_code == 403
    stop_id = plan["routes"][0]["stops"][0]["id"]
    assert client.post(f"{url}/stops/{stop_id}/delivered", json={"delivered_amount_bdt": 1},
                       headers=admin).status_code == 403
    # Agents never get route details.
    for res in (client.get(API, headers=agent), client.get(url, headers=agent),
                client.post(API, json=BODY, headers=agent),
                client.get(f"{url}/narrative", headers=agent)):
        assert res.status_code == 403
    # Another distributor: cannot see or decide this plan; its own plan has none of these agents.
    assert client.get(url, headers=ctg).status_code == 403
    assert client.post(f"{url}/decision", json={"decision": "approve", "note": "x"},
                       headers=ctg).status_code == 403
    assert client.get(API, headers=ctg).json()["total"] == 0
    theirs = _create(client, DIST_CTG)
    assert {s["agent_code"] for s in _stops(theirs)} <= {"AGT-0002"}
    assert agent_id("AGT-0002") in {s["agent_id"] for s in _stops(theirs)}
    assert client.get(API, headers=admin, params={"distributor_id": plan["distributor_id"]}
                      ).json()["total"] == 1
    assert client.get(API).status_code == 401


def test_decision_needs_note_and_writes_audit(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    url, h = f"{API}/{plan['id']}", bearer(client, DIST_DHAKA)
    for bad in ({"decision": "approve"}, {"decision": "approve", "note": "  "},
                {"decision": "maybe", "note": "x"}):
        assert client.post(f"{url}/decision", json=bad, headers=h).status_code == 422
    stop_id = plan["routes"][0]["stops"][0]["id"]
    early = client.post(f"{url}/stops/{stop_id}/delivered", json={"delivered_amount_bdt": 1},
                        headers=h)
    assert early.status_code == 409 and early.json()["detail"] == "plan_not_approved"
    res = client.post(f"{url}/decision", json={"decision": "approve", "note": "Van 1 at 10"},
                      headers=h)
    assert res.status_code == 200 and res.json()["status"] == "approved"
    assert res.json()["note"] == "Van 1 at 10" and res.json()["decided_by"]
    again = client.post(f"{url}/decision", json={"decision": "reject", "note": "x"}, headers=h)
    assert again.status_code == 409 and again.json()["detail"] == "already_decided"
    with Session(get_engine()) as session:
        dist_id = session.scalar(select(User.id).where(User.email == DIST_DHAKA))
    (entry,) = _audit(plan["id"])
    assert (entry.action, entry.user_id, entry.note) == ("van_plan.approve", dist_id,
                                                         "Van 1 at 10")
    assert entry.payload["total_bdt"] == plan["total_bdt"]
    # Plan-vs-actual feedback, once per stop.
    done = client.post(f"{url}/stops/{stop_id}/delivered",
                       json={"delivered_amount_bdt": 55_000, "note": "short by 5k"}, headers=h)
    assert done.status_code == 200
    stop = next(s for r in done.json()["routes"] for s in r["stops"] if s["id"] == stop_id)
    assert (stop["status"], stop["delivered_amount_bdt"]) == ("delivered", 55_000)
    twice = client.post(f"{url}/stops/{stop_id}/delivered", json={"delivered_amount_bdt": 1},
                        headers=h)
    assert twice.status_code == 409 and twice.json()["detail"] == "stop_not_planned"
    assert [e.action for e in _audit(plan["id"])] == ["van_plan.approve",
                                                      "van_plan.stop_delivered"]
    assert client.post(f"{url}/stops/999999/delivered", json={"delivered_amount_bdt": 1},
                       headers=h).status_code == 403


def test_narrative_is_template_in_both_languages(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    h = bearer(client, DIST_DHAKA)
    en = client.get(f"{API}/{plan['id']}/narrative", headers=h).json()
    bn = client.get(f"{API}/{plan['id']}/narrative", params={"lang": "bn"}, headers=h).json()
    for out in (en, bn):
        assert out["generated_by"] == "template" and out["model_version"] == "test-flat"
        assert out["distance_source"] == "estimate" and out["generated_at"]
    assert f"{plan['trips']} van trip(s)" in en["text"] and "separate trip" in en["text"]
    assert "1 covered by a swap" in en["text"] and "estimates" in en["text"]
    assert "ভ্যান" in bn["text"] and "১" in bn["text"]


def test_not_ready_without_forecasts(client: TestClient, seeded: Path) -> None:
    res = client.post(API, json=BODY, headers=bearer(client, DIST_DHAKA))
    assert res.status_code == 503 and res.json()["detail"] == "van_not_ready"


def test_bad_bodies_are_rejected(client: TestClient, seeded: Path) -> None:
    h = bearer(client, DIST_DHAKA)
    for bad in ({"horizon_h": 0}, {"vehicles": {"count": 0}}, {"vehicles": {"capacity_bdt": -1}},
                {"options": {"time_limit_s": 99}}, {"unknown": 1}):
        assert client.post(API, json=bad, headers=h).status_code == 422


def test_hourly_tick_does_not_load_van_solving() -> None:
    # The table definitions (app.models.van_plan) load with every model; solving code must not.
    code = ("import sys, app.services.data_clock, app.services.pipeline, "
            "app.services.data_scheduler; print(sorted(m for m in sys.modules if m.startswith("
            "('app.rules.van_routing', 'app.services.van_', 'ortools'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, cwd=Path(__file__).resolve().parents[1])
    assert out.stdout.strip() == "[]", out.stdout
