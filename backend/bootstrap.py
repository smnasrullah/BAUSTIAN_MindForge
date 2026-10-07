"""Idempotent bootstrap steps, called one by one from scripts/bootstrap.sh.

Exit codes for checks: 0 = work needed, 1 = already done.
"""

import argparse
import logging
import secrets
import sys
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import DATA_VERSION, get_settings
from app.core.db import get_engine
from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole
from app.models.system_meta import SystemMeta
from app.services import auth, data_clock, help_scheduler, jobs, notifications, pipeline
from app.services import seed as reference_seed
from ml import registry
from ml.data_gen import generate
from ml.training import train

log = logging.getLogger("bootstrap")


def _get_meta(session: Session, key: str) -> Any:
    row = session.scalar(select(SystemMeta).where(SystemMeta.key == key))
    return row.value if row else None


def _set_meta(session: Session, key: str, value: Any) -> None:
    session.merge(SystemMeta(key=key, value=value))


def wait_db(attempts: int = 60, delay_s: float = 2.0) -> int:
    for i in range(1, attempts + 1):
        try:
            with get_engine().connect():
                log.info("database reachable")
                return 0
        except OperationalError:
            log.info("waiting for database (%d/%d)", i, attempts)
            time.sleep(delay_s)
    log.error("database not reachable")
    return 1


def needs_seed() -> int:
    """Fixed clock: data version changed. Live clock: also no live window yet, another seed or
    mode, or a gap above DATA_REGEN_GAP_DAYS (catch-up handles smaller gaps)."""
    settings = get_settings()
    with Session(get_engine()) as session:
        current = _get_meta(session, "data_version")
        mode = _get_meta(session, "clock_mode") or "fixed"
        why = (data_clock.needs_regenerate(session, settings, clock.target_hour())
               if clock.is_live() else None)
    if why is not None:
        log.info("live data window needs a rebuild: %s", why)
    stale = current != DATA_VERSION or mode != settings.clock_mode or why is not None
    return 0 if stale else 1


def seed() -> int:
    settings = get_settings()
    seed_reference()
    if clock.is_live():
        counts = data_clock.regenerate(settings, clock.target_hour())
    else:
        counts = generate.run(seed=settings.seed)
    seed_helpers()  # logins for agents that only exist now (seed.HELPER_USERS)
    with Session(get_engine()) as session, session.begin():
        _set_meta(session, "seed", settings.seed)
        _set_meta(session, "data_version", DATA_VERSION)
        _set_meta(session, help_scheduler.FRESH_SEED_KEY, True)  # mark-ready stamps the time
    log.info("seeded data_version=%s seed=%d counts=%s", DATA_VERSION, settings.seed, counts)
    return 0


def seed_reference() -> int:
    """Re-run only the idempotent distributor/agent/user seed (e.g. after a password change)."""
    with Session(get_engine()) as session, session.begin():
        log.info("reference seed: %s", reference_seed.run(session, get_settings()))
    return 0


def seed_helpers() -> int:
    """Create missing helper-agent demo logins (seed.HELPER_USERS). Create-only: safe on every
    start and on an existing database; never resets a user."""
    with Session(get_engine()) as session, session.begin():
        log.info("helper logins created: %d", reference_seed.ensure_helpers(session,
                                                                           get_settings()))
    return 0


def catch_up() -> int:
    """Live clock: append the hours missed while the app was stopped (bounded batches, each its
    own transaction), then make sure a demo story lies ahead (DEMO_MODE). Fixed clock: no-op."""
    if not clock.is_live():
        return 0
    settings = get_settings()
    started = time.perf_counter()
    hours = data_clock.catch_up(settings, clock.target_hour())
    story = data_clock.ensure_story(settings)
    log.info("catch-up: %d h in %.1fs; new demo story: %s", hours,
             time.perf_counter() - started, story)
    return 0


def needs_train() -> int:
    ok, why = registry.verify(get_settings().artifacts_dir)
    if not ok:
        log.warning("artifacts need training: %s", why)
    return 1 if ok else 0


def run_train() -> int:
    if clock.is_live():  # training reads the fixed timeline, which a live database lacks
        log.error("forecast artifacts missing or invalid; restore the committed ones (git) or "
                  "train once with CLOCK_MODE=fixed")
        return 1
    log.warning("training from seed (slow path; committed artifacts were missing or invalid)")
    train.run(artifacts_dir=get_settings().artifacts_dir, seed=get_settings().seed)
    return 0


def precompute() -> int:
    """Register the active models and precompute every cache (app/services/pipeline.py).
    Logs how long each stage took (slow first starts are diagnosed from these lines)."""
    current: list[Any] = [time.perf_counter(), ""]

    def timed(name: str) -> None:
        if current[1]:
            log.info("precompute %s took %.1fs", current[1], time.perf_counter() - current[0])
        current[:] = [time.perf_counter(), name]

    pipeline.precompute(get_settings(), timed)
    timed("")
    return 0


E2E_INBOX_USER = "dist.dhaka@agentpulse.demo"


def seed_notifications() -> int:
    """e2e fixture: the demo distributor's inbox becomes all-read plus one known unread notice."""
    with Session(get_engine()) as session, session.begin():
        nid = notifications.seed_one_unread(session, E2E_INBOX_USER)
    log.info("seeded unread notification %d for %s", nid, E2E_INBOX_USER)
    return 0


E2E_WRONG_PASSWORD_USER = "agent.sunamganj@agentpulse.demo"
E2E_PENDING_USER = "e2e.pending@example.org"  # a11y spec: the admin "Reject" sign-up UI


def _pending_signup(session: Session) -> None:
    """One self-signup awaiting approval (created once, put back to pending if needed)."""
    user = session.scalar(select(User).where(User.email == E2E_PENDING_USER))
    if user is None:
        session.add(User(email=E2E_PENDING_USER, full_name="E2E Pending Signup",
                         password_hash=hash_password(secrets.token_urlsafe(24)),
                         role=UserRole.agent, agent_id=None, distributor_id=None,
                         is_active=False, is_pending=True, is_demo=False))
        return
    user.is_active, user.is_pending, user.is_rejected = False, True, False
    user.role, user.agent_id, user.distributor_id = UserRole.agent, None, None


def e2e_fixtures() -> int:
    """Known state before each e2e run (no DB reset): one unread notice for the distributor, no
    lockout left on the account the wrong-password spec uses, and one pending self-signup."""
    seed_notifications()
    with Session(get_engine()) as session, session.begin():
        n = auth.clear_login_failures(session, E2E_WRONG_PASSWORD_USER)
        _pending_signup(session)
    log.info("cleared %d login failures for %s; pending signup %s", n,
             E2E_WRONG_PASSWORD_USER, E2E_PENDING_USER)
    return 0


def mark_ready() -> int:
    with Session(get_engine()) as session, session.begin():
        _set_meta(session, "bootstrap_state", "ready")
        # Fresh bootstrap (seeded in this run): the DEMO_MODE scheduler start delay counts from
        # now. A plain restart keeps the old stamp, so it does not wait again.
        if _get_meta(session, help_scheduler.FRESH_SEED_KEY):
            _set_meta(session, help_scheduler.FRESH_READY_KEY, datetime.now(UTC).isoformat())
            _set_meta(session, help_scheduler.FRESH_SEED_KEY, False)
        # A restart killed any admin job that was still running in the old process.
        jobs.mark_interrupted(session)
    return 0


COMMANDS = {
    "wait-db": wait_db,
    "needs-seed": needs_seed,
    "seed": seed,
    "seed-reference": seed_reference,
    "seed-helpers": seed_helpers,
    "catch-up": catch_up,
    "needs-train": needs_train,
    "train": run_train,
    "precompute": precompute,
    "mark-ready": mark_ready,
    "seed-notifications": seed_notifications,
    "e2e-fixtures": e2e_fixtures,
}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[bootstrap] %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=sorted(COMMANDS))
    return COMMANDS[parser.parse_args().command]()


if __name__ == "__main__":
    sys.exit(main())
