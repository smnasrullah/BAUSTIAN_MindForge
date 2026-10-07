"""Admin system overview counts and the model registry listing."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.llm import store
from app.models import (
    Agent,
    Anomaly,
    Distributor,
    Event,
    ModelVersion,
    RecommendationRequest,
    SwapSuggestion,
    SystemMeta,
    User,
)
from app.models.enums import AnomalyStatus, RequestStatus, SwapStatus, UserRole
from app.schemas.admin import ActiveModel, AdminOverview, RoleCount, SchedulerStatus
from app.schemas.admin_ops import MetricItem, ModelRegistry, ModelVersionItem
from app.services import admin_audit, jobs

RECENT_AUDIT = 6
SCHEDULER_KEY = "help_scheduler_status"  # written by app/services/help_scheduler.py


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _count(session: Session, model: Any, *where: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def overview(session: Session, settings: Settings) -> AdminOverview:
    per_role = {role: (total, active) for role, total, active in session.execute(
        select(User.role, func.count(), func.count().filter(User.is_active.is_(True)))
        .group_by(User.role))}
    roles = [RoleCount(role=r, total=per_role.get(r, (0, 0))[0], active=per_role.get(r, (0, 0))[1])
             for r in UserRole]
    models = session.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))
                             .order_by(ModelVersion.model_name))
    job = jobs.latest(session)
    return AdminOverview(
        users=roles, distributors=_count(session, Distributor), agents=_count(session, Agent),
        events=_count(session, Event),
        open_anomalies=_count(session, Anomaly, Anomaly.status == AnomalyStatus.open),
        pending_swaps=_count(session, SwapSuggestion,
                             SwapSuggestion.status == SwapStatus.pending),
        open_requests=_count(session, RecommendationRequest,
                             RecommendationRequest.status == RequestStatus.requested),
        llm_calls_today=store.live_calls_today(session),
        llm_daily_cap=settings.llm_daily_call_cap,
        active_models=[ActiveModel(model_name=m.model_name, version=m.version,
                                   trained_at=_utc(m.trained_at)) for m in models],
        latest_job=jobs.to_out(session, job) if job else None,
        recent_audit=admin_audit.recent(session, RECENT_AUDIT),
        help_scheduler=scheduler_status(session, clock.now()),
        generated_at=datetime.now(UTC))


def _ts(value: object) -> datetime | None:
    return _utc(datetime.fromisoformat(value)) if isinstance(value, str) else None


def scheduler_status(session: Session, now: datetime) -> SchedulerStatus | None:
    row = session.get(SystemMeta, SCHEDULER_KEY)
    v = row.value if row is not None and isinstance(row.value, dict) else None
    if v is None:
        return None
    interval = v.get("interval_s") if isinstance(v.get("interval_s"), int) else None
    nxt = _ts(v.get("next_run_at"))
    result = v.get("last_result")
    return SchedulerStatus(
        interval_s=interval, last_run_at=_ts(v.get("last_run_at")),
        last_result={str(k): int(n) for k, n in result.items()}
        if isinstance(result, dict) else None,
        last_error=v.get("last_error") if isinstance(v.get("last_error"), str) else None,
        next_run_at=nxt, leader=v.get("leader") if isinstance(v.get("leader"), str) else None,
        stale=nxt is not None and now > nxt + timedelta(seconds=2 * (interval or 60)))


def flatten(metrics: dict[str, Any], prefix: str = "") -> list[MetricItem]:
    """Numeric leaves of a nested metrics document as dotted keys (booleans skipped)."""
    out: list[MetricItem] = []
    for key, value in metrics.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(flatten(value, f"{path}."))
        elif isinstance(value, int | float) and not isinstance(value, bool):
            out.append(MetricItem(key=path, value=float(value)))
    return out


def registry(session: Session) -> ModelRegistry:
    rows = session.scalars(select(ModelVersion).order_by(
        ModelVersion.model_name, ModelVersion.is_active.desc(), ModelVersion.trained_at.desc()))
    items = [ModelVersionItem(
        id=m.id, model_name=m.model_name, version=m.version, trained_at=_utc(m.trained_at),
        is_active=m.is_active, artifact_sha256=m.artifact_sha256,
        metrics=flatten(m.metrics or {}), created_at=_utc(m.created_at)) for m in rows]
    return ModelRegistry(items=items, generated_at=datetime.now(UTC))
