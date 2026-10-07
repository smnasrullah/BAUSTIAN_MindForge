"""Live data clock: keeps the synthetic data and every cache at the current hour.

- needs_regenerate(): no live data yet, another data version or mode, or a gap above
  DATA_REGEN_GAP_DAYS -> a fresh 120-day window ending at the current hour.
- catch_up(): append the missing hours in batches of DATA_CATCHUP_BATCH_H, one transaction each
  (safe to interrupt; the next run continues from the last committed hour, same values).
- tick(): catch up (or regenerate), then recompute forecasts, stock-out + risk, rebalance +
  swaps and anomaly flags for the new origin. The daily holdout impact backtest is NOT part of
  the tick: backtest_job.py runs it on its own (own leader lock, own budget).
- tick_guard(): a tick still running (in any process) makes the next one skip.

Every writer takes the same database lock (a Postgres transaction-level advisory lock), so the
scheduler tick, the bootstrap catch-up and the admin "generate data" job never interleave. The
scheduler (data_scheduler.py) runs ticks in the one leader process only. Fixed clock: no-ops.
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import DATA_VERSION, Settings, get_settings
from app.core.db import get_engine
from app.core.leader import Leader
from app.models import SystemMeta
from app.services import pipeline
from ml.data_gen import live_load
from ml.data_gen.dataset import N_AGENTS

log = logging.getLogger(__name__)
STATUS_KEY = "data_clock_status"
REQUEST_KEY = "data_clock_request"
WRITE_LOCK_ID = 7_310_455_002  # pg advisory lock key shared by every data writer
TICK_LOCK_ID = 7_310_455_004  # pg advisory lock key held while a tick runs (non-overlap guard)
TICK_BUDGET_S = 60.0


@contextmanager
def tick_guard() -> Iterator[bool]:
    """Yields False when a tick is already running here or in another process (the caller then
    skips its tick). Postgres: session advisory lock; SQLite: file lock (app/core/leader.py)."""
    guard = Leader(get_engine(), "data-tick", TICK_LOCK_ID)
    free = guard.acquire()
    try:
        yield free
    finally:
        if free:
            guard.release()


def lock_writers(session: Session) -> None:
    """Serialise data writers (released at commit/rollback). SQLite has one writer anyway."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": WRITE_LOCK_ID})


def _meta(session: Session, key: str) -> Any:
    row = session.get(SystemMeta, key)
    return row.value if row else None


def needs_regenerate(session: Session, settings: Settings, target: datetime) -> str | None:
    """Why the live window must be rebuilt, or None when catch-up is enough."""
    if _meta(session, "data_version") != DATA_VERSION:
        return "data_version"
    if _meta(session, "clock_mode") != "live":
        return "clock_mode"
    if _meta(session, "seed") != settings.seed:
        return "seed"
    hour = live_load.data_hour(session)
    if hour is None:
        return "no_state"
    if hour > target:
        return "data_ahead_of_clock"  # the clock moved back (CLOCK_SHIFT_H): never keep future
    if target - hour > timedelta(days=settings.data_regen_gap_days):
        return "gap"
    return None


def regenerate(settings: Settings, target: datetime, n_agents: int = N_AGENTS) -> dict[str, int]:
    with Session(get_engine()) as session, session.begin():
        lock_writers(session)
        counts = live_load.regenerate(session, settings.seed, n_agents, target)
    log.info("live data window regenerated up to %s: %s", target.isoformat(), counts)
    return counts


Progress = Callable[[datetime, datetime, int], None]


def catch_up(settings: Settings, target: datetime, progress: Progress | None = None) -> int:
    """Append hours up to `target`; returns hours written. Each batch commits on its own."""
    total = 0
    start = None
    while True:
        with Session(get_engine()) as session, session.begin():
            lock_writers(session)
            if start is None:
                start = live_load.data_hour(session)
            n = live_load.append(session, settings.seed, target, settings.data_catchup_batch_h)
        if n == 0:
            break
        total += n
        if progress is not None and start is not None:
            progress(start, target, total)
        log.info("live data: +%d h (total %d) towards %s", n, total, target.isoformat())
    return total


def ensure_story(settings: Settings) -> bool:
    """DEMO_MODE: when no demo story is ahead of the clock, anchor a new one at the data hour."""
    if not settings.demo_mode:
        return False
    with Session(get_engine()) as session, session.begin():
        lock_writers(session)
        if live_load.active_story(session, clock.data_now(session)) is not None:
            return False
        story = live_load.reanchor(session, settings.seed)
    return story is not None


@dataclass
class TickResult:
    reason: str
    started_at: str
    from_hour: str | None
    to_hour: str
    hours: int
    regenerated: str | None
    story_reanchored: bool
    precomputed: bool
    duration_s: float
    stages_s: dict[str, float] = field(default_factory=dict)


def write_status(values: dict[str, Any]) -> None:
    try:
        with Session(get_engine()) as s, s.begin():
            before = _meta(s, STATUS_KEY)
            s.merge(SystemMeta(key=STATUS_KEY, value={**(before or {}), **values}))
    except Exception:  # noqa: BLE001 - status is best effort
        log.exception("data clock: could not write status")


def status() -> dict[str, Any]:
    with Session(get_engine()) as s:
        value = _meta(s, STATUS_KEY)
    return value if isinstance(value, dict) else {}


def tick(reason: str, settings: Settings | None = None, reanchor: bool = False) -> TickResult:
    """Bring data and caches to the current hour. Live clock only."""
    settings = settings or get_settings()
    t0 = time.perf_counter()
    started = clock.now()
    target = clock.target_hour()
    with Session(get_engine()) as s:
        before = live_load.data_hour(s)
        why = needs_regenerate(s, settings, target)
    hours = 0
    if why is not None:
        write_status({"catchup": {"state": "regenerating", "reason": why,
                                   "to": target.isoformat()}})
        regenerate(settings, target)
    else:
        def progress(start: datetime, to: datetime, done: int) -> None:
            write_status({"catchup": {"state": "running", "from": start.isoformat(),
                                       "to": to.isoformat(), "hours_done": done}})
        hours = catch_up(settings, target, progress)
    story = ensure_story(settings) if (reanchor or why is not None or hours) else False
    stages: dict[str, float] = {"data": round(time.perf_counter() - t0, 2)}
    precomputed = bool(hours or why or story or reanchor or reason == "manual")
    if precomputed:
        current = [time.perf_counter(), ""]

        def timed(name: str) -> None:
            if current[1]:
                stages[str(current[1])] = round(time.perf_counter() - float(current[0]), 2)
            current[:] = [time.perf_counter(), name]

        pipeline.precompute(settings, timed, backtest_too=False)
        timed("")
    result = TickResult(reason=reason, started_at=started.isoformat(),
                        from_hour=before.isoformat() if before else None,
                        to_hour=target.isoformat(), hours=hours, regenerated=why,
                        story_reanchored=story, precomputed=precomputed,
                        duration_s=round(time.perf_counter() - t0, 2), stages_s=stages)
    log.info("data tick (%s): %s", reason, asdict(result))
    return result


def request_tick(session: Session, user_id: str, reanchor: bool = False) -> dict[str, Any]:
    """Ask the leader to tick now (it polls this flag). The caller audits and commits."""
    value = {"requested_at": clock.now().isoformat(), "by": user_id, "reanchor": reanchor}
    session.merge(SystemMeta(key=REQUEST_KEY, value=value))
    return value


def take_request(session: Session) -> dict[str, Any] | None:
    row = session.get(SystemMeta, REQUEST_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    value = dict(row.value)
    session.delete(row)
    return value
