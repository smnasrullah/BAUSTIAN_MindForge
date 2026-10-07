"""POST /agents/{id}/whatif on the hand-made market (flat forecasts -> exact answers).

AGT-0001: cash 5,500 drained by 1,000/h, capacity 400,000 -> runs out at 5.5 h.
"""

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.enums import RiskLevelCode
from app.rules.risk_rules import SEVERITY
from app.services import whatif as whatif_service
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, AGENT_PATIYA, DIST_DHAKA, agent_id, bearer
from tests.rebalance_helpers import build_market

API = "/api/v1"


@pytest.fixture
def market(seeded: Path) -> Path:
    build_market()
    return seeded


def _whatif(client: TestClient, headers: dict[str, str], code: str = "AGT-0001",
            **body: Any) -> Any:
    payload = {"float_type": "cash", "delta_amount": 0, **body}
    return client.post(f"{API}/agents/{agent_id(code)}/whatif", json=payload, headers=headers)


def test_before_equals_cache_and_after_moves_runway(client: TestClient, market: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    res = _whatif(client, h, delta_amount=2_000)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["model_version"] == "test-flat" and body["generated_at"]
    assert body["advisory"] is True and body["capacity"] == 400_000
    cached = client.get(f"{API}/agents/{agent_id('AGT-0001')}/stockout", headers=h).json()
    risk = client.get(f"{API}/agents/{agent_id('AGT-0001')}/risk", headers=h).json()
    cash = cached["floats"][0]
    before, after = body["before"], body["after"]
    assert (before["balance"], before["hours_to_stockout"], before["confidence"]) == (
        cash["balance"], cash["hours_to_stockout"], cash["confidence"])
    assert before["stockout_at"] == cash["stockout_at"]
    assert before["horizons"] == risk["floats"][0]["horizons"]
    assert after["balance"] == 7_500 and after["hours_to_stockout"] == 7.5
    assert [(r["horizon_h"], r["level"]) for r in after["horizons"]] == [
        (6, "green"), (24, "red"), (72, "red")]
    assert before["horizons"][0]["level"] == "red"


def test_series_for_the_runway_ghost(client: TestClient, market: Path) -> None:
    body = _whatif(client, bearer(client, DIST_DHAKA), delta_amount=2_000).json()
    before, after = body["before"]["series"], body["after"]["series"]
    assert [p["hour"] for p in before] == list(range(73))
    assert before[0]["expected"] == 5_500 and after[0]["expected"] == 7_500
    assert before[5]["expected"] == 500 and after[5]["expected"] == 2_500
    assert before[6]["expected"] == 0 and after[7]["expected"] == 500
    assert before[-1]["low"] == before[-1]["high"] == 0
    assert before[0]["ts"] == body["as_of"] and before[1]["ts"] > before[0]["ts"]


def _hours(s: dict[str, Any]) -> float:
    return float("inf") if s["hours_to_stockout"] is None else float(s["hours_to_stockout"])


def test_positive_delta_never_worsens_risk(client: TestClient, market: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    base = _whatif(client, h).json()["before"]
    prev = base
    for delta in (0, 100, 1_000, 10_000, 100_000, 394_500):
        after = _whatif(client, h, delta_amount=delta).json()["after"]
        assert _hours(after) >= _hours(prev)
        assert SEVERITY[RiskLevelCode(after["level"])] <= SEVERITY[RiskLevelCode(prev["level"])]
        for a, b in zip(after["horizons"], prev["horizons"], strict=True):
            assert a["probability"] <= b["probability"]
            assert SEVERITY[RiskLevelCode(a["level"])] <= SEVERITY[RiskLevelCode(b["level"])]
        assert all(a["expected"] >= b["expected"]
                   for a, b in zip(after["series"], prev["series"], strict=True))
        prev = after
    assert prev["hours_to_stockout"] is None and prev["level"] == "green"


def test_bounds_are_validated(client: TestClient, market: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    for delta in (-5_501, 394_501):
        res = _whatif(client, h, delta_amount=delta)
        assert res.status_code == 422 and res.json()["detail"] == "delta_out_of_bounds"
    assert _whatif(client, h, delta_amount=-5_500).status_code == 200  # down to exactly 0
    assert _whatif(client, h, delta_amount=394_500).status_code == 200  # up to capacity
    for bad in ({"delta_amount": 1e12}, {"float_type": "gold"}, {"delta_amount": "lots"}):
        assert _whatif(client, h, **bad).status_code == 422
    res = client.post(f"{API}/agents/{agent_id('AGT-0001')}/whatif", json={}, headers=h)
    assert res.status_code == 422


def test_latency_under_300_ms(client: TestClient, market: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    assert _whatif(client, h, delta_amount=1_000).status_code == 200  # warm-up
    for delta in (500, 5_000, 50_000, -2_000, 0):
        start = time.perf_counter()
        res = _whatif(client, h, float_type="emoney", delta_amount=delta)
        elapsed = time.perf_counter() - start
        assert res.status_code == 200, res.text
        assert elapsed < 0.3, f"what-if took {elapsed * 1000:.0f} ms"


def test_scoping(client: TestClient, market: Path) -> None:
    assert _whatif(client, {}).status_code == 401
    assert _whatif(client, bearer(client, AGENT_PATIYA)).status_code == 403  # other agent
    assert _whatif(client, bearer(client, AGENT_PATIYA), "AGT-0002").status_code == 200
    assert _whatif(client, bearer(client, DIST_DHAKA), "AGT-0002").status_code == 403
    assert _whatif(client, bearer(client, DIST_DHAKA), "AGT-9001").status_code == 200
    assert _whatif(client, bearer(client, ADMIN)).status_code == 403  # A(self), D only


def test_not_ready_without_cache(client: TestClient, seeded: Path) -> None:
    res = _whatif(client, bearer(client, AGENT_MIRPUR))
    assert res.status_code == 503 and res.json()["detail"] == "risk_not_ready"


def test_cached_paths_match_a_fresh_computation(client: TestClient, market: Path) -> None:
    """Slider moves reuse each worker's sampled paths (services/whatif); answers are unchanged."""
    h = bearer(client, AGENT_MIRPUR)

    def numbers(delta: float) -> dict[str, Any]:
        body = _whatif(client, h, delta_amount=delta).json()
        return {k: body[k] for k in ("before", "after", "capacity", "as_of")}

    _whatif(client, h, delta_amount=1_000)  # warms the cache for this agent and float
    cached = [numbers(d) for d in (3_000, -1_000, 9_000)]
    whatif_service._paths.clear()
    fresh = []
    for d in (3_000, -1_000, 9_000):
        whatif_service._paths.clear()
        fresh.append(numbers(d))
    assert cached == fresh
