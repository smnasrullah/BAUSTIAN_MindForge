"""LLM call log page and daily usage (tokens, latency, cache hits, guard failures, cap)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm import store
from app.llm.mode import LIVE
from app.models import LlmCallLog, User
from app.models.enums import GeneratedBy, GuardResult, LlmIntent
from app.schemas.admin_ops import LlmLogItem, LlmLogPage, LlmUsage, LlmUsageDay

# service.py logs a cache hit with provider "cache".
CACHE_PROVIDER = "cache"


@dataclass(frozen=True)
class LlmLogFilter:
    intent: LlmIntent | None = None
    generated_by: GeneratedBy | None = None
    guard_result: GuardResult | None = None
    cache_hit: bool | None = None


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def log_page(session: Session, f: LlmLogFilter, page: int, page_size: int) -> LlmLogPage:
    q = select(LlmCallLog, User.email).outerjoin(User, User.id == LlmCallLog.user_id)
    if f.intent is not None:
        q = q.where(LlmCallLog.intent == f.intent)
    if f.generated_by is not None:
        q = q.where(LlmCallLog.generated_by == f.generated_by)
    if f.guard_result is not None:
        q = q.where(LlmCallLog.guard_result == f.guard_result)
    if f.cache_hit is not None:
        q = q.where((LlmCallLog.provider == CACHE_PROVIDER) if f.cache_hit
                    else (LlmCallLog.provider != CACHE_PROVIDER))
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.execute(q.order_by(LlmCallLog.id.desc())
                           .offset((page - 1) * page_size).limit(page_size)).tuples()
    items = [LlmLogItem(
        id=c.id, created_at=_utc(c.created_at), user_id=c.user_id, user_email=email,
        intent=c.intent, provider=c.provider, model=c.model, lang=c.lang,
        prompt_tokens=c.prompt_tokens, completion_tokens=c.completion_tokens,
        latency_ms=c.latency_ms, generated_by=c.generated_by, guard_result=c.guard_result,
        cache_hit=c.provider == CACHE_PROVIDER, error=c.error) for c, email in rows]
    return LlmLogPage(items=items, total=total, page=page, page_size=page_size)


def _p95(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))])


def _utc_day(session: Session) -> ColumnElement[date]:
    """created_at as a UTC calendar day (SQLite stores naive UTC; Postgres converts first)."""
    if session.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone("UTC", LlmCallLog.created_at))
    return func.date(LlmCallLog.created_at)


def usage(session: Session, settings: Settings, days: int) -> LlmUsage:
    """Per UTC day over the last `days` days (today included), oldest first."""
    today = datetime.now(UTC).date()
    first = today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    # Aggregated in SQL per UTC day: loading every logged call (it grows with every briefing or
    # explanation view) took 250 ms at 6,000 rows on the verify stack.
    by_day: dict[date, LlmUsageDay] = {
        first + timedelta(days=i): LlmUsageDay(
            day=first + timedelta(days=i), calls=0, live_calls=0, cache_hits=0, replay=0,
            template=0, guard_failures=0, prompt_tokens=0, completion_tokens=0)
        for i in range(days)}
    window = LlmCallLog.created_at >= start
    is_cache = LlmCallLog.provider == CACHE_PROVIDER

    def count(cond: ColumnElement[bool]) -> ColumnElement[int]:
        return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)

    day_col = _utc_day(session)
    rows = session.execute(
        select(day_col.label("day"), func.count().label("calls"),
               count(LlmCallLog.provider.in_(LIVE)), count(is_cache),
               count(LlmCallLog.generated_by == GeneratedBy.replay),
               count(LlmCallLog.generated_by == GeneratedBy.template),
               count(LlmCallLog.guard_result != GuardResult.passed),
               func.coalesce(func.sum(LlmCallLog.prompt_tokens), 0),
               func.coalesce(func.sum(LlmCallLog.completion_tokens), 0))
        .where(window).group_by(day_col)).all()
    for day_value, calls, live, hits, replay, template, guard, prompt, completion in rows:
        d = by_day.get(day_value if isinstance(day_value, date) else date.fromisoformat(day_value))
        if d is None:
            continue
        d.calls, d.live_calls, d.cache_hits = int(calls), int(live), int(hits)
        d.replay, d.template, d.guard_failures = int(replay), int(template), int(guard)
        d.prompt_tokens, d.completion_tokens = int(prompt), int(completion)
    # Latency of calls that did work (cache hits answer in ~0 ms and would hide slow providers).
    latencies = list(session.scalars(select(LlmCallLog.latency_ms).where(window, ~is_cache)))
    total = sum(d.calls for d in by_day.values())
    hits = sum(d.cache_hits for d in by_day.values())
    today_calls = store.live_calls_today(session)
    cap = settings.llm_daily_call_cap
    return LlmUsage(
        days=list(by_day.values()), calls_today=today_calls, daily_cap=cap,
        cap_used=round(today_calls / cap, 4) if cap > 0 else 0.0, total_calls=total,
        cache_hit_rate=round(hits / total, 4) if total else None,
        avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else None,
        p95_latency_ms=_p95(latencies),
        guard_failures=sum(d.guard_failures for d in by_day.values()),
        generated_at=datetime.now(UTC))
