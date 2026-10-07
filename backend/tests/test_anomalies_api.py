"""Anomaly flags end to end: train on the small synthetic DB, scan at SIM_NOW, list / detail /
review with role scoping and audit_log."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import Anomaly, AuditLog, User
from app.services import anomaly_scan
from ml.data_gen import demo_spec
from ml.inference.anomaly import load_detector
from ml.registry import verify_anomaly
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, DIST_DHAKA, bearer

API = "/api/v1/anomalies"
DIST_CTG = "dist.chattogram@agentpulse.demo"


def _page(client: TestClient, email: str, **params: Any) -> dict[str, Any]:
    res = client.get(API, params=params, headers=bearer(client, email))
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def _demo_id(client: TestClient) -> int:
    items = _page(client, ADMIN)["items"]
    return int(next(i["id"] for i in items if i["agent"]["code"] == demo_spec.ANOMALY_AGENT))


def test_training_writes_verified_artifact_with_metrics(anomaly_artifacts: Path) -> None:
    assert verify_anomaly(anomaly_artifacts) == (True, "ok")


def test_demo_agent_is_flagged_with_reasons(client: TestClient, flagged: Path) -> None:
    body = _page(client, ADMIN)
    assert body["advisory"] is True and body["total"] >= 1
    item = next(i for i in body["items"] if i["agent"]["code"] == demo_spec.ANOMALY_AGENT)
    assert item["status"] == "open" and item["score"] > item["threshold"]
    assert item["model_version"].startswith("iforest-") and item["generated_at"]
    assert item["peer_group"] == "all"  # 8 agents: every tier x area group is under MIN_PEERS
    assert item["reasons"] and item["reasons"][0]["deviation"] >= 2
    # Night structuring shows up as a shifted hourly pattern.
    assert "hour_shift" in {r["feature"] for r in item["reasons"]}
    # Window = the 7 days before SIM_NOW.
    assert item["window_end"].startswith("2026-04-30T14:00")
    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)


def test_list_is_scoped_filtered_and_paged(client: TestClient, flagged: Path) -> None:
    total = _page(client, ADMIN)["total"]
    dhaka = _page(client, DIST_DHAKA)
    assert demo_spec.ANOMALY_AGENT in {i["agent"]["code"] for i in dhaka["items"]}
    ctg = _page(client, DIST_CTG)
    assert dhaka["total"] + ctg["total"] <= total
    assert demo_spec.ANOMALY_AGENT not in {i["agent"]["code"] for i in ctg["items"]}
    assert _page(client, ADMIN, status="open")["total"] == total
    assert _page(client, ADMIN, status="confirmed")["total"] == 0
    assert _page(client, ADMIN, page=2, page_size=total)["items"] == []
    assert client.get(API).status_code == 401
    assert client.get(API, headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    h = bearer(client, ADMIN)
    for bad in ({"status": "closed"}, {"page": 0}, {"page_size": 101}):
        assert client.get(API, params=bad, headers=h).status_code == 422


def test_detail_has_peer_distribution(client: TestClient, flagged: Path) -> None:
    anomaly_id = _demo_id(client)
    res = client.get(f"{API}/{anomaly_id}", headers=bearer(client, DIST_DHAKA))
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["peer_count"] == 8 and d["window_h"] == 168 and d["history_h"] == 672
    names = [f["name"] for f in d["features"]]
    # The trained detector's own measures: the four base ones, then any burst measures it chose.
    assert names == list(load_detector(flagged).spec.raw_names)
    assert names[:4] == ["cash_out_growth", "hour_shift", "refills_per_day", "out_in_log_ratio"]
    assert set(names[4:]) <= {"burst_peak_ratio", "burst_days", "rate_change"}
    for f in d["features"]:
        assert f["p10"] <= f["p25"] <= f["p50"] <= f["p75"] <= f["p90"]
        assert 0 <= f["percentile"] <= 100
    assert d["peer_scores"]["max"] >= d["score"] >= d["peer_scores"]["p50"]
    assert d["context"]["cash_out_bdt"] > 0 and d["reviewed_by"] is None
    assert d["advisory"] is True


def test_detail_scoping(client: TestClient, flagged: Path) -> None:
    anomaly_id = _demo_id(client)
    assert client.get(f"{API}/{anomaly_id}",
                      headers=bearer(client, DIST_CTG)).status_code == 403
    assert client.get(f"{API}/{anomaly_id}",
                      headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    assert client.get(f"{API}/999999", headers=bearer(client, DIST_DHAKA)).status_code == 403
    res = client.get(f"{API}/999999", headers=bearer(client, ADMIN))
    assert (res.status_code, res.json()["detail"]) == (404, "anomaly_not_found")


def test_review_is_audited_and_final(client: TestClient, flagged: Path) -> None:
    anomaly_id = _demo_id(client)
    url, h = f"{API}/{anomaly_id}/review", bearer(client, DIST_DHAKA)
    for bad in ({"decision": "confirmed"}, {"decision": "confirmed", "note": "  "},
                {"decision": "fraud", "note": "x"}):
        assert client.post(url, json=bad, headers=h).status_code == 422
    assert client.post(url, json={"decision": "confirmed", "note": "x"},
                       headers=bearer(client, AGENT_MIRPUR)).status_code == 403
    assert client.post(url, json={"decision": "confirmed", "note": "x"},
                       headers=bearer(client, DIST_CTG)).status_code == 403
    res = client.post(url, json={"decision": "confirmed", "note": " Visited shop; logs odd. "},
                      headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["status"], body["note"]) == ("confirmed", "Visited shop; logs odd.")
    assert body["reviewed_at"] and body["reviewed_by"]
    again = client.post(url, json={"decision": "dismissed", "note": "changed mind"}, headers=h)
    assert (again.status_code, again.json()["detail"]) == (409, "already_reviewed")
    with Session(get_engine()) as session:
        (log,) = session.scalars(select(AuditLog).where(
            AuditLog.entity_type == "anomaly", AuditLog.entity_id == str(anomaly_id))).all()
        reviewer = session.scalar(select(User.id).where(User.email == DIST_DHAKA))
    assert (log.action, log.user_id, log.note) == ("anomaly.confirmed", reviewer,
                                                   "Visited shop; logs odd.")
    assert log.payload["status"] == "confirmed" and log.payload["model_version"]
    assert _page(client, ADMIN, status="confirmed")["total"] == 1


def test_admin_can_dismiss(client: TestClient, flagged: Path) -> None:
    anomaly_id = _demo_id(client)
    res = client.post(f"{API}/{anomaly_id}/review",
                      json={"decision": "dismissed", "note": "Known Eid stock-up"},
                      headers=bearer(client, ADMIN))
    assert res.status_code == 200 and res.json()["status"] == "dismissed"


def test_rescan_keeps_reviewed_flag_without_duplicate(client: TestClient, flagged: Path) -> None:
    anomaly_id = _demo_id(client)
    client.post(f"{API}/{anomaly_id}/review", json={"decision": "confirmed", "note": "ok"},
                headers=bearer(client, ADMIN))
    before = _page(client, ADMIN)["total"]
    with Session(get_engine()) as session, session.begin():
        assert anomaly_scan.precompute(session, flagged) == 0  # cache current: no-op
        anomaly_scan.precompute(session, flagged, force=True)
    with Session(get_engine()) as session:
        rows = session.scalar(select(func.count()).select_from(Anomaly))
    assert rows == before == _page(client, ADMIN)["total"]
    statuses = {i["id"]: i["status"] for i in _page(client, ADMIN)["items"]}
    assert statuses[anomaly_id] == "confirmed"


def test_not_ready_without_scan(client: TestClient, seeded: Path) -> None:
    res = client.get(API, headers=bearer(client, ADMIN))
    assert (res.status_code, res.json()["detail"]) == (503, "anomalies_not_ready")


def _anomaly_notes(client: TestClient, email: str) -> list[dict[str, Any]]:
    res = client.get("/api/v1/notifications", headers=bearer(client, email))
    assert res.status_code == 200, res.text
    return [i for i in res.json()["items"] if i["type"] == "anomaly"]


def test_new_flags_notify_own_distributor_once(client: TestClient, flagged: Path) -> None:
    (note,) = _anomaly_notes(client, DIST_DHAKA)
    assert note["title_key"] == "notifications.anomalies_new"
    assert note["params"]["count"] == _page(client, DIST_DHAKA)["total"]
    ctg = _anomaly_notes(client, DIST_CTG)
    assert sum(int(n["params"]["count"]) for n in ctg) == _page(client, DIST_CTG)["total"]
    assert _anomaly_notes(client, AGENT_MIRPUR) == []
    with Session(get_engine()) as session, session.begin():
        anomaly_scan.precompute(session, flagged, force=True)  # same flags: nothing new
    assert len(_anomaly_notes(client, DIST_DHAKA)) == 1
