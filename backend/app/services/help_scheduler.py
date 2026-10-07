"""Background loop for the help trigger: one tick every interval (HELP_TRIGGER_INTERVAL_S).

A tick = claim-timeout sweep, wave advance, trigger (help_trigger_run.tick). It runs only
- once bootstrap is ready (before that the tables or the forecast may not exist yet), and in
  DEMO_MODE, after a FRESH bootstrap only (the database was seeded in that run), not before
  HELP_SCHEDULER_DEMO_START_DELAY_S after it became ready (a new demo does not open with a
  burst of requests); a plain restart does not wait again, and
- in the one process holding the leader lock (app/core/leader.py: Postgres advisory lock,
  file lock on SQLite), so several workers or instances never act twice.
Every tick is idempotent anyway (dedupe, compare-and-set moves), as a second line of defence.

The leader writes its status (last_run_at, last_result, next_run_at, last_error) into one
system_meta row, upserted per tick (no admin job row per tick); GET /admin/overview shows it.
Interval 0 turns the loop off. main.py starts it outside tests.
"""

import logging
import os
import socket
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.leader import Leader
from app.models import SystemMeta
from app.services import help_trigger_run, system_status

log = logging.getLogger(__name__)
STATUS_KEY = "help_scheduler_status"
FRESH_SEED_KEY = "bootstrap_fresh_seed"  # bootstrap.py seed: this run seeded the database
FRESH_READY_KEY = "bootstrap_fresh_ready_at"  # bootstrap.py mark-ready: when that run was ready
LOCK_ID = 7_310_455_001  # pg advisory lock key of the help scheduler (any fixed bigint)
WAIT_POLL_S = 5  # while bootstrap runs (or the demo start delay), look again this often
QUIET = {"waiting": "waiting for bootstrap",
         "demo_delay": "DEMO_MODE: first tick held for the start delay",
         "standby": "another process is the leader; standing by"}
_stop = threading.Event()
# Set by the live data clock right after a tick: run the trigger now on the fresh forecast.
_wake = threading.Event()
_thread: threading.Thread | None = None
# This process: whether it has ticked since it started.
_start: dict[str, bool] = {"ticked": False}


def fresh_ready_at() -> datetime | None:
    """When the last fresh bootstrap (a newly seeded database) became ready, if recorded."""
    with Session(get_engine()) as s:
        row = s.get(SystemMeta, FRESH_READY_KEY)
    if row is None or not isinstance(row.value, str):
        return None
    return clock.as_utc(datetime.fromisoformat(row.value))


def _held_for_demo(now: datetime) -> bool:
    """DEMO_MODE: after a fresh bootstrap, hold the first tick until ready + the start delay."""
    settings = get_settings()
    if not settings.demo_mode or _start["ticked"]:
        return False
    since = fresh_ready_at()
    if since is None:
        return False  # a restart of an existing database: no delay
    return now < since + timedelta(seconds=settings.help_scheduler_demo_start_delay_s)


def _write_status(values: dict[str, Any]) -> None:
    try:
        with Session(get_engine()) as s, s.begin():
            row = s.get(SystemMeta, STATUS_KEY)
            before = row.value if row is not None and isinstance(row.value, dict) else {}
            s.merge(SystemMeta(key=STATUS_KEY, value={**before, **values}))
    except Exception:  # noqa: BLE001 - status is best effort; the tick itself already ran
        log.exception("help scheduler: could not write status")


def run_once(leader: Leader, interval_s: int) -> str:
    """One turn of the loop: 'waiting' (bootstrap not ready), 'demo_delay' (DEMO_MODE start
    delay), 'standby' (another process leads), 'ran' or 'failed'."""
    if system_status.bootstrap_state(get_settings()) != "ready":
        return "waiting"
    if _held_for_demo(clock.now()):
        return "demo_delay"
    try:
        if not leader.acquire():
            return "standby"
    except Exception:  # noqa: BLE001 - database not reachable: try again next turn
        log.exception("help scheduler: leader check failed")
        return "failed"
    started = clock.now()
    next_run = (started + timedelta(seconds=interval_s)).isoformat()
    who = f"{socket.gethostname()}:{os.getpid()}"
    try:
        counts = help_trigger_run.tick(started)
    except Exception as exc:  # noqa: BLE001 - one bad tick must not stop the loop
        log.exception("help scheduler tick failed")
        _write_status({"last_run_at": started.isoformat(), "last_result": None,
                       "last_error": f"{type(exc).__name__}: {exc}"[:500],
                       "next_run_at": next_run, "leader": who, "interval_s": interval_s})
        return "failed"
    _start["ticked"] = True
    log.info("help scheduler tick: %s", counts)
    _write_status({"last_run_at": started.isoformat(), "last_result": counts,
                   "last_error": None, "next_run_at": next_run, "leader": who,
                   "interval_s": interval_s})
    return "ran"


def _loop(interval_s: int) -> None:
    leader = Leader(get_engine(), "help-scheduler", LOCK_ID)
    last = ""
    try:
        while not _stop.is_set():
            outcome = run_once(leader, interval_s)
            if outcome != last and outcome in QUIET:
                log.info("help scheduler: %s", QUIET[outcome])
            last = outcome
            short = outcome in ("waiting", "demo_delay")
            _wake.wait(min(interval_s, WAIT_POLL_S) if short else interval_s)
            _wake.clear()
    finally:
        leader.release()


def wake() -> None:
    """Run the next tick now (this process's loop; the leader is the one that acts)."""
    _wake.set()


def start(interval_s: int) -> None:
    global _thread
    if interval_s <= 0 or _thread is not None:
        return
    _stop.clear()
    _wake.clear()
    _thread = threading.Thread(target=_loop, args=(interval_s,), name="help-trigger",
                               daemon=True)
    _thread.start()
    log.info("help scheduler started: every %d s", interval_s)


def stop(timeout_s: float = 10.0) -> None:
    """Ask the loop to end and wait (at most timeout_s) for a running tick to finish."""
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout_s)
    _thread = None
