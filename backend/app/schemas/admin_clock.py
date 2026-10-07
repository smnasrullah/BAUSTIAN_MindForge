from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.system import ClockInfo


class TickStage(BaseModel):
    name: str  # data | forecast | risk | rebalance | anomalies | backtest
    seconds: float


class TickInfo(BaseModel):
    reason: Literal["hourly", "manual"]
    started_at: datetime
    from_hour: datetime | None
    to_hour: datetime
    hours: int  # hours of data appended
    regenerated: str | None  # why the window was rebuilt instead (gap, data_version, ...)
    story_reanchored: bool
    precomputed: bool
    duration_s: float
    stages: list[TickStage]


class CatchupInfo(BaseModel):
    state: Literal["running", "regenerating"]
    from_hour: datetime | None
    to_hour: datetime | None
    hours_done: int


class DemoStoryInfo(BaseModel):
    agent_code: str
    refill_at: datetime
    stockout_at: datetime
    demo_event: str | None  # labelled synthetic event used when no real calendar day explains it


class BacktestJobInfo(BaseModel):
    """The daily holdout impact backtest: its own background job, outside the hourly tick."""

    state: Literal["running", "ok", "failed"]
    started_at: datetime | None  # the current (state running) or last run
    last_run_at: datetime | None  # start of the last finished run
    duration_s: float | None
    budget_s: float
    over_budget: bool
    last_error: str | None


class AdminClock(BaseModel):
    clock: ClockInfo
    tick_interval_s: int  # how often the leader looks for a new hour (live only)
    budget_s: float
    next_tick_at: datetime | None
    last_tick: TickInfo | None
    over_budget: bool
    catchup: CatchupInfo | None
    last_error: str | None
    last_error_at: datetime | None
    tick_requested_at: datetime | None
    demo_story: DemoStoryInfo | None
    generated_at: datetime
    backtest: BacktestJobInfo | None = None  # live clock: last run of the daily backtest job
    skipped_ticks: int = 0  # ticks skipped because the previous one was still running
    last_skipped_at: datetime | None = None


class TickRequestOut(BaseModel):
    requested_at: datetime
