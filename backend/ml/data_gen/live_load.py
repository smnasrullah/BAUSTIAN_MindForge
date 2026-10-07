"""Write live-clock synthetic data: a fresh window, appended hours, weather and calendar events.

Rows are never written for a future hour: transactions for hours before the data hour H,
snapshots up to H (the balance at the top of the current hour). Calendar events (salary days,
hat-bazar, holidays) are written LIVE_FUTURE_DAYS ahead because they are known in advance;
weather is written only up to today. Each call runs in the caller's transaction, so an
interrupted batch leaves nothing behind and the next call redoes it with the same values.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import DATA_VERSION
from app.models import Agent
from app.models.enums import EventType, UrbanRural
from app.models.system_meta import SystemMeta
from app.models.timeseries import Event, FloatSnapshot, Transaction, WeatherDaily
from ml.data_gen import demo_spec
from ml.data_gen import live_calendar as lc
from ml.data_gen.demo_scenario import haversine_km
from ml.data_gen.events import DISTRICT_BN, EventRow
from ml.data_gen.geography import HAT_WEEKDAY
from ml.data_gen.live import H1, Engine, Hour, LiveWorld, build_world, local
from ml.data_gen.live_plan import plan
from ml.data_gen.live_story import DEMO_EVENT_BN, DEMO_EVENT_EN, STORY_DISTRICT, Story
from ml.data_gen.load import SNAPSHOT_COLS, TXN_COLS, bulk, upsert_agents
from ml.data_gen.timeline import BDT, LIVE_FUTURE_DAYS, Window, live_window

CLOCK_KEY = "data_clock"
STORY_KEY = "demo_story"
UNVERIFIED_EN, UNVERIFIED_BN = " (date unverified)", " (তারিখ যাচাই করা হয়নি)"


def _at(d: date, hour: int = 0) -> datetime:
    return datetime.combine(d, time(hour), tzinfo=BDT)


def _meta(session: Session, key: str) -> Any:
    row = session.get(SystemMeta, key)
    return row.value if row else None


def _set(session: Session, key: str, value: Any) -> None:
    session.merge(SystemMeta(key=key, value=value))


def stories(session: Session) -> tuple[Story, ...]:
    raw = _meta(session, STORY_KEY)
    items = raw.get("stories", []) if isinstance(raw, dict) else []
    return tuple(Story.from_json(s) for s in items)


def world_for(session: Session, seed: int) -> LiveWorld:
    state = _meta(session, CLOCK_KEY) or {}
    return build_world(seed, int(state.get("n_agents", 0)) or 300, stories(session))


# --- events and weather -----------------------------------------------------------------------

def calendar_events(d: date, holidays: tuple[lc.Holiday, ...]) -> list[EventRow]:
    """Calendar events that START on day d (same kinds as ml/data_gen/events.py)."""
    out: list[EventRow] = []
    if d.day == 1:
        out.append(EventRow(EventType.salary, "Salary days (1st-3rd)", "বেতন দিবস (১-৩ তারিখ)",
                            _at(d), _at(d + timedelta(days=3)), None,
                            lc.cal.SALARY_OUT[UrbanRural.urban][0]))
    if d.day == lc.cal.GARMENT_DAYS[0]:
        for district in lc.cal.GARMENT_DISTRICTS:
            out.append(EventRow(EventType.salary, "Factory wage days", "কারখানার মজুরি দিবস",
                                _at(d), _at(d + timedelta(days=len(lc.cal.GARMENT_DAYS))),
                                district, lc.cal.GARMENT_OUT))
    for district, wd in HAT_WEEKDAY.items():
        if d.weekday() == wd:
            out.append(EventRow(EventType.hat_bazar, f"{district} weekly hat",
                                f"{DISTRICT_BN[district]} সাপ্তাহিক হাট",
                                _at(d, lc.cal.HAT_HOURS.start), _at(d, lc.cal.HAT_HOURS.stop),
                                district, lc.cal.HAT_OUT[UrbanRural.rural]))
    for h in holidays:
        en = h.name_en + (UNVERIFIED_EN if h.status == "unverified" else "")
        bn = h.name_bn + (UNVERIFIED_BN if h.status == "unverified" else "")
        if h.kind == "eid" and h.day + timedelta(days=lc.cal.EID_OFFSETS[0]) == d:
            end = h.day + timedelta(days=lc.cal.EID_OFFSETS[-1] + 1)
            out.append(EventRow(EventType.eid, f"{en} (pre-Eid rush and holidays)", bn, _at(d),
                                _at(end), None, max(lc.cal.EID_OUT[UrbanRural.rural])))
        if h.kind == "holiday" and h.day == d:
            out.append(EventRow(EventType.holiday, en, bn, _at(d), _at(d + timedelta(days=1)),
                                None, lc.cal.HOLIDAY_MULT[UrbanRural.urban]))
    return out


def weather_events(d: date, weather: dict[str, tuple[float, float, bool]]) -> list[EventRow]:
    out = []
    for district, (rain, _temp, severe) in sorted(weather.items()):
        if severe:
            mult = lc.rain_multiplier(rain, UrbanRural.rural)
            out.append(EventRow(EventType.weather, "Heavy rain", "ভারী বৃষ্টি", _at(d),
                                _at(d + timedelta(days=1)), district, round(mult, 3)))
    return out


def story_event(s: Story) -> EventRow | None:
    if s.wage_day is None:
        return None
    return EventRow(EventType.salary, DEMO_EVENT_EN, DEMO_EVENT_BN, _at(s.wage_day),
                    _at(s.wage_day + timedelta(days=1)), STORY_DISTRICT, lc.cal.GARMENT_OUT)


def _add_events(session: Session, rows: list[EventRow]) -> int:
    session.add_all(Event(type=e.type, name_en=e.name_en, name_bn=e.name_bn,
                          starts_at=e.starts_at, ends_at=e.ends_at, district=e.district,
                          intensity=Decimal(str(e.intensity))) for e in rows)
    return len(rows)


def _add_weather(session: Session, engine: Engine, first: date, last: date) -> tuple[int, int]:
    """weather_daily rows and heavy-rain events for days first..last: (rows, events)."""
    n, n_ev, d = 0, 0, first
    while d <= last:
        w = engine.weather(d)
        for district, (rain, temp, severe) in sorted(w.items()):
            session.merge(WeatherDaily(district=district, date=d, rain_mm=Decimal(str(rain)),
                                       temp_c=Decimal(str(temp)), severe=severe))
            n += 1
        n_ev += _add_events(session, weather_events(d, w))
        d += timedelta(days=1)
    return n, n_ev


def _add_calendar(session: Session, holidays: tuple[lc.Holiday, ...], first: date,
                  last: date) -> int:
    n, d = 0, first
    while d <= last:
        n += _add_events(session, calendar_events(d, holidays))
        d += timedelta(days=1)
    return n


# --- rows ---------------------------------------------------------------------------------------

def _snapshot_rows(ids: np.ndarray, ts: datetime, cash: np.ndarray, em: np.ndarray,
                   holdout: bool) -> Iterator[tuple[Any, ...]]:
    t = ts.astimezone(UTC)
    for aid, c, e in zip(ids.tolist(), np.round(cash).astype(np.int64).tolist(),
                         np.round(em).astype(np.int64).tolist(), strict=True):
        yield aid, t, c, e, holdout


def _txn_rows(ids: np.ndarray, h: Hour, holdout: bool) -> Iterator[tuple[Any, ...]]:
    t = h.ts.astimezone(UTC)
    for kind, amt, cnt in (("cash_in", h.served_in, h.cnt_in), ("cash_out", h.served_out,
                                                                h.cnt_out)):
        rounded = np.round(amt).astype(np.int64)
        for r in np.flatnonzero((rounded > 0) & (cnt > 0)).tolist():
            yield int(ids[r]), t, kind, int(rounded[r]), int(cnt[r]), holdout


def _write_hours(session: Session, ids: np.ndarray, hours: list[Hour], win: Window) -> tuple[
        int, int]:
    snaps = (row for h in hours for row in _snapshot_rows(
        ids, h.ts + H1, h.cash_next, h.em_next, h.ts + H1 >= win.holdout_start))
    n_snap = bulk(session, FloatSnapshot.__table__, SNAPSHOT_COLS, snaps)
    txns = (row for h in hours for row in _txn_rows(ids, h, h.ts >= win.holdout_start))
    return n_snap, bulk(session, Transaction.__table__, TXN_COLS, txns)


def _ids(session: Session, world: LiveWorld) -> np.ndarray:
    by_code = dict(session.execute(select(Agent.code, Agent.id)).tuples().all())
    missing = [a.code for a in world.agents if a.code not in by_code]
    if missing:
        raise RuntimeError(f"live data: agents missing in the database: {missing[:5]}")
    return np.array([by_code[a.code] for a in world.agents], dtype=np.int64)


# --- meta ---------------------------------------------------------------------------------------

def _story_summary(session: Session, world: LiveWorld, s: Story) -> dict[str, Any]:
    eng = Engine(world)
    donor = world.agents[world.index(demo_spec.DONOR_AGENT)]
    agent = world.agents[world.index(demo_spec.STOCKOUT_AGENT)]
    km = haversine_km(agent.lat, agent.lng, donor.lat, donor.lng)
    return {"anchor": local(s.anchor).isoformat(),
            "stockout": {"agent_code": agent.code, "stockout_at": local(s.stockout_at).isoformat(),
                         "refill_at": local(s.anchor).isoformat(), "refill_cash": s.refill_cash,
                         "demo_event": DEMO_EVENT_EN if s.wage_day else None},
            "donor": {"agent_code": donor.code, "distance_km": round(km, 2),
                      "same_distributor": donor.distributor_code == agent.distributor_code,
                      "cash_target": float(eng.block(local(s.anchor).date()).cash_target[
                          world.index(demo_spec.DONOR_AGENT)])},
            "anomaly": {"agent_code": demo_spec.ANOMALY_AGENT, "kind": "night_structuring",
                        "window_start": local(s.anomaly_start).isoformat(),
                        "window_end": local(s.anomaly_end).isoformat()}}


def _write_meta(session: Session, world: LiveWorld, hour: datetime, state: dict[str, Any],
                labels_changed: bool) -> None:
    win = live_window(hour)
    _set(session, "sim_now", hour.astimezone(UTC).isoformat())
    _set(session, "data_range", {"start": win.start.isoformat(), "end": hour.isoformat(),
                                 "holdout_start": win.holdout_start.isoformat()})
    _set(session, CLOCK_KEY, state | {"data_hour": hour.astimezone(UTC).isoformat()})
    _set(session, STORY_KEY, {"stories": [s.as_json() for s in world.stories]})
    if labels_changed:
        labels = Engine(world).labels(win.start.date(), local(hour).date())
        demo = (_story_summary(session, world, world.stories[-1])
                if world.stories and demo_spec.STOCKOUT_AGENT in {a.code for a in world.agents}
                else {})
        _set(session, "synthetic_labels", {"anomalies": [lab.as_json() for lab in labels],
                                           "demo": demo})


# --- public -------------------------------------------------------------------------------------

def regenerate(session: Session, seed: int, n_agents: int, hour: datetime) -> dict[str, int]:
    """A fresh 120-day window ending at `hour` (a UTC hour), replacing all time series, events
    and weather; the demo story is anchored at `hour`."""
    base = build_world(seed, n_agents)
    story = plan(base, hour, fresh=True)
    world = base.with_stories((story,) if story else ())
    win = live_window(hour)
    ids_by_code = upsert_agents(session, world.agents, {a.code for a in world.agents})
    for model in (Transaction, FloatSnapshot, Event, WeatherDaily):
        session.execute(delete(model))
    ids = np.array([ids_by_code[a.code] for a in world.agents], dtype=np.int64)
    engine = Engine(world)
    cash, em = engine.start(win.start)
    n_snap = bulk(session, FloatSnapshot.__table__, SNAPSHOT_COLS,
                  _snapshot_rows(ids, win.start, cash, em, win.start >= win.holdout_start))
    hours = list(engine.run(win.start, cash, em, int((hour - win.start) / H1)))
    s, t = _write_hours(session, ids, hours, win)
    today = local(hour).date()
    n_weather, n_rain = _add_weather(session, engine, win.start.date(), today)
    n_events = n_rain + _add_calendar(session, world.holidays, win.start.date(),
                                      today + timedelta(days=LIVE_FUTURE_DAYS))
    if story is not None and (ev := story_event(story)) is not None:
        n_events += _add_events(session, [ev])
    session.flush()
    _set(session, "seed", seed)
    _set(session, "data_version", DATA_VERSION)
    _set(session, "clock_mode", "live")
    state = {"window_start": win.start.isoformat(), "n_agents": n_agents,
             "weather_through": today.isoformat(),
             "events_through": (today + timedelta(days=LIVE_FUTURE_DAYS)).isoformat()}
    _write_meta(session, world, hour, state, labels_changed=True)
    return {"agents": len(ids), "float_snapshots": n_snap + s, "transactions": t,
            "weather_daily": n_weather, "events": n_events}


def data_hour(session: Session) -> datetime | None:
    state = _meta(session, CLOCK_KEY)
    if not isinstance(state, dict) or "data_hour" not in state:
        return None
    return datetime.fromisoformat(state["data_hour"]).astimezone(UTC)


def append(session: Session, seed: int, to_hour: datetime, max_hours: int) -> int:
    """Generate the hours after the data hour, at most up to `to_hour` and `max_hours` of them.
    Returns hours written (0 when the data is current)."""
    state = dict(_meta(session, CLOCK_KEY) or {})
    start = data_hour(session)
    if start is None:
        raise RuntimeError("live data clock state missing; regenerate first")
    n = min(int((to_hour - start) / H1), max_hours)
    if n <= 0:
        return 0
    world = world_for(session, seed)
    ids = _ids(session, world)
    found = {aid: (float(c), float(e)) for aid, c, e in session.execute(
        select(FloatSnapshot.agent_id, FloatSnapshot.cash_balance, FloatSnapshot.emoney_balance)
        .where(FloatSnapshot.ts == start)).tuples()}
    if len(found) < len(ids):
        raise RuntimeError(f"live data: snapshot at {start.isoformat()} incomplete")
    cash = np.array([found[int(a)][0] for a in ids])
    em = np.array([found[int(a)][1] for a in ids])
    engine = Engine(world)
    end = start + n * H1
    win = live_window(end)
    _write_hours(session, ids, list(engine.run(start, cash, em, n)), win)
    today = local(end).date()
    weather_through = date.fromisoformat(state["weather_through"])
    events_through = date.fromisoformat(state["events_through"])
    rolled = today > weather_through
    if rolled:
        _add_weather(session, engine, weather_through + timedelta(days=1), today)
        state["weather_through"] = today.isoformat()
    future = today + timedelta(days=LIVE_FUTURE_DAYS)
    if future > events_through:
        _add_calendar(session, world.holidays, events_through + timedelta(days=1), future)
        state["events_through"] = future.isoformat()
    session.flush()
    _write_meta(session, world, end, state, labels_changed=rolled)
    return n


def reanchor(session: Session, seed: int) -> Story | None:
    """A new demo story at the current data hour (only the future is shaped): the story
    agent's top-up becomes its balance at the top of this hour."""
    hour = data_hour(session)
    if hour is None:
        return None
    world = world_for(session, seed)
    story = plan(world, hour, fresh=False)
    if story is None:
        return None
    world = world.with_stories((*world.stories, story))
    i = world.index(demo_spec.STOCKOUT_AGENT)
    agent_id = _ids(session, world)[i]
    em = Engine(world).em_target[i]
    session.execute(update(FloatSnapshot).where(
        FloatSnapshot.agent_id == int(agent_id), FloatSnapshot.ts == hour).values(
        cash_balance=Decimal(int(story.refill_cash)), emoney_balance=Decimal(int(em))))
    if (ev := story_event(story)) is not None:
        _add_events(session, [ev])
    session.flush()
    _write_meta(session, world, hour, dict(_meta(session, CLOCK_KEY) or {}), labels_changed=True)
    return story


def active_story(session: Session, now: datetime) -> Story | None:
    """The latest story whose stock-out is still ahead of `now`."""
    found = [s for s in stories(session) if s.stockout_at > now]
    return found[-1] if found else None
