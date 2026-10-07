"""Admin background jobs: one at a time, progress written to admin_jobs from the worker thread.

Kinds:
- generate_data: rebuild the synthetic dataset from the configured seed, then precompute every
  cache. Same seed -> same rows, so this also proves the data is reproducible.
- retrain_forecast / retrain_anomaly: train into a candidate folder next to the artifacts and
  record an inactive model version. Serving keeps the committed, active model.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.models import AdminJob, AuditLog, User
from app.schemas.jobs import JobKind, JobList, JobOut, JobResultItem, JobStatus
from app.services import data_clock, help_trigger_run, model_registry, pipeline
from ml.data_gen import generate
from ml.registry import ANOMALY_MODEL, FORECAST_MODEL
from ml.training import anomaly as anomaly_train
from ml.training import train

log = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
# A job whose worker has not written for this long is reported as interrupted.
STALE_AFTER = timedelta(minutes=60)
RETRAIN_ROUNDS = train.ROUNDS
INTERRUPTED = "interrupted"

Progress = Callable[[str, int], None]


class JobError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _status(raw: str) -> JobStatus:
    for s in get_args(JobStatus):
        if raw == s:
            return s
    return "failed"


def _kind(raw: str) -> JobKind:
    for k in get_args(JobKind):
        if raw == k:
            return k
    raise JobError("unknown_kind")


def _text(value: Any) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def to_out(session: Session, job: AdminJob) -> JobOut:
    email = session.scalar(select(User.email).where(User.id == job.started_by)) \
        if job.started_by else None
    return JobOut(
        id=job.id, kind=_kind(job.kind), status=_status(job.status), progress=job.progress,
        step=job.step, error=job.error,
        result=[JobResultItem(key=k, value=_text(v)) for k, v in (job.result or {}).items()],
        started_by_email=email, created_at=_utc(job.created_at), updated_at=_utc(job.updated_at),
        finished_at=_utc(job.finished_at) if job.finished_at else None)


def _expire_stale(session: Session, job: AdminJob) -> None:
    if job.status in ACTIVE and datetime.now(UTC) - _utc(job.updated_at) > STALE_AFTER:
        job.status, job.error, job.finished_at = "failed", INTERRUPTED, datetime.now(UTC)
        session.flush()


def running(session: Session) -> AdminJob | None:
    job = session.scalars(select(AdminJob).where(AdminJob.status.in_(ACTIVE))
                          .order_by(AdminJob.id.desc()).limit(1)).first()
    if job is not None:
        _expire_stale(session, job)
        if job.status not in ACTIVE:
            return None
    return job


def latest(session: Session) -> AdminJob | None:
    return session.scalars(select(AdminJob).order_by(AdminJob.id.desc()).limit(1)).first()


def get(session: Session, job_id: int) -> AdminJob:
    job = session.get(AdminJob, job_id)
    if job is None:
        raise JobError("job_not_found")
    _expire_stale(session, job)
    return job


def recent(session: Session, limit: int = 20) -> JobList:
    active = running(session)
    rows = session.scalars(select(AdminJob).order_by(AdminJob.id.desc()).limit(limit))
    return JobList(items=[to_out(session, j) for j in rows],
                   running=to_out(session, active) if active else None)


def start(session: Session, user: User, kind: JobKind) -> AdminJob:
    """Queue a job (409 `job_running` while another one is active). Caller commits, then runs."""
    if running(session) is not None:
        raise JobError("job_running")
    now = datetime.now(UTC)
    job = AdminJob(kind=kind, status="queued", progress=0, step="queued", result={},
                   started_by=user.id, created_at=now, updated_at=now)
    session.add(job)
    session.flush()
    # The start is a human decision; the outcome lives on the job row.
    session.add(AuditLog(user_id=user.id, action=f"job.{kind}", entity_type="job",
                         entity_id=str(job.id), note=None, payload={"kind": kind}))
    return job


def mark_interrupted(session: Session) -> int:
    """Bootstrap: no worker survives a restart, so active jobs are failed as interrupted."""
    res = session.execute(update(AdminJob).where(AdminJob.status.in_(ACTIVE)).values(
        status="failed", error=INTERRUPTED, finished_at=datetime.now(UTC)))
    return int(getattr(res, "rowcount", 0) or 0)


# --- worker ---------------------------------------------------------------------------------

def _write(job_id: int, **values: Any) -> None:
    with Session(get_engine()) as session, session.begin():
        session.execute(update(AdminJob).where(AdminJob.id == job_id)
                        .values(updated_at=datetime.now(UTC), **values))


def _progress(job_id: int) -> Progress:
    def report(step: str, pct: int) -> None:
        _write(job_id, status="running", step=step, progress=max(0, min(99, pct)))
        log.info("job %d: %s (%d%%)", job_id, step, pct)
    return report


# Share of the bar each precompute stage reaches when it starts (data job).
_PRECOMPUTE_PCT = {"forecast": 55, "risk": 70, "rebalance": 78, "anomalies": 86, "backtest": 92}


def _generate_data(settings: Settings, job_id: int, p: Progress) -> dict[str, Any]:
    p("generate", 5)
    if clock.is_live():  # a fresh 120-day window ending at the current hour
        counts = data_clock.regenerate(settings, clock.target_hour())
    else:
        counts = generate.run(seed=settings.seed)
    p("precompute", 50)
    pipeline.precompute(settings, lambda name: p(f"precompute:{name}",
                                                 _PRECOMPUTE_PCT.get(name, 50)))
    return {"seed": settings.seed, **{f"rows.{k}": v for k, v in counts.items()}}


def _candidate_dir(settings: Settings, job_id: int, name: str) -> Path:
    return settings.artifacts_dir.parent / "candidates" / f"{name}-job-{job_id}"


def _register(model_name: str, manifest: dict[str, Any], metrics: dict[str, Any],
              out: Path) -> dict[str, Any]:
    with Session(get_engine()) as session, session.begin():
        active = model_registry.active_model(session, model_name)
        row, reproduced = model_registry.register_candidate(session, model_name, manifest,
                                                            metrics)
        return {"version": row.version, "reproduced": reproduced,
                "active_version": active.version if active else None,
                "candidate_dir": out.name}


LIVE_RETRAIN = ("retraining reads the fixed training timeline; run it with CLOCK_MODE=fixed "
                "(the live clock serves the committed models)")


def _retrain_forecast(settings: Settings, job_id: int, p: Progress) -> dict[str, Any]:
    if clock.is_live():
        raise RuntimeError(LIVE_RETRAIN)
    out = _candidate_dir(settings, job_id, "forecast")
    p("load", 3)
    fits = 0

    def step(name: str) -> None:
        nonlocal fits
        if name == "panel":
            p("fit", 10)
        elif name.startswith("fit:"):
            fits += 1
            p(name, 10 + fits * 12)  # 6 boosters (2 targets x 3 quantiles) -> 82%
        elif name == "evaluate":
            p("evaluate", 85)

    manifest = train.run(out, settings.seed, RETRAIN_ROUNDS, step)
    p("register", 95)
    metrics: dict[str, Any] = manifest["forecast"]["holdout_metrics"]
    result = _register(FORECAST_MODEL, manifest, metrics, out)
    for target in ("cash_out", "cash_in"):
        skill = metrics.get(target, {}).get("mae_skill")
        if skill is not None:
            result[f"{target}.mae_skill"] = skill
    return result


def _retrain_anomaly(settings: Settings, job_id: int, p: Progress) -> dict[str, Any]:
    if clock.is_live():
        raise RuntimeError(LIVE_RETRAIN)
    out = _candidate_dir(settings, job_id, "anomaly")
    p("fit", 10)
    manifest = anomaly_train.run(out, settings.seed)
    p("register", 90)
    metrics: dict[str, Any] = manifest["anomaly"]["metrics"]
    result = _register(ANOMALY_MODEL, manifest, metrics, out)
    holdout = metrics.get("holdout", {})
    for key in ("precision", "recall"):
        if key in holdout:
            result[f"holdout.{key}"] = holdout[key]
    return result


def _help_trigger(settings: Settings, job_id: int, p: Progress) -> dict[str, Any]:
    """One help-trigger tick (sweep, wave advance, trigger); the same tick the scheduler runs."""
    p("trigger", 10)
    report = help_trigger_run.tick_report()
    result: dict[str, Any] = dict(report.counts)
    run = report.run
    # Dry run / kill switch: say so, and list what WOULD have been sent and to whom.
    result["dry_run"], result["enabled"], result["sent"] = run.dry_run, run.enabled, run.sent
    result["would_create"] = len(run.would_create)
    for plan in run.would_create:
        result[f"would_ask.{plan.agent_code}.{plan.float_type.value}"] = ", ".join(
            a.display for a in plan.asks)
    return result


RUNNERS: dict[str, Callable[[Settings, int, Progress], dict[str, Any]]] = {
    "generate_data": _generate_data,
    "retrain_forecast": _retrain_forecast,
    "retrain_anomaly": _retrain_anomaly,
    "help_trigger": _help_trigger,
}


def run(job_id: int, kind: JobKind) -> None:
    """Background task body. Never raises: the outcome is written to the job row."""
    p = _progress(job_id)
    try:
        p("start", 1)
        result = RUNNERS[kind](get_settings(), job_id, p)
    except Exception as exc:  # noqa: BLE001 - every failure must land on the job row
        log.exception("job %d (%s) failed", job_id, kind)
        _write(job_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
               finished_at=datetime.now(UTC))
        return
    _write(job_id, status="succeeded", step="done", progress=100, finished_at=datetime.now(UTC),
           result={k: v for k, v in result.items() if v is not None})
