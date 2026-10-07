"""Admin overview card: clock mode, now, data hour, last/next tick, catch-up, demo story, and
the daily backtest job (live clock)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.models import AuditLog, Forecast, SystemMeta, User
from app.schemas.admin_clock import (
    AdminClock,
    BacktestJobInfo,
    CatchupInfo,
    DemoStoryInfo,
    TickInfo,
    TickStage,
)
from app.services import backtest_job, data_clock
from app.services.freshness import clock_info
from ml.data_gen import live_load
from ml.data_gen.demo_spec import STOCKOUT_AGENT
from ml.data_gen.live_story import DEMO_EVENT_EN


class ClockError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _ts(raw: Any) -> datetime | None:
    return clock.as_utc(datetime.fromisoformat(raw)) if isinstance(raw, str) else None


def _tick(raw: Any) -> TickInfo | None:
    if not isinstance(raw, dict):
        return None
    started, to = _ts(raw.get("started_at")), _ts(raw.get("to_hour"))
    if started is None or to is None:
        return None
    stages = raw.get("stages_s") or {}
    return TickInfo(reason="manual" if raw.get("reason") == "manual" else "hourly",
                    started_at=started, from_hour=_ts(raw.get("from_hour")), to_hour=to,
                    hours=int(raw.get("hours") or 0), regenerated=raw.get("regenerated"),
                    story_reanchored=bool(raw.get("story_reanchored")),
                    precomputed=bool(raw.get("precomputed")),
                    duration_s=float(raw.get("duration_s") or 0.0),
                    stages=[TickStage(name=str(k), seconds=float(v)) for k, v in stages.items()])


def _catchup(raw: Any) -> CatchupInfo | None:
    if not isinstance(raw, dict):
        return None
    state = "regenerating" if raw.get("state") == "regenerating" else "running"
    return CatchupInfo(state=state, from_hour=_ts(raw.get("from")), to_hour=_ts(raw.get("to")),
                       hours_done=int(raw.get("hours_done") or 0))


def _backtest(raw: dict[str, Any]) -> BacktestJobInfo | None:
    state = raw.get("state")
    if state not in ("running", "ok", "failed"):
        return None
    took = raw.get("duration_s")
    return BacktestJobInfo(state=state, started_at=_ts(raw.get("started_at")),
                           last_run_at=_ts(raw.get("last_run_at")),
                           duration_s=float(took) if isinstance(took, int | float) else None,
                           budget_s=float(raw.get("budget_s") or backtest_job.BUDGET_S),
                           over_budget=bool(raw.get("over_budget")),
                           last_error=raw.get("last_error"))


def _story(session: Session) -> DemoStoryInfo | None:
    if not clock.is_live():
        return None
    s = live_load.active_story(session, clock.data_now(session))
    if s is None:
        return None
    return DemoStoryInfo(agent_code=STOCKOUT_AGENT, refill_at=clock.as_utc(s.anchor),
                         stockout_at=clock.as_utc(s.stockout_at),
                         demo_event=DEMO_EVENT_EN if s.wage_day else None)


def overview(session: Session, settings: Settings) -> AdminClock:
    last = session.scalar(select(func.max(Forecast.generated_at)))
    st = data_clock.status()
    live = clock.is_live()
    request = session.get(SystemMeta, data_clock.REQUEST_KEY)
    requested = _ts(request.value.get("requested_at")) if request and isinstance(
        request.value, dict) else None
    nxt = clock.hour_floor(clock.now()) + timedelta(hours=1) if live else None
    return AdminClock(
        clock=clock_info(session, clock.as_utc(last) if last else None),
        tick_interval_s=settings.data_tick_interval_s if live else 0,
        budget_s=data_clock.TICK_BUDGET_S, next_tick_at=nxt, last_tick=_tick(st.get("last_tick")),
        over_budget=bool(st.get("over_budget")), catchup=_catchup(st.get("catchup")),
        last_error=st.get("last_error"), last_error_at=_ts(st.get("last_error_at")),
        tick_requested_at=requested, demo_story=_story(session),
        generated_at=datetime.now(UTC),
        backtest=_backtest(backtest_job.status()) if live else None,
        skipped_ticks=int(st.get("skipped_ticks") or 0),
        last_skipped_at=_ts(st.get("last_skipped_at")))


def request_tick(session: Session, user: User) -> datetime:
    """Admin "Run tick now": the leader runs it within one check interval. Audited."""
    if not clock.is_live():
        raise ClockError("clock_fixed")
    value = data_clock.request_tick(session, str(user.id))
    session.add(AuditLog(user_id=user.id, action="data_clock.tick", entity_type="settings",
                         entity_id=data_clock.REQUEST_KEY, note=None, payload=value))
    session.flush()
    return clock.as_utc(datetime.fromisoformat(value["requested_at"]))
