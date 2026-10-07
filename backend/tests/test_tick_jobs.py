"""Live data clock: the non-overlap guard of the hourly tick and the separate backtest job."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import BACKEND_DIR, get_settings
from app.core.db import get_engine
from app.core.leader import Leader
from app.services import backtest, backtest_job, data_clock, data_scheduler
from ml.data_gen import live_load
from tests.auth_helpers import ADMIN, bearer

N = 8
COMMITTED = BACKEND_DIR / "ml" / "artifacts"
H = datetime(2026, 10, 5, 5, tzinfo=UTC)  # 11:00 in Dhaka


@pytest.fixture
def now(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    holder = [H + timedelta(minutes=7)]
    monkeypatch.setattr(clock, "_source", lambda: holder[0])
    return holder


@pytest.fixture
def live(seeded: Path, monkeypatch: pytest.MonkeyPatch, now: list[datetime]) -> Iterator[Path]:
    """Reference-seeded DB, live clock, committed artifacts, N agents of live data up to H,
    bootstrap marked ready."""
    monkeypatch.setenv("CLOCK_MODE", "live")
    monkeypatch.setenv("ARTIFACTS_DIR", str(COMMITTED))
    monkeypatch.setitem(backtest_job._last_try, "key", None)
    get_settings.cache_clear()
    data_clock.regenerate(get_settings(), H, N)
    get_settings().bootstrap_state_file.write_text("ready", encoding="utf-8")
    yield seeded
    get_settings.cache_clear()


def _data_hour() -> datetime | None:
    with Session(get_engine()) as s:
        return live_load.data_hour(s)


def _stale() -> bool:
    with Session(get_engine()) as s:
        return backtest.stale_key(s, get_settings()) is not None


def test_a_running_tick_makes_the_next_one_skip(live: Path, now: list[datetime],
                                               client: TestClient,
                                               caplog: pytest.LogCaptureFixture) -> None:
    leader = Leader(get_engine(), "data-clock", data_scheduler.LOCK_ID)
    now[0] = H + timedelta(hours=1, minutes=1)  # a new hour is due
    try:
        with data_clock.tick_guard() as free:  # stands in for a tick that is still running
            assert free
            assert data_scheduler.run_once(leader) == "skipped"
            assert data_scheduler.run_once(leader) == "skipped"
        assert "previous tick still running" in caplog.text
        assert _data_hour() == H  # the skipped ticks wrote nothing
        st = data_clock.status()
        assert st["skipped_ticks"] == 2 and st["last_skipped_at"] == now[0].isoformat()
        card = client.get("/api/v1/admin/clock", headers=bearer(client, ADMIN)).json()
        assert card["skipped_ticks"] == 2 and card["last_skipped_at"] is not None

        assert data_scheduler.run_once(leader) == "ran"  # guard free again: the tick runs
        assert _data_hour() == H + timedelta(hours=1)
        with data_clock.tick_guard() as free:
            assert free  # the finished tick released it
    finally:
        leader.release()


def test_the_tick_leaves_the_backtest_to_its_own_job(live: Path, client: TestClient) -> None:
    result = data_clock.tick("manual")
    assert result.precomputed
    assert "backtest" not in result.stages_s and "risk" in result.stages_s
    assert _stale()  # the tick did not run the holdout backtest

    leader = Leader(get_engine(), "backtest-job", backtest_job.LOCK_ID)
    try:
        with data_clock.tick_guard():
            assert backtest_job.run_once(leader) == "busy"  # never starts during a tick
        assert backtest_job.status() == {}
        assert backtest_job.run_once(leader) == "ran"
        assert not _stale()
        st = backtest_job.status()
        assert st["state"] == "ok" and st["last_error"] is None and st["duration_s"] >= 0
        assert st["budget_s"] == backtest_job.BUDGET_S
        assert backtest_job.run_once(leader) == "current"  # once a day, not every poll
    finally:
        leader.release()

    card = client.get("/api/v1/admin/clock", headers=bearer(client, ADMIN)).json()
    job = card["backtest"]
    assert job["state"] == "ok" and job["last_run_at"] is not None
    assert job["duration_s"] is not None and job["budget_s"] == backtest_job.BUDGET_S
    assert job["over_budget"] is False


def test_a_failed_backtest_is_recorded_and_not_retried_every_poll(
        live: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("holdout broke")

    data_clock.tick("manual")  # registers the model the backtest key names
    monkeypatch.setattr(backtest, "precompute", boom)
    leader = Leader(get_engine(), "backtest-job", backtest_job.LOCK_ID)
    try:
        assert backtest_job.run_once(leader) == "failed"
        st = backtest_job.status()
        assert st["state"] == "failed" and "holdout broke" in st["last_error"]
        assert backtest_job.run_once(leader) == "retry_later"  # same key: wait RETRY_S
    finally:
        leader.release()


def test_fixed_clock_card_has_no_backtest_job(client: TestClient, seeded: Path) -> None:
    card = client.get("/api/v1/admin/clock", headers=bearer(client, ADMIN)).json()
    assert card["backtest"] is None and card["skipped_ticks"] == 0
