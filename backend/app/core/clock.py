"""The one clock of the app: wall time, the data clock, and the bridge between them.

Two modes (settings.clock_mode):
- live (default for run.bat, local runs and judges): now() is the real time (Asia/Dhaka is UTC+6,
  no DST) plus an optional CLOCK_SHIFT_H used only to verify catch-up. The synthetic data is
  generated up to the current hour and an hourly tick moves the forecast origin with it.
- fixed (tests, benchmarks, reproducible evaluation): the data clock is frozen at SIM_NOW.

data_now(session) is the forecast origin: the hour every prediction starts at (system_meta
sim_now, written by the data loader and by every live tick). In live mode it trails now() by at
most the time to the next tick. Every workflow timestamp (created_at, needed_by, claim timers,
notification times) is wall time from now(); forecast_to_wall() places a forecast moment on the
wall clock by keeping its distance from the origin. The server clock is the one clock for every
role, so all users see the same present.

Tests replace _source (monkeypatch) to get a fake wall clock everywhere at once.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from app.core.config import get_settings
from ml.data_gen.timeline import FIXED, SIM_NOW, Window, live_window

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ClockMode = Literal["live", "fixed"]
DATA_NOW_KEY = "sim_now"  # system_meta key of the forecast origin (name kept from fixed mode)


def mode() -> ClockMode:
    return get_settings().clock_mode


def is_live() -> bool:
    return mode() == "live"


def _system_now() -> datetime:
    now = datetime.now(UTC)
    settings = get_settings()
    if settings.clock_mode == "live" and settings.clock_shift_h:
        now += timedelta(hours=settings.clock_shift_h)
    return now


_source: Callable[[], datetime] = _system_now


def now() -> datetime:
    return _source()


def as_utc(ts: datetime) -> datetime:
    """Naive values (SQLite) are UTC; aware values are converted."""
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def hour_floor(ts: datetime) -> datetime:
    """Start of the hour (UTC and Asia/Dhaka hours coincide: the offset is whole hours)."""
    return as_utc(ts).replace(minute=0, second=0, microsecond=0)


def target_hour() -> datetime:
    """The hour the data should reach: the current hour (live) or SIM_NOW (fixed)."""
    return hour_floor(now()) if is_live() else as_utc(SIM_NOW)


def data_now(session: "Session") -> datetime:
    """The forecast origin stored with the data; SIM_NOW before any data exists."""
    from app.models import SystemMeta  # models import config only; keeps core import-light

    row = session.get(SystemMeta, DATA_NOW_KEY)
    return as_utc(datetime.fromisoformat(row.value)) if row and row.value else as_utc(SIM_NOW)


def window_at(origin: datetime) -> Window:
    """The timeline window predictions at this origin use."""
    return live_window(origin) if is_live() else FIXED


def window(session: "Session") -> Window:
    return window_at(data_now(session))


def lag_h(origin: datetime, wall_now: datetime) -> float:
    """Live: hours of the forecast already behind us (the origin trails now by < 1 tick).
    Fixed: 0 - the frozen origin is placed at `wall_now` (forecast_to_wall)."""
    if not is_live():
        return 0.0
    return max((as_utc(wall_now) - as_utc(origin)).total_seconds() / 3600, 0.0)


def forecast_to_wall(forecast_ts: datetime, origin: datetime, wall_now: datetime) -> datetime:
    """A moment on the forecast timeline -> wall clock, keeping its distance from the origin."""
    return as_utc(wall_now) + (as_utc(forecast_ts) - as_utc(origin))


def hours_after(wall_now: datetime, hours: float) -> datetime:
    """forecast_to_wall() for a forecast offset given in hours from the origin."""
    return as_utc(wall_now) + timedelta(hours=hours)
