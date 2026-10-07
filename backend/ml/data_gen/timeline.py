"""Simulated timeline: local time is Asia/Dhaka (UTC+6, no DST).

The module constants are the FIXED timeline (clock mode "fixed": tests, benchmarks, the trained
artifacts). `Window` is the same idea for any span; live mode builds one around the current hour
(`live_window`), so hour indexes always count from a window's own start.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

import numpy as np

BDT = timezone(timedelta(hours=6), "Asia/Dhaka")

START = datetime(2026, 1, 5, tzinfo=BDT)
N_DAYS = 120
N_HOURS = N_DAYS * 24
END = START + timedelta(hours=N_HOURS)  # exclusive: 2026-05-05 00:00
HOLDOUT_DAYS = 14
HOLDOUT_START = START + timedelta(days=N_DAYS - HOLDOUT_DAYS)  # 2026-04-21 00:00
# Validation: the 14 days before the holdout. Model selection, thresholds and calibration are
# chosen here; served models never train on it, and the holdout is scored once (blind test).
VALIDATION_DAYS = 14
VAL_START = HOLDOUT_START - timedelta(days=VALIDATION_DAYS)  # 2026-04-07 00:00
# Fixed "now" of the demo; inside the holdout, so the 72 h after it are never trained on.
SIM_NOW = datetime(2026, 4, 30, 20, tzinfo=BDT)

# Python weekday numbers (Mon=0). Bangladesh weekend: Friday (+ Saturday for offices/banks).
SUN, MON, TUE, WED, THU, FRI, SAT = 6, 0, 1, 2, 3, 4, 5


def hour_index(ts: datetime) -> int:
    return int((ts - START) / timedelta(hours=1))


def day_index(d: date) -> int:
    return (d - START.date()).days


def days() -> list[date]:
    return [START.date() + timedelta(days=i) for i in range(N_DAYS)]


def local_hours() -> list[datetime]:
    return [START + timedelta(hours=i) for i in range(N_HOURS)]


def utc_hours() -> list[datetime]:
    return [t.astimezone(UTC) for t in local_hours()]


def weekday_of_day() -> np.ndarray:
    return np.array([d.weekday() for d in days()], dtype=np.int64)


def hour_of_day() -> np.ndarray:
    return np.arange(N_HOURS, dtype=np.int64) % 24


def holdout_mask() -> np.ndarray:
    return np.arange(N_HOURS) >= hour_index(HOLDOUT_START)


# --- windows ---------------------------------------------------------------------------------

LIVE_HISTORY_DAYS = N_DAYS  # live mode keeps the same 120 days of history before today
LIVE_FUTURE_DAYS = 3  # calendar room for the 72 h forecast after the current hour


def midnight(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=BDT)


@dataclass(frozen=True)
class Window:
    """Hours [start, start + n_days) in local days. Hour index 0 = start (local midnight)."""

    start: datetime
    n_days: int
    holdout_start: datetime

    @property
    def n_hours(self) -> int:
        return self.n_days * 24

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=self.n_hours)

    def hour_index(self, ts: datetime) -> int:
        aware = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
        return int((aware - self.start) // timedelta(hours=1))

    def ts_of(self, t: int) -> datetime:
        return (self.start + timedelta(hours=t)).astimezone(UTC)

    def day_index(self, d: date) -> int:
        return (d - self.start.date()).days

    def days(self) -> list[date]:
        return [self.start.date() + timedelta(days=i) for i in range(self.n_days)]

    def local_hours(self) -> list[datetime]:
        return [self.start + timedelta(hours=i) for i in range(self.n_hours)]


FIXED = Window(START, N_DAYS, HOLDOUT_START)


def live_window(origin: datetime) -> Window:
    """History from LIVE_HISTORY_DAYS before the origin's local day, through LIVE_FUTURE_DAYS
    after it; the holdout is the last 14 days before the origin's day."""
    day = origin.astimezone(BDT).date()
    return Window(midnight(day - timedelta(days=LIVE_HISTORY_DAYS)),
                  LIVE_HISTORY_DAYS + 1 + LIVE_FUTURE_DAYS,
                  midnight(day - timedelta(days=HOLDOUT_DAYS)))
