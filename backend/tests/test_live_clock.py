"""Live clock: clock service, live data window, catch-up, hourly tick, demo story, admin card.

Small world (8 agents) on SQLite with the COMMITTED model artifacts, and an injected clock.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import BACKEND_DIR, get_settings
from app.core.db import get_engine
from app.core.leader import Leader
from app.models import Agent, AuditLog, Event, FloatSnapshot, Forecast, SystemMeta, Transaction
from app.services import data_clock, data_scheduler, freshness
from ml.data_gen import demo_spec, live_load
from ml.data_gen.demo_scenario import haversine_km
from ml.data_gen.live import H1, Engine, build_world, local
from ml.data_gen.live_calendar import load_holidays, weather_of_day
from ml.data_gen.live_story import DEMO_EVENT_EN
from ml.data_gen.timeline import BDT, FIXED, SIM_NOW, live_window
from tests.auth_helpers import ADMIN, bearer

N = 8
COMMITTED = BACKEND_DIR / "ml" / "artifacts"
H = datetime(2026, 10, 5, 5, tzinfo=UTC)  # 11:00 in Dhaka


@dataclass
class FakeClock:
    now: datetime


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    holder = FakeClock(H + timedelta(minutes=7))
    monkeypatch.setattr(clock, "_source", lambda: holder.now)
    return holder


@pytest.fixture
def live(seeded: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeClock) -> Iterator[Path]:
    """Reference-seeded DB, live clock, committed artifacts; no data generated yet."""
    monkeypatch.setenv("CLOCK_MODE", "live")
    monkeypatch.setenv("ARTIFACTS_DIR", str(COMMITTED))
    get_settings.cache_clear()
    yield seeded
    get_settings.cache_clear()


def _regen(at: datetime) -> None:
    data_clock.regenerate(get_settings(), at, N)


def _count(model: type[FloatSnapshot] | type[Transaction] | type[Event]) -> int:
    with Session(get_engine()) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def _max_ts(model: type[FloatSnapshot] | type[Transaction]) -> datetime:
    with Session(get_engine()) as s:
        found = s.scalar(select(func.max(model.ts)))
    assert found is not None
    return clock.as_utc(found)


# --- clock service ------------------------------------------------------------------------------

def test_fixed_clock_is_frozen_at_sim_now(env: Path) -> None:
    assert clock.mode() == "fixed" and not clock.is_live()
    assert clock.target_hour() == SIM_NOW.astimezone(UTC)
    assert clock.window_at(SIM_NOW) == FIXED
    assert clock.lag_h(SIM_NOW, SIM_NOW + timedelta(hours=5)) == 0.0


def test_live_clock_follows_the_injected_now(live: Path, fake: FakeClock) -> None:
    fake.now = datetime(2026, 10, 5, 9, 37, 12, tzinfo=UTC)
    assert clock.is_live()
    assert clock.target_hour() == datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert clock.lag_h(datetime(2026, 10, 5, 9, tzinfo=UTC), fake.now) == pytest.approx(0.62, 0.01)
    win = clock.window_at(clock.target_hour())
    assert win.start == datetime(2026, 6, 7, tzinfo=BDT)  # 120 local days before 5 Oct
    assert win.hour_index(clock.target_hour()) + 72 <= win.n_hours  # room for the horizon


def test_live_window_uses_the_dhaka_date(live: Path) -> None:
    # 18:30 UTC on 4 Oct is already 00:30 on 5 Oct in Dhaka: the window counts from the 5th.
    win = live_window(datetime(2026, 10, 4, 18, 30, tzinfo=UTC))
    assert win.start == datetime(2026, 6, 7, tzinfo=BDT)
    assert win.start.astimezone(UTC) == datetime(2026, 6, 6, 18, tzinfo=UTC)
    assert win.holdout_start == datetime(2026, 9, 21, tzinfo=BDT)


def test_clock_shift_moves_the_wall_clock(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    monkeypatch.setenv("CLOCK_MODE", "live")
    monkeypatch.setenv("CLOCK_SHIFT_H", "-72")
    get_settings.cache_clear()
    shifted = clock._system_now()
    assert abs((datetime.now(UTC) - shifted) - timedelta(hours=72)) < timedelta(seconds=5)
    monkeypatch.setenv("CLOCK_MODE", "fixed")
    get_settings.cache_clear()
    assert abs(datetime.now(UTC) - clock._system_now()) < timedelta(seconds=5)  # fixed: no shift


# --- deterministic world --------------------------------------------------------------------------

def test_same_date_gives_the_same_values() -> None:
    d = date(2026, 9, 14)
    a, b = Engine(build_world(42, N)), Engine(build_world(42, N))
    b.block(d - timedelta(days=3))  # a different history of calls must not matter
    x, y = a.block(d), b.block(d)
    assert np.array_equal(x.amt_out, y.amt_out) and np.array_equal(x.amt_in, y.amt_in)
    assert np.array_equal(x.scheduled, y.scheduled) and np.array_equal(x.adhoc_u, y.adhoc_u)
    assert weather_of_day(42, d) == weather_of_day(42, d)
    assert not np.array_equal(a.block(d + timedelta(days=1)).amt_out, x.amt_out)


def test_holiday_file_marks_unverified_dates() -> None:
    days = load_holidays()
    assert all(h.status in ("fixed_date", "unverified") for h in days)
    assert all(h.status == "unverified" for h in days if h.kind == "eid")
    assert any(h.day == date(2026, 12, 16) and h.status == "fixed_date" for h in days)


# --- live data: fresh window, catch-up, idempotence, no future rows ------------------------------

def test_catch_up_matches_an_uninterrupted_run(live: Path, monkeypatch: pytest.MonkeyPatch
                                               ) -> None:
    start = H - 30 * H1
    _regen(start)
    monkeypatch.setenv("DATA_CATCHUP_BATCH_H", "7")
    get_settings.cache_clear()
    assert data_clock.catch_up(get_settings(), H) == 30
    assert _max_ts(FloatSnapshot) == H and _max_ts(Transaction) == H - H1  # nothing ahead
    rows = (_count(FloatSnapshot), _count(Transaction), _count(Event))
    assert data_clock.catch_up(get_settings(), H) == 0  # idempotent
    assert (_count(FloatSnapshot), _count(Transaction), _count(Event)) == rows

    with Session(get_engine()) as s:
        world = live_load.world_for(s, 42)
        ids = dict(s.execute(select(Agent.code, Agent.id)).tuples().all())
        stored = dict(s.execute(select(FloatSnapshot.agent_id, FloatSnapshot.cash_balance)
                                .where(FloatSnapshot.ts == H)).tuples().all())
    engine = Engine(world)
    win = live_window(start)
    cash, em = engine.start(win.start)
    last = list(engine.run(win.start, cash, em, int((H - win.start) / H1)))[-1]
    for i, a in enumerate(world.agents):
        assert float(stored[ids[a.code]]) == last.cash_next[i]


def test_an_interrupted_batch_leaves_nothing_behind(live: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    _regen(H - 5 * H1)
    before = (_count(FloatSnapshot), _count(Transaction))

    def boom(*_args: object, **_kw: object) -> None:
        raise RuntimeError("killed mid-batch")

    with monkeypatch.context() as mp:
        mp.setattr(live_load, "_write_meta", boom)
        with pytest.raises(RuntimeError):
            data_clock.catch_up(get_settings(), H)
    assert (_count(FloatSnapshot), _count(Transaction)) == before
    with Session(get_engine()) as s:
        assert live_load.data_hour(s) == H - 5 * H1
    assert data_clock.catch_up(get_settings(), H) == 5


def test_regenerate_on_a_large_gap_or_a_clock_moved_back(live: Path) -> None:
    _regen(H)
    s_ = get_settings()
    with Session(get_engine()) as s:
        assert data_clock.needs_regenerate(s, s_, H + timedelta(days=3)) is None
        assert data_clock.needs_regenerate(s, s_, H + timedelta(days=15)) == "gap"
        assert data_clock.needs_regenerate(s, s_, H - H1) == "data_ahead_of_clock"
    with Session(get_engine()) as s, s.begin():
        s.merge(SystemMeta(key="clock_mode", value="fixed"))
    with Session(get_engine()) as s:
        assert data_clock.needs_regenerate(s, s_, H) == "clock_mode"


# --- demo story relative to now -------------------------------------------------------------------

def test_demo_story_runs_out_this_afternoon_with_a_donor_nearby(live: Path) -> None:
    _regen(H)
    with Session(get_engine()) as s:
        story = live_load.active_story(s, H)
        labels = s.get(SystemMeta, "synthetic_labels")
        events = list(s.scalars(select(Event).where(Event.name_en == DEMO_EVENT_EN)))
    assert story is not None and story.anchor == H
    at = local(story.stockout_at)
    assert at.date() == local(H).date() and (at.hour, at.minute) == (15, 40)
    assert (story.wage_day is None) == (len(events) == 0)  # labelled event only when needed
    assert labels is not None
    donor = labels.value["demo"]["donor"]
    assert donor["same_distributor"] and donor["distance_km"] <= 2.0

    world = build_world(42, N, (story,))
    engine = Engine(world)
    i = world.index(demo_spec.STOCKOUT_AGENT)
    with Session(get_engine()) as s:
        ids = dict(s.execute(select(Agent.code, Agent.id)).tuples().all())
        snap = {aid: (float(c), float(e)) for aid, c, e in s.execute(
            select(FloatSnapshot.agent_id, FloatSnapshot.cash_balance,
                   FloatSnapshot.emoney_balance).where(FloatSnapshot.ts == H)).tuples()}
    cash = np.array([snap[ids[a.code]][0] for a in world.agents])
    em = np.array([snap[ids[a.code]][1] for a in world.agents])
    assert cash[i] == story.refill_cash
    hours = list(engine.run(H, cash, em, 5))  # 11:00 .. 15:00 Dhaka
    before = [cash[i]] + [h.cash_next[i] for h in hours[:-1]]
    assert min(before) > 0  # cash lasts until the stock-out hour ...
    last = hours[-1]
    assert before[-1] + last.served_in[i] - last.served_out[i] == 0  # ... and runs dry in it
    donor_agent = world.agents[world.index(demo_spec.DONOR_AGENT)]
    me = world.agents[i]
    assert haversine_km(me.lat, me.lng, donor_agent.lat, donor_agent.lng) <= 2.0


def test_reanchor_shapes_only_the_future(live: Path, fake: FakeClock) -> None:
    _regen(H)
    later = H + 10 * H1  # 21:00 Dhaka, after today's stock-out
    data_clock.catch_up(get_settings(), later)
    with Session(get_engine()) as s, s.begin():
        story = live_load.reanchor(s, 42)
    assert story is not None and story.anchor == later
    assert local(story.stockout_at).date() == local(later).date() + timedelta(days=1)
    assert story.dry_days == (local(story.stockout_at).date(),)


# --- hourly tick: data + every cache --------------------------------------------------------------

def test_tick_moves_data_and_predictions_to_the_new_hour(live: Path, fake: FakeClock,
                                                         client: TestClient) -> None:
    _regen(H)
    first = data_clock.tick("manual")
    assert first.precomputed and first.duration_s < data_clock.TICK_BUDGET_S
    fake.now = H + timedelta(hours=1, minutes=1)
    second = data_clock.tick("hourly")
    assert (second.hours, second.regenerated, second.precomputed) == (1, None, True)
    again = data_clock.tick("hourly")  # same hour: nothing to do
    assert (again.hours, again.precomputed) == (0, False)
    with Session(get_engine()) as s:
        origin = s.scalar(select(func.min(Forecast.ts)))
        f = freshness.freshness(s, get_settings())
    assert origin is not None and clock.as_utc(origin) == H + H1
    assert f.clock is not None and f.clock.mode == "live"
    assert f.clock.data_hour == H + H1 and f.data_period.end == H + H1
    assert f.data_period.start == datetime(2026, 6, 7, tzinfo=BDT)

    h = bearer(client, ADMIN)
    card = client.get("/api/v1/admin/clock", headers=h).json()
    assert card["clock"]["mode"] == "live" and card["tick_interval_s"] > 0
    res = client.post("/api/v1/admin/clock/tick", headers=h)
    assert res.status_code == 202
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "data_clock.tick")) == 1
        assert data_clock.take_request(s) is not None


def test_admin_clock_in_fixed_mode(client: TestClient, seeded: Path) -> None:
    h = bearer(client, ADMIN)
    card = client.get("/api/v1/admin/clock", headers=h).json()
    assert card["clock"]["mode"] == "fixed" and card["next_tick_at"] is None
    assert client.post("/api/v1/admin/clock/tick", headers=h).json()["detail"] == "clock_fixed"
    assert client.get("/api/v1/admin/clock").status_code == 401


def test_scheduler_waits_for_bootstrap_and_respects_the_leader(live: Path) -> None:
    _regen(H)
    state = get_settings().bootstrap_state_file
    state.write_text("seeding", encoding="utf-8")
    leader = Leader(get_engine(), "data-clock", data_scheduler.LOCK_ID)
    other = Leader(get_engine(), "data-clock", data_scheduler.LOCK_ID)
    try:
        assert data_scheduler.run_once(leader) == "waiting"
        state.write_text("ready", encoding="utf-8")
        assert other.acquire()
        assert data_scheduler.run_once(leader) == "standby"
        other.release()
        assert data_scheduler.run_once(leader) == "idle"  # data already at the current hour
    finally:
        leader.release()
        other.release()
