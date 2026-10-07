"""Stockout + risk endpoints on hand-made balances and flat forecasts with known answers.

Flat forecasts (q10 = q50 = q90) make every Monte Carlo path identical, so hours and
probabilities are exact: cash 5,500 drained by 1,000/h runs out at 5.5 h, and so on.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.models import Agent, Distributor, FloatSnapshot, Forecast, ModelVersion
from app.models.enums import FloatType, UrbanRural
from app.rules.risk_rules import build_config
from app.services import risk
from ml.data_gen.timeline import SIM_NOW
from ml.registry import DEPENDENCE_FILE, FORECAST_MODEL
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, AGENT_PATIYA, DIST_DHAKA, agent_id, bearer

API = "/api/v1"
NOW = SIM_NOW.astimezone(UTC)
BIG = 1_000_000
# code -> (cash balance, e-money balance, cash_out per hour, cash_in per hour)
SCENARIOS: dict[str, tuple[float, float, float, float]] = {
    "AGT-0001": (5_500, BIG, 1_000, 0),  # cash out at 5.5 h -> red at 6/24/72
    "AGT-0002": (BIG, BIG, 0, 0),  # never -> green
    "AGT-0003": (30_000, BIG, 1_000, 0),  # cash out at 30 h -> green 6/24, red 72
    "AGT-9001": (BIG, 10_000, 0, 1_000),  # e-money out at 10 h -> green 6, red 24/72
    "AGT-9002": (BIG, BIG, 0, 0),
}
EXTRA = {"AGT-9001": ("Karwan Bazar Point", "Tejgaon"),
         "AGT-9002": ("Uttara Sector 7 Store", "Uttara")}


def _add_extra_agents(session: Session) -> None:
    dhk = session.scalar(select(Distributor.id).where(Distributor.code == "DST-DHK"))
    assert dhk is not None
    for code, (name, upazila) in EXTRA.items():
        session.add(Agent(code=code, name=name, distributor_id=dhk, region="Dhaka",
                          district="Dhaka", upazila=upazila, urban_rural=UrbanRural.urban, tier=2,
                          lat=23.8, lng=90.4, cash_capacity=Decimal("100000"),
                          emoney_capacity=Decimal("100000")))
    session.flush()


def _forecast_rows(mv: int, agent: int, cash_out: float, cash_in: float) -> list[dict[str, Any]]:
    rows = []
    for ft, v in ((FloatType.cash, cash_out), (FloatType.emoney, cash_in)):
        rows += [{"model_version_id": mv, "agent_id": agent, "float_type": ft,
                  "ts": NOW + timedelta(hours=h - 1), "horizon_h": h, "q_low": v, "q_mid": v,
                  "q_high": v, "generated_at": NOW} for h in range(1, 73)]
    return rows


@pytest.fixture
def cache(seeded: Path) -> Path:
    with Session(get_engine()) as session, session.begin():
        _add_extra_agents(session)
        mv = ModelVersion(model_name=FORECAST_MODEL, version="test-flat", trained_at=NOW,
                          artifact_sha256="0" * 64, metrics={}, is_active=True)
        session.add(mv)
        session.flush()
        ids = dict(session.execute(select(Agent.code, Agent.id)).tuples().all())
        for code, (cash, em, out, cin) in SCENARIOS.items():
            session.add(FloatSnapshot(agent_id=ids[code], ts=NOW, cash_balance=Decimal(cash),
                                      emoney_balance=Decimal(em)))
            session.execute(insert(Forecast), _forecast_rows(mv.id, ids[code], out, cin))
        assert risk.precompute(session, build_config(), seed=42) == len(SCENARIOS)
    return seeded


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _levels(body: dict[str, Any], float_type: str) -> list[tuple[int, float, str]]:
    f = next(f for f in body["floats"] if f["float_type"] == float_type)
    return [(h["horizon_h"], h["probability"], h["level"]) for h in f["horizons"]]


def test_stockout_known_answer(client: TestClient, cache: Path) -> None:
    res = client.get(f"{API}/agents/{agent_id('AGT-0001')}/stockout",
                     headers=bearer(client, AGENT_MIRPUR))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["model_version"] == "test-flat" and body["generated_at"]
    assert _iso(body["as_of"]) == NOW
    cash, em = body["floats"]
    assert (cash["float_type"], cash["balance"], cash["capacity"]) == ("cash", 5500, 400000)
    assert cash["hours_to_stockout"] == 5.5 and cash["confidence"] == 1.0
    assert _iso(cash["stockout_at"]) == NOW + timedelta(hours=5.5)
    assert em["stockout_at"] is None and em["hours_to_stockout"] is None
    assert em["confidence"] == 1.0


def test_risk_levels_known_answer(client: TestClient, cache: Path) -> None:
    headers = bearer(client, ADMIN)
    body = client.get(f"{API}/agents/{agent_id('AGT-0003')}/risk", headers=headers).json()
    assert _levels(body, "cash") == [(6, 0.0, "green"), (24, 0.0, "green"), (72, 1.0, "red")]
    assert _levels(body, "emoney") == [(6, 0.0, "green"), (24, 0.0, "green"), (72, 0.0, "green")]
    # Headline = 24 h: the 72 h red stays visible in by_horizon only.
    assert body["level"] == "green" and body["model_version"] == "test-flat"
    assert [f["level"] for f in body["floats"]] == ["green", "green"]
    assert [(h["horizon_h"], h["level"]) for h in body["by_horizon"]] == [
        (6, "green"), (24, "green"), (72, "red")]
    body = client.get(f"{API}/agents/{agent_id('AGT-9001')}/risk", headers=headers).json()
    assert _levels(body, "emoney") == [(6, 0.0, "green"), (24, 1.0, "red"), (72, 1.0, "red")]
    assert body["level"] == "red"


def test_summary(client: TestClient, cache: Path) -> None:
    res = client.get(f"{API}/agents/{agent_id('AGT-0001')}/summary",
                     headers=bearer(client, DIST_DHAKA))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["agent"]["code"] == "AGT-0001" and body["level"] == "red"
    assert body["model_version"] == "test-flat" and body["generated_at"]
    cash = body["floats"][0]
    assert cash["level"] == "red" and cash["hours_to_stockout"] == 5.5
    assert [h["level"] for h in cash["horizons"]] == ["red", "red", "red"]
    assert body["floats"][1]["level"] == "green"


def _codes(client: TestClient, headers: dict[str, str], **params: Any) -> list[str]:
    res = client.get(f"{API}/agents/risk", params=params, headers=headers)
    assert res.status_code == 200, res.text
    return [r["code"] for r in res.json()["items"]]


def test_list_sort_filter_search(client: TestClient, cache: Path) -> None:
    h = bearer(client, ADMIN)
    assert _codes(client, h) == ["AGT-0001", "AGT-9001", "AGT-0003", "AGT-0002", "AGT-9002"]
    assert _codes(client, h, horizon=72, level="red") == ["AGT-0001", "AGT-9001", "AGT-0003"]
    assert _codes(client, h, horizon=6, level="red") == ["AGT-0001"]
    assert _codes(client, h, level="amber") == []
    assert _codes(client, h, sort="stockout") == [
        "AGT-0001", "AGT-9001", "AGT-0003", "AGT-0002", "AGT-9002"]
    assert _codes(client, h, sort="name")[0] == "AGT-9001"  # Karwan Bazar Point
    assert _codes(client, h, q="uttara") == ["AGT-9002"]
    assert _codes(client, h, q="%") == []
    row = client.get(f"{API}/agents/risk", headers=h).json()["items"][0]
    assert (row["level"], row["probability"], row["worst_float"]) == ("red", 1.0, "cash")
    assert row["hours_to_stockout"] == 5.5


def test_list_pagination(client: TestClient, cache: Path) -> None:
    h = bearer(client, ADMIN)
    pages = [client.get(f"{API}/agents/risk", params={"page": p, "page_size": 2},
                        headers=h).json() for p in (1, 2, 3, 4)]
    assert [len(p["items"]) for p in pages] == [2, 2, 1, 0]
    assert {p["total"] for p in pages} == {5}
    assert pages[0]["page_size"] == 2 and pages[1]["page"] == 2
    assert pages[0]["horizon_h"] == 24 and pages[0]["model_version"] == "test-flat"
    for bad in ({"horizon": 12}, {"page": 0}, {"page_size": 101}, {"sort": "bogus"},
                {"level": "yellow"}):
        assert client.get(f"{API}/agents/risk", params=bad, headers=h).status_code == 422


def test_list_is_role_scoped(client: TestClient, cache: Path) -> None:
    dist = _codes(client, bearer(client, DIST_DHAKA), sort="code")
    assert dist == ["AGT-0001", "AGT-9001", "AGT-9002"]
    assert _codes(client, bearer(client, AGENT_MIRPUR)) == ["AGT-0001"]
    assert client.get(f"{API}/agents/risk").status_code == 401


def test_per_agent_scoping(client: TestClient, cache: Path) -> None:
    own, other = agent_id("AGT-0001"), agent_id("AGT-0002")
    patiya = bearer(client, AGENT_PATIYA)
    dist = bearer(client, DIST_DHAKA)
    for path in ("summary", "stockout", "risk"):
        assert client.get(f"{API}/agents/{own}/{path}").status_code == 401
        assert client.get(f"{API}/agents/{own}/{path}", headers=patiya).status_code == 403
        assert client.get(f"{API}/agents/{other}/{path}", headers=patiya).status_code == 200
        assert client.get(f"{API}/agents/{other}/{path}", headers=dist).status_code == 403


def test_precompute_is_idempotent(cache: Path) -> None:
    with Session(get_engine()) as session, session.begin():
        assert risk.precompute(session, build_config(), seed=42) == 0
        assert risk.precompute(session, build_config({24: [0.1, 0.2]}), seed=42) == 5


def test_not_ready_without_cache(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    assert client.get(f"{API}/agents/risk", headers=h).json()["detail"] == "risk_not_ready"
    for path in ("summary", "stockout", "risk"):
        res = client.get(f"{API}/agents/{agent_id('AGT-0001')}/{path}", headers=h)
        assert res.status_code == 503


def test_refill_aware_view_is_extra_and_leaves_the_decision_alone(
        client: TestClient, cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the estimated copula in the artifacts, the stockout view gains `refill_aware`;
    risk levels and the no-refill stockout time stay the decision input."""
    art = cache / "artifacts_dep"
    art.mkdir()
    dep = {"rho_out": 0.1, "rho_in": 0.1, "cross_path": 0.5, "cross_hour": 0.0, "n_paths": 1}
    (art / DEPENDENCE_FILE).write_text(json.dumps({"pooled": dep, "segments": {}}),
                                       encoding="utf-8")
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    get_settings.cache_clear()
    with Session(get_engine()) as session, session.begin():
        assert risk.precompute(session, build_config(), seed=42, force=True) == len(SCENARIOS)
    h = bearer(client, AGENT_MIRPUR)
    body = client.get(f"{API}/agents/{agent_id('AGT-0001')}/stockout", headers=h).json()
    cash = body["floats"][0]
    assert cash["hours_to_stockout"] == 5.5  # decision input unchanged
    # No refill in the (one-hour) history: the refill-aware view agrees, flat demand is exact.
    assert cash["refill_aware"] == {"stockout_at": cash["stockout_at"],
                                    "hours_to_stockout": 5.5, "probability_24h": 1.0}
    risk_body = client.get(f"{API}/agents/{agent_id('AGT-0001')}/risk", headers=h).json()
    assert _levels(risk_body, "cash")[1] == (24, 1.0, "red")
