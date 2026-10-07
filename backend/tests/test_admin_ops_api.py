"""Admin operations: data summary + assumptions, model registry, drift, jobs, LLM log/usage."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_engine
from app.llm import store
from app.models import AdminJob, Agent, AuditLog, ModelVersion, Transaction, User
from app.models.enums import GeneratedBy, GuardResult, Lang, LlmIntent, TxnType
from app.services import admin_data, jobs
from app.services.jobs import Progress
from tests.auth_helpers import ADMIN, bearer

API = "/api/v1/admin"


def test_data_summary_and_assumptions(client: TestClient, seeded: Path,
                                      monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = bearer(client, ADMIN)
    body = client.get(f"{API}/data", headers=h).json()
    counts = {c["table"]: c["rows"] for c in body["counts"]}
    assert counts["agents"] == 3 and counts["users"] == 7 and "transactions_holdout" in counts
    assert body["configured_seed"] == 42
    assert body["period"]["holdout_start"] < body["period"]["sim_now"] < body["period"]["end"]
    doc = tmp_path / "docs"
    doc.mkdir()
    (doc / admin_data.ASSUMPTIONS_FILE).write_text("# Synthetic Data\n\n| a | b |\n",
                                                   encoding="utf-8")
    monkeypatch.setattr(admin_data, "DOC_DIRS", (doc,))
    res = client.get(f"{API}/data/assumptions", headers=h)
    assert res.json() == {"title": "Synthetic Data", "markdown": "# Synthetic Data\n\n| a | b |\n"}
    monkeypatch.setattr(admin_data, "DOC_DIRS", (tmp_path / "missing",))
    res = client.get(f"{API}/data/assumptions", headers=h)
    assert (res.status_code, res.json()["detail"]) == (404, "assumptions_missing")


def test_data_summary_big_counts_follow_inserts(client: TestClient, seeded: Path) -> None:
    """The cached float_snapshots/transactions counts are invalidated by a new row."""
    h = bearer(client, ADMIN)

    def counts() -> dict[str, int]:
        body = client.get(f"{API}/data", headers=h).json()
        return {c["table"]: c["rows"] for c in body["counts"]}

    before = counts()
    assert list(before)[:7] == ["distributors", "agents", "users", "float_snapshots",
                                "transactions", "events", "weather_daily"]
    with Session(get_engine()) as s:
        agent_id = s.scalar(select(Agent.id).limit(1))
        s.add(Transaction(agent_id=agent_id, ts=datetime.now(UTC), txn_type=TxnType.cash_in,
                          amount_bdt=Decimal("100.00"), is_holdout=True))
        s.commit()
    after = counts()
    assert after["transactions"] == before["transactions"] + 1
    assert after["transactions_holdout"] == before["transactions_holdout"] + 1
    assert after["float_snapshots"] == before["float_snapshots"]


def _fake_runner(settings: Settings, job_id: int, p: Progress) -> dict[str, Any]:
    p("generate", 40)
    return {"seed": settings.seed, "rows.agents": 3, "reproduced": True}


def test_job_runs_in_background_with_progress(client: TestClient, seeded: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(jobs.RUNNERS, "generate_data", _fake_runner)
    h = bearer(client, ADMIN)
    res = client.post(f"{API}/jobs", json={"kind": "generate_data"}, headers=h)
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "queued" and res.json()["started_by_email"] == ADMIN
    job = client.get(f"{API}/jobs/{res.json()['id']}", headers=h).json()
    assert (job["status"], job["progress"], job["step"]) == ("succeeded", 100, "done")
    assert {r["key"]: r["value"] for r in job["result"]} == {
        "seed": "42", "rows.agents": "3", "reproduced": "true"}
    listing = client.get(f"{API}/jobs", headers=h).json()
    assert listing["running"] is None and listing["items"][0]["id"] == job["id"]
    with Session(get_engine()) as session:
        assert session.scalar(select(AuditLog.action).where(AuditLog.entity_type == "job")) \
            == "job.generate_data"
    assert client.get(f"{API}/jobs/9999", headers=h).status_code == 404
    assert client.post(f"{API}/jobs", json={"kind": "nope"}, headers=h).status_code == 422


def test_failed_job_records_error(client: TestClient, seeded: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(settings: Settings, job_id: int, p: Progress) -> dict[str, Any]:
        raise RuntimeError("no data")
    monkeypatch.setitem(jobs.RUNNERS, "retrain_anomaly", boom)
    h = bearer(client, ADMIN)
    jid = client.post(f"{API}/jobs", json={"kind": "retrain_anomaly"}, headers=h).json()["id"]
    job = client.get(f"{API}/jobs/{jid}", headers=h).json()
    assert job["status"] == "failed" and job["error"] == "RuntimeError: no data"


def test_one_job_at_a_time_and_stale_jobs_expire(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    with Session(get_engine()) as session, session.begin():
        uid = session.scalar(select(User.id).where(User.email == ADMIN))
        now = datetime.now(UTC)
        session.add(AdminJob(kind="retrain_forecast", status="running", progress=30, step="fit",
                             result={}, started_by=uid, created_at=now, updated_at=now))
    res = client.post(f"{API}/jobs", json={"kind": "generate_data"}, headers=h)
    assert (res.status_code, res.json()["detail"]) == (409, "job_running")
    assert client.get(f"{API}/jobs", headers=h).json()["running"]["progress"] == 30
    with Session(get_engine()) as session, session.begin():
        job = session.scalars(select(AdminJob)).one()
        job.updated_at = datetime.now(UTC) - jobs.STALE_AFTER - timedelta(minutes=1)
    listing = client.get(f"{API}/jobs", headers=h).json()
    assert listing["running"] is None
    assert (listing["items"][0]["status"], listing["items"][0]["error"]) == (
        "failed", "interrupted")


def test_mark_interrupted(seeded: Path) -> None:
    with Session(get_engine()) as session, session.begin():
        session.add(AdminJob(kind="generate_data", status="running", result={}))
        session.flush()
        assert jobs.mark_interrupted(session) == 1
        assert session.scalars(select(AdminJob.status)).one() == "failed"


def _log(provider: str, generated_by: GeneratedBy, guard: GuardResult, tokens: int | None,
         latency: int) -> store.CallRecord:
    return store.CallRecord(user_id=None, intent=LlmIntent.narrate, lang=Lang.en,
                            evidence_hash="e", provider=provider, model=None,
                            generated_by=generated_by, guard_result=guard, latency_ms=latency,
                            prompt_tokens=tokens, completion_tokens=tokens)


def test_llm_logs_and_usage(client: TestClient, seeded: Path) -> None:
    with Session(get_engine()) as session, session.begin():
        store.log_call(session, _log("anthropic", GeneratedBy.llm, GuardResult.passed, 100, 900))
        store.log_call(session, _log("anthropic", GeneratedBy.template,
                                     GuardResult.numbers_fail, 80, 1100))
        store.log_call(session, _log("cache", GeneratedBy.llm, GuardResult.passed, None, 0))
        store.log_call(session, _log("replay", GeneratedBy.replay, GuardResult.passed, None, 3))
    h = bearer(client, ADMIN)
    page = client.get(f"{API}/llm/logs", headers=h).json()
    assert page["total"] == 4 and page["items"][0]["provider"] == "replay"
    assert [i["cache_hit"] for i in page["items"]] == [False, True, False, False]
    hits = client.get(f"{API}/llm/logs", params={"cache_hit": True}, headers=h).json()
    assert hits["total"] == 1
    failed = client.get(f"{API}/llm/logs", params={"guard_result": "numbers_fail"},
                        headers=h).json()
    assert failed["total"] == 1 and failed["items"][0]["generated_by"] == "template"
    usage = client.get(f"{API}/llm/usage", params={"days": 3}, headers=h).json()
    assert len(usage["days"]) == 3
    today = usage["days"][-1]
    assert (today["calls"], today["live_calls"], today["cache_hits"], today["replay"],
            today["template"], today["guard_failures"]) == (4, 2, 1, 1, 1, 1)
    assert today["prompt_tokens"] == 180
    assert usage["calls_today"] == 2 and usage["cap_used"] == round(2 / usage["daily_cap"], 4)
    assert usage["cache_hit_rate"] == 0.25 and usage["p95_latency_ms"] == 1100


def test_models_and_drift_need_a_model(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    assert client.get(f"{API}/models", headers=h).json()["items"] == []
    drift = client.get(f"{API}/drift", headers=h).json()
    assert drift["status"] == "no_data" and drift["floats"] == []


def test_models_and_drift(client: TestClient, ready: Path) -> None:
    h = bearer(client, ADMIN)
    items = client.get(f"{API}/models", headers=h).json()["items"]
    forecast = next(i for i in items if i["model_name"] == "demand_forecast")
    assert forecast["is_active"] is True
    keys = {m["key"] for m in forecast["metrics"]}
    assert {"cash_out.mae_skill", "cash_in.coverage_q10_q90"} <= keys
    drift = client.get(f"{API}/drift", headers=h).json()
    assert drift["model_version"] == forecast["version"]
    assert {f["float_type"] for f in drift["floats"]} == {"cash", "emoney"}
    cash = next(f for f in drift["floats"] if f["float_type"] == "cash")
    assert [b["horizon"] for b in cash["buckets"]] == ["1-6", "7-24", "25-72"]
    assert cash["hours_compared"] > 0 and len(cash["by_horizon"]) == 72
    for b in cash["buckets"]:
        assert b["mae"] is not None and b["reference_mae"] is not None
        assert b["status"] in {"stable", "watch", "drift"}


@pytest.mark.slow
def test_retrain_forecast_records_inactive_version(client: TestClient, ready: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "RETRAIN_ROUNDS", 5)
    h = bearer(client, ADMIN)
    jid = client.post(f"{API}/jobs", json={"kind": "retrain_forecast"}, headers=h).json()["id"]
    job = client.get(f"{API}/jobs/{jid}", headers=h).json()
    assert job["status"] == "succeeded", job["error"]
    result = {r["key"]: r["value"] for r in job["result"]}
    with Session(get_engine()) as session:
        row = session.scalar(select(ModelVersion).where(ModelVersion.version == result["version"]))
        assert row is not None and row.is_active is (result["reproduced"] == "true")
    assert (ready.parent / "candidates" / f"forecast-job-{jid}" / "manifest.json").is_file()
