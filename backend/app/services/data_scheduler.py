"""Background loop of the live data clock (CLOCK_MODE=live; off in fixed mode and in tests).

Every DATA_TICK_INTERVAL_S the loop looks at the clock. When the current hour is past the data
hour (or an admin asked for a tick), the one process holding the leader lock (app/core/leader.py)
runs data_clock.tick(): new hour(s) of data, then every cache except the daily holdout backtest.
A tick still running (data_clock.tick_guard) makes the next one skip; the skip is logged and
counted in the status. Right after a tick it wakes the help scheduler, so the help trigger reads
the fresh forecast at once, and the backtest job (backtest_job.py), which reruns the impact
backtest when the day moved. Status (last tick, its duration per stage, next tick, catch-up
progress, skipped ticks, last error) lives in system_meta data_clock_status and is shown on the
admin overview.
"""

import logging
import os
import socket
import threading
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.core.leader import Leader
from app.services import backtest_job, data_clock, help_scheduler, system_status
from ml.data_gen import live_load

log = logging.getLogger(__name__)
LOCK_ID = 7_310_455_003  # pg advisory lock key of the data clock leader
_stop = threading.Event()
_thread: threading.Thread | None = None


def next_tick_at() -> str:
    return (clock.hour_floor(clock.now()) + timedelta(hours=1)).isoformat()


def run_once(leader: Leader) -> str:
    """'waiting' (bootstrap not ready), 'standby' (another process leads), 'idle' (data is
    current), 'skipped' (the previous tick is still running), 'ran' or 'failed'."""
    settings = get_settings()
    if system_status.bootstrap_state(settings) != "ready":
        return "waiting"
    try:
        if not leader.acquire():
            return "standby"
    except Exception:  # noqa: BLE001 - database not reachable: try again next turn
        log.exception("data clock: leader check failed")
        return "failed"
    with data_clock.tick_guard() as free:
        if not free:
            _skipped()
            return "skipped"
        return _run(settings)


def _skipped() -> None:
    """A tick is still running (e.g. a leader that lost its lock but not its work): skip."""
    before = data_clock.status().get("skipped_ticks")
    count = (before if isinstance(before, int) else 0) + 1
    log.warning("data clock: previous tick still running; this tick is skipped (%d so far)",
                count)
    data_clock.write_status({"skipped_ticks": count, "last_skipped_at": clock.now().isoformat()})


def _run(settings: Settings) -> str:
    try:
        with Session(get_engine()) as s, s.begin():
            request = data_clock.take_request(s)
            hour = live_load.data_hour(s)
    except Exception:  # noqa: BLE001 - database not reachable: try again next turn
        log.exception("data clock: could not read the data hour")
        return "failed"
    target = clock.target_hour()
    if request is None and hour is not None and hour >= target:
        return "idle"
    who = f"{socket.gethostname()}:{os.getpid()}"
    reason = "manual" if request else "hourly"
    try:
        result = data_clock.tick(reason, settings, reanchor=bool(request and request["reanchor"]))
    except Exception as exc:  # noqa: BLE001 - one bad tick must not stop the loop
        log.exception("data clock tick failed")
        data_clock.write_status({"last_error": f"{type(exc).__name__}: {exc}"[:500],
                                 "last_error_at": clock.now().isoformat(), "leader": who,
                                 "next_tick_at": next_tick_at(), "catchup": None})
        return "failed"
    data_clock.write_status({"last_tick": asdict(result), "last_error": None, "leader": who,
                             "next_tick_at": next_tick_at(), "catchup": None,
                             "over_budget": result.duration_s > data_clock.TICK_BUDGET_S})
    help_scheduler.wake()
    backtest_job.wake()  # a new day may have moved the held-out window
    return "ran"


def _loop(interval_s: int) -> None:
    leader = Leader(get_engine(), "data-clock", LOCK_ID)
    try:
        while not _stop.is_set():
            run_once(leader)
            _stop.wait(interval_s)
    finally:
        leader.release()


def start(interval_s: int) -> None:
    global _thread
    if interval_s <= 0 or _thread is not None or not clock.is_live():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval_s,), name="data-clock", daemon=True)
    _thread.start()
    log.info("data clock started: checks every %d s", interval_s)


def stop(timeout_s: float = 10.0) -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout_s)
    _thread = None
