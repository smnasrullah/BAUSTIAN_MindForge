"""Van plans, should stage: forecast-aware amounts and deadlines, stockout before arrival, pins
(lock / include / exclude) with audit, freeze window, LLM narrative through the guard, and the
van evaluation endpoint."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import AuditLog, LlmCallLog
from app.models.enums import LlmIntent
from app.services import van_eval_read
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, bearer
from tests.test_llm_api import FakeProvider, echo, invents, live, llm_env  # noqa: F401
from tests.van_api_helpers import AMBER, SHORT, STEEP, add_amber_and_curve, build_van_market

API = "/api/v1/distributor/van-plans"
DIST_CTG = "dist.chattogram@agentpulse.demo"
BODY = {"options": {"time_limit_s": 5}}


@pytest.fixture
def van_market(seeded: Path) -> Path:
    build_van_market()
    add_amber_and_curve()
    return seeded


def _create(client: TestClient, **body: Any) -> dict[str, Any]:
    res = client.post(API, json=BODY | body, headers=bearer(client, DIST_DHAKA))
    assert res.status_code == 201, res.text
    out: dict[str, Any] = res.json()
    return out


def _stops(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["agent_code"]: s for r in plan["routes"] for s in r["stops"]} | {
        s["agent_code"]: s for s in plan["unrouted"]}


def _van(plan: dict[str, Any], code: str) -> int | None:
    return next((r["vehicle_no"] for r in plan["routes"] for s in r["stops"]
                 if s["agent_code"] == code), None)


def _pin(client: TestClient, plan: dict[str, Any], code: str, action: str,
         email: str = DIST_DHAKA) -> Any:
    stop_id = _stops(plan)[code]["id"]
    return client.post(f"{API}/{plan['id']}/stops/{stop_id}/{action}", json={"note": "test"},
                       headers=bearer(client, email))


def test_amber_gets_median_amount_and_curve_sets_deadline(client: TestClient,
                                                          van_market: Path) -> None:
    stops = _stops(_create(client))
    amber = stops[AMBER]
    assert (amber["source_quantile"], amber["amount_bdt"]) == ("q50", 67_000)
    steep = stops[STEEP]
    assert steep["deadline_rule"] == "p_limit" and steep["status"] == "planned"
    assert steep["stockout_before_arrival_p"] >= 0.5 and steep["stockout_risk_flag"] is True
    others = [s for c, s in stops.items() if c in SHORT and c != STEEP]
    assert all(s["stockout_before_arrival_p"] is None and s["stockout_risk_flag"] is None
               for s in others), "no curve -> no made-up probability"
    assert all(s["deadline_rule"] == "recommendation" for s in others)


def test_flagged_count_and_narrative_mention(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    assert plan["flagged"] == 1
    text = client.get(f"{API}/{plan['id']}/narrative", headers=bearer(client, DIST_DHAKA)
                      ).json()["text"]
    assert "1 agent(s) may run out of cash before the van arrives" in text


def test_lock_include_exclude_resolve_and_audit(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    code = next(c for c in SHORT if _stops(plan)[c]["status"] == "planned")
    van = _van(plan, code)
    res = _pin(client, plan, code, "lock")
    assert res.status_code == 201, res.text
    locked = res.json()
    assert locked["id"] != plan["id"] and locked["status"] == "pending"
    assert _stops(locked)[code]["pin"] == "lock" and _van(locked, code) == van
    old = client.get(f"{API}/{plan['id']}", headers=bearer(client, DIST_DHAKA)).json()
    assert old["status"] == "superseded"
    excl = _pin(client, locked, code, "exclude").json()
    s = _stops(excl)[code]
    assert (s["status"], s["reason"], s["pin"]) == ("dropped", "excluded", "exclude")
    assert excl["served"] + excl["dropped"] == len(_stops(excl))
    incl = _pin(client, excl, code, "include").json()
    assert _stops(incl)[code]["status"] == "planned" and _stops(incl)[code]["pin"] == "include"
    with Session(get_engine()) as session:
        rows = session.scalars(select(AuditLog).where(AuditLog.entity_type == "van_plan")
                               .order_by(AuditLog.id)).all()
    assert [r.action for r in rows] == ["van_plan.stop_lock", "van_plan.stop_exclude",
                                        "van_plan.stop_include"]
    assert rows[0].entity_id == str(plan["id"]) and rows[0].payload["new_plan_id"] == locked["id"]
    assert all(r.note == "test" for r in rows)


def test_pin_rules(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    swap = _pin(client, plan, "AGT-0001", "include")
    assert swap.status_code == 409 and swap.json()["detail"] == "swap_covered"
    code = next(c for c in SHORT if _stops(plan)[c]["status"] == "planned")
    assert _pin(client, plan, code, "lock", ADMIN).status_code == 403
    assert _pin(client, plan, code, "lock", DIST_CTG).status_code == 403
    assert _pin(client, plan, code, "lock", AGENT_MIRPUR).status_code == 403
    assert _pin(client, plan, code, "maybe").status_code == 422
    h = bearer(client, DIST_DHAKA)
    client.post(f"{API}/{plan['id']}/decision", json={"decision": "approve", "note": "ok"},
                headers=h)
    late = _pin(client, plan, code, "lock")
    assert late.status_code == 409 and late.json()["detail"] == "plan_not_pending"


def test_exclude_then_lock_unrouted_is_refused(client: TestClient, van_market: Path) -> None:
    plan = _create(client)
    code = next(c for c in SHORT if _stops(plan)[c]["status"] == "planned")
    excl = _pin(client, plan, code, "exclude").json()
    res = _pin(client, excl, code, "lock")
    assert res.status_code == 409 and res.json()["detail"] == "stop_not_routed"


def test_freeze_window_keeps_near_stops_on_their_van(client: TestClient,
                                                     van_market: Path) -> None:
    plan = _create(client)
    h = bearer(client, DIST_DHAKA)
    client.post(f"{API}/{plan['id']}/decision", json={"decision": "approve", "note": "go"},
                headers=h)
    start = datetime.fromisoformat(plan["planned_at"])
    near = {s["agent_code"]: r["vehicle_no"] for r in plan["routes"] for s in r["stops"]
            if datetime.fromisoformat(s["eta_lo"]) - start <= timedelta(minutes=30)}
    assert near, "the test market has a first stop within the freeze window"
    nxt = _create(client)
    assert nxt["id"] != plan["id"]
    frozen = {c: s for c, s in _stops(nxt).items() if s["pin"] == "frozen"}
    assert set(frozen) == set(near)
    assert set(nxt["params"]["frozen"]) == {str(s["agent_id"]) for s in frozen.values()}
    for c, s in frozen.items():
        assert s["status"] == "planned" and _van(nxt, c) == near[c]


def test_narrative_goes_through_the_llm_guard(client: TestClient, van_market: Path,
                                              llm_env: Path,  # noqa: F811
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _create(client)
    url, h = f"{API}/{plan['id']}/narrative", bearer(client, DIST_DHAKA)
    off = client.get(url, headers=h).json()
    assert off["generated_by"] == "template"
    fake = live(monkeypatch, FakeProvider(echo))
    ok = client.get(url, headers=h).json()
    assert ok["generated_by"] == "llm" and fake.calls == 1 and ok["text"] == off["text"]
    live(monkeypatch, FakeProvider(invents))
    bad = client.get(url, params={"lang": "bn"}, headers=h).json()
    assert bad["generated_by"] == "template" and bad["fallback_reason"] == "numbers_fail"
    with Session(get_engine()) as session:
        logged = session.scalars(select(LlmCallLog.generated_by).where(
            LlmCallLog.intent == LlmIntent.van_narrative)).all()
    assert "llm" in logged and "template" in logged


def test_van_comparison_endpoint(client: TestClient, seeded: Path, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    url = "/api/v1/impact/van-comparison"
    assert client.get(url, headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    monkeypatch.setattr(van_eval_read, "EVAL_FILE", tmp_path / "missing.json")
    res = client.get(url, headers=bearer(client, ADMIN))
    assert res.status_code == 503 and res.json()["detail"] == "van_eval_missing"
    stat = {"mean": 1.0, "lo": 0.5, "hi": 1.5}
    contrast = {"first": "D_full_model", "second": "C_hard_deadline", "diff_total_bdt": stat,
                "seeds_first_lower": 5, "seeds": 5, "verdict": "lower"}
    doc = {"label": "synthetic data", "model_version": "van-rules-2",
           "generated_at": "2026-10-06T00:00:00+00:00", "distance_source": "estimate",
           "seeds": [1, 2, 3, 4, 5], "instances": 10, "stops": 50,
           "policies": [{"name": "D_full_model", "metrics": {"total_bdt": stat},
                         "service_rate_by_area": {"rural": 0.9}, "drop_reasons": {}}],
           "d_vs_c": contrast, "d_vs_a": contrast, "sensitivity": [], "sensitivity_seed": 1}
    path = tmp_path / "eval.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(van_eval_read, "EVAL_FILE", path)
    body = client.get(url, headers=bearer(client, DIST_DHAKA)).json()
    assert body["label"] == "synthetic data" and body["d_vs_c"]["verdict"] == "lower"
    assert body["model_version"] and body["generated_at"] and body["distance_source"]


def test_committed_van_evaluation_is_valid() -> None:
    """The evaluation file served by the endpoint parses and covers >= 5 seeds, A-D."""
    out = van_eval_read.load()
    assert out is not None and out.label == "synthetic data" and len(out.seeds) >= 5
    assert {p.name for p in out.policies} == {"A_separate_trips", "B_nearest_neighbour",
                                              "C_hard_deadline", "D_full_model"}
    assert {r.factor for r in out.sensitivity} == {"road_factor", "cost_per_km_bdt",
                                                   "delivery_reliability"}
