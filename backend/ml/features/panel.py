"""Hourly panel read from the database: demand per agent, calendar/event flags, weather.

Hour index t covers [start + t h, start + (t + 1) h) of a timeline window (local time
Asia/Dhaka): the fixed simulated timeline by default, or the live window around the current
hour (ml/data_gen/timeline.py). `load_panel(session, end=t0)` reads only transactions before t0,
so inference at an origin can never see the future.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent
from app.models.enums import EventType, TxnType, UrbanRural
from app.models.timeseries import Event, Transaction, WeatherDaily
from ml.data_gen.timeline import FIXED, START, Window

# (district, day) -> (rain_mm, temp_c) for days with no stored weather row (live: the days after
# today, which the forecast horizon reaches; the synthetic weather outlook).
WeatherFill = Callable[[str, date], tuple[float, float]]

AREA_CODE: dict[UrbanRural, int] = {UrbanRural.urban: 0, UrbanRural.peri_urban: 1,
                                    UrbanRural.rural: 2}
# Region code per agent (band calibration cells); 0 = unknown region.
REGIONS: tuple[str, ...] = ("Dhaka", "Chattogram", "Sylhet")
# Event flag rows in Panel.events; EID holds the day number inside the Eid window (-1 = none).
SALARY, WAGE, EID, HOLIDAY, HAT, SEVERE = range(6)
N_EVENT_FEATURES = 6
TARGETS = ("cash_out", "cash_in")


@dataclass
class Panel:
    agent_ids: np.ndarray  # (A,) agents.id, ordered by id
    tier: np.ndarray  # (A,)
    area: np.ndarray  # (A,) AREA_CODE
    district: np.ndarray  # (A,) index into districts
    cash_cap: np.ndarray  # (A,) BDT
    emoney_cap: np.ndarray  # (A,) BDT
    districts: list[str]
    demand: dict[str, np.ndarray]  # target -> (A, N_HOURS) BDT served per hour
    events: np.ndarray  # (D, N_EVENT_FEATURES, N_HOURS)
    rain_mm: np.ndarray  # (D, N_DAYS)
    temp_c: np.ndarray  # (D, N_DAYS)
    hour: np.ndarray  # (N_HOURS,) local hour of day
    dow: np.ndarray  # (N_HOURS,) Mon=0
    dom: np.ndarray  # (N_HOURS,) day of month
    window: Window = field(default=FIXED)
    region: np.ndarray | None = None  # (A,) 1 + index into REGIONS, 0 = unknown


def region_code(region: str | None) -> int:
    return REGIONS.index(region) + 1 if region in REGIONS else 0


def _utc(ts: datetime) -> datetime:
    # SQLite returns naive datetimes; values are written in UTC.
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def hour_of(ts: datetime) -> int:
    """Hour index on the FIXED timeline (training; live code uses Window.hour_index)."""
    return int((_utc(ts) - START) // timedelta(hours=1))


def ts_of(t: int) -> datetime:
    return (START + timedelta(hours=t)).astimezone(UTC)


def _agents(session: Session) -> tuple[list[Agent], list[str]]:
    agents = list(session.scalars(select(Agent).order_by(Agent.id)))
    return agents, sorted({a.district for a in agents})


def _demand(session: Session, row_of: dict[int, int], end: int, win: Window,
            since: int) -> dict[str, np.ndarray]:
    out = {k: np.zeros((len(row_of), win.n_hours)) for k in TARGETS}
    q = select(Transaction.agent_id, Transaction.ts, Transaction.txn_type, Transaction.amount_bdt)
    if end < win.n_hours:
        q = q.where(Transaction.ts < win.ts_of(end))
    q = q.where(Transaction.ts >= win.ts_of(max(since, 0)))
    for aid, ts, kind, amount in session.execute(q):
        t, r = win.hour_index(_utc(ts)), row_of.get(aid)
        if r is not None and 0 <= t < end:
            out[TxnType(kind).value][r, t] += float(amount)
    return out


def _hour_span(start: datetime, end: datetime, win: Window) -> slice:
    return slice(max(win.hour_index(_utc(start)), 0),
                 min(win.hour_index(_utc(end)), win.n_hours))


def _events(session: Session, districts: list[str], win: Window) -> np.ndarray:
    ev = np.zeros((len(districts), N_EVENT_FEATURES, win.n_hours))
    ev[:, EID, :] = -1
    for e in session.scalars(select(Event).where(Event.ends_at > win.start,
                                                 Event.starts_at < win.end)):
        rows = [districts.index(e.district)] if e.district in districts else (
            list(range(len(districts))) if e.district is None else [])
        span = _hour_span(e.starts_at, e.ends_at, win)
        if span.stop <= span.start:
            continue
        kind = EventType(e.type)
        first = win.hour_index(_utc(e.starts_at))  # may lie before the window start
        for r in rows:
            if kind is EventType.eid:
                ev[r, EID, span] = (np.arange(span.start, span.stop) - first) // 24
            elif kind is EventType.salary:
                ev[r, WAGE if e.district else SALARY, span] = 1
            else:
                flag = {EventType.holiday: HOLIDAY, EventType.hat_bazar: HAT,
                        EventType.weather: SEVERE}[kind]
                ev[r, flag, span] = 1
    return ev


def _weather(session: Session, districts: list[str], win: Window,
             fill: WeatherFill | None) -> tuple[np.ndarray, np.ndarray]:
    rain = np.zeros((len(districts), win.n_days))
    temp = np.full((len(districts), win.n_days), 25.0)
    seen = np.zeros((len(districts), win.n_days), dtype=bool)
    first, last = win.start.date(), win.start.date() + timedelta(days=win.n_days - 1)
    for w in session.scalars(select(WeatherDaily).where(WeatherDaily.date >= first,
                                                        WeatherDaily.date <= last)):
        d: date = w.date
        i = win.day_index(d)
        if w.district in districts and 0 <= i < win.n_days:
            r = districts.index(w.district)
            rain[r, i], temp[r, i] = float(w.rain_mm), float(w.temp_c)
            seen[r, i] = True
    if fill is not None:
        days = win.days()
        for r, i in zip(*np.nonzero(~seen), strict=True):
            rain[r, i], temp[r, i] = fill(districts[int(r)], days[int(i)])
    return rain, temp


def load_panel(session: Session, end: int | None = None, window: Window = FIXED,
               since: int = 0, weather_fill: WeatherFill | None = None) -> Panel:
    """Read the panel; demand after hour index `end` (exclusive) and before `since` is left at
    zero (features look back at most 4 weeks, so a live tick reads only that much)."""
    end = window.n_hours if end is None else end
    agents, districts = _agents(session)
    row_of = {a.id: i for i, a in enumerate(agents)}
    rain, temp = _weather(session, districts, window, weather_fill)
    loc = window.local_hours()
    return Panel(
        agent_ids=np.array([a.id for a in agents], dtype=np.int64),
        tier=np.array([a.tier for a in agents], dtype=float),
        area=np.array([AREA_CODE[UrbanRural(a.urban_rural)] for a in agents], dtype=float),
        district=np.array([districts.index(a.district) for a in agents], dtype=np.int64),
        cash_cap=np.array([float(a.cash_capacity) for a in agents]),
        emoney_cap=np.array([float(a.emoney_capacity) for a in agents]),
        districts=districts,
        demand=_demand(session, row_of, end, window, since),
        events=_events(session, districts, window),
        rain_mm=rain,
        temp_c=temp,
        hour=np.array([t.hour for t in loc], dtype=float),
        dow=np.array([t.weekday() for t in loc], dtype=float),
        dom=np.array([t.day for t in loc], dtype=float),
        window=window,
        region=np.array([region_code(a.region) for a in agents], dtype=np.int64),
    )
