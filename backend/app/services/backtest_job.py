"""Background job of the live clock: the daily holdout impact + fairness backtest (F11, F12).

It used to run inside the first hourly tick after midnight and pushed that tick over its budget
(~45-75 s on top of ~30 s). Now the data clock wakes this loop after every tick (same process
only), and it also looks every POLL_S (a cheap key check). When the backtest key changed (a new
day moved the held-out window, the window was regenerated, rules or model changed), the one
process holding its own leader lock reruns backtest.precompute in one transaction, with its own
budget (BUDGET_S, reported only).

- It does not start while a tick runs (data_clock.tick_guard); a tick that starts during a
  backtest is never blocked by it.
- A run that fails or is skipped by the backtest itself (data does not match) is retried when
  the key changes or after RETRY_S, not every poll.
- Status (state running | ok | failed, last run, duration, over budget, last error) lives in
  system_meta backtest_job_status; GET /admin/clock shows it on the Data clock card.
Live clock only: in fixed mode bootstrap runs the backtest once and nothing moves.
"""

import json
import logging
import os
import socket
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.core.leader import Leader
from app.models import SystemMeta
from app.services import backtest, data_clock, system_status

log = logging.getLogger(__name__)
STATUS_KEY = "backtest_job_status"
LOCK_ID = 7_310_455_005  # pg advisory lock key of the backtest job leader
BUDGET_S = 180.0
POLL_S = 60  # the job leader may be another worker than the tick's, whose wake() misses it
WAIT_POLL_S = 5  # while bootstrap runs or a tick is running, look again this often
RETRY_S = 3600.0
_stop = threading.Event()
_wake = threading.Event()
_thread: threading.Thread | None = None
# This process: the key of the last run that did not leave the caches current, and when.
_last_try: dict[str, Any] = {"key": None, "at": 0.0}


def write_status(values: dict[str, Any]) -> None:
    try:
        with Session(get_engine()) as s, s.begin():
            row = s.get(SystemMeta, STATUS_KEY)
            before = row.value if row is not None and isinstance(row.value, dict) else {}
            s.merge(SystemMeta(key=STATUS_KEY, value={**before, **values}))
    except Exception:  # noqa: BLE001 - status is best effort
        log.exception("backtest job: could not write status")


def status() -> dict[str, Any]:
    with Session(get_engine()) as s:
        row = s.get(SystemMeta, STATUS_KEY)
    return row.value if row is not None and isinstance(row.value, dict) else {}


def _pending_key(settings: Settings) -> str | None:
    """The backtest key as text when the caches are stale, None when they are current."""
    with Session(get_engine()) as s:
        key = backtest.stale_key(s, settings)
    return None if key is None else json.dumps(key, sort_keys=True)


def run_once(leader: Leader) -> str:
    """'waiting' (bootstrap not ready), 'standby' (another process leads), 'busy' (a tick is
    running), 'current', 'retry_later' (the last run for this key failed or skipped), 'ran' or
    'failed'."""
    settings = get_settings()
    if system_status.bootstrap_state(settings) != "ready":
        return "waiting"
    try:
        if not leader.acquire():
            return "standby"
        with data_clock.tick_guard() as free:
            if not free:
                return "busy"
        key = _pending_key(settings)
    except Exception:  # noqa: BLE001 - database not reachable: try again next turn
        log.exception("backtest job: check failed")
        return "failed"
    if key is None:
        return "current"
    if key == _last_try["key"] and time.monotonic() - float(_last_try["at"]) < RETRY_S:
        return "retry_later"
    return run(settings, key)


def run(settings: Settings, key: str | None = None) -> str:
    """Run the backtest now (one transaction) and record its status."""
    started = clock.now().isoformat()
    who = f"{socket.gethostname()}:{os.getpid()}"
    write_status({"state": "running", "started_at": started, "leader": who, "budget_s": BUDGET_S})
    t0 = time.perf_counter()
    try:
        with Session(get_engine()) as s, s.begin():
            rows = backtest.precompute(s, settings)
    except Exception as exc:  # noqa: BLE001 - one bad run must not stop the loop
        log.exception("backtest job failed")
        _last_try.update(key=key, at=time.monotonic())
        took = round(time.perf_counter() - t0, 2)
        write_status({"state": "failed", "last_run_at": started, "duration_s": took,
                      "over_budget": took > BUDGET_S,
                      "last_error": f"{type(exc).__name__}: {exc}"[:500]})
        return "failed"
    took = round(time.perf_counter() - t0, 2)
    if rows == 0:  # skipped by the backtest itself (logged there): do not retry every poll
        _last_try.update(key=key, at=time.monotonic())
    if took > BUDGET_S:
        log.warning("backtest job took %.1f s (budget %.0f s)", took, BUDGET_S)
    log.info("backtest job: %d impact rows in %.1f s", rows, took)
    write_status({"state": "ok", "last_run_at": started, "duration_s": took, "rows": rows,
                  "over_budget": took > BUDGET_S, "last_error": None})
    return "ran"


def _loop(interval_s: int) -> None:
    leader = Leader(get_engine(), "backtest-job", LOCK_ID)
    try:
        while not _stop.is_set():
            outcome = run_once(leader)
            short = outcome in ("waiting", "busy")
            _wake.wait(WAIT_POLL_S if short else interval_s)
            _wake.clear()
    finally:
        leader.release()


def wake() -> None:
    """Look now (called by the data clock right after a tick)."""
    _wake.set()


def start(interval_s: int = POLL_S) -> None:
    global _thread
    if interval_s <= 0 or _thread is not None or not clock.is_live():
        return
    _stop.clear()
    _wake.clear()
    _thread = threading.Thread(target=_loop, args=(interval_s,), name="backtest-job",
                               daemon=True)
    _thread.start()
    log.info("backtest job started: looks every %d s and after each data tick", interval_s)


def stop(timeout_s: float = 10.0) -> None:
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout_s)
    _thread = None
