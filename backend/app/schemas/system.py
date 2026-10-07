from datetime import datetime
from typing import Literal

from pydantic import BaseModel

BootstrapState = Literal[
    "starting",
    "waiting_for_db",
    "migrating",
    "seeding",
    "training",
    "precomputing",
    "finalizing",
    "ready",
    "failed",
]
LlmMode = Literal["anthropic", "openai_compatible", "replay", "template"]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class SystemStatus(BaseModel):
    ready: bool
    bootstrap_state: BootstrapState
    db: bool
    migration_current: str | None
    migration_head: str | None
    seed: int | None
    data_version: str | None
    artifacts_ok: bool
    model_version: str | None
    llm_mode: LlmMode
    demo_mode: bool
    # Reset links go to the server log (no email server). Development only.
    dev_mailer: bool
    generated_at: datetime


class DataPeriod(BaseModel):
    """Synthetic data window; the last 14 days are held out from training."""

    start: datetime
    end: datetime  # exclusive
    holdout_start: datetime
    sim_now: datetime  # the forecast origin every prediction starts at (the data clock)


ClockMode = Literal["live", "fixed"]


class ClockInfo(BaseModel):
    """The one server clock every role sees (app/core/clock.py)."""

    mode: ClockMode  # live: real time, Asia/Dhaka; fixed: frozen SIM_NOW (reproducible runs)
    timezone: Literal["Asia/Dhaka"]
    now: datetime  # server wall clock
    data_hour: datetime  # forecast origin: flows are logged up to here, balances at its top
    last_data_hour: datetime  # the last complete hour of logged flows (data_hour - 1 h)
    last_compute_at: datetime | None  # when forecasts, risk and the rest were last computed


class Freshness(BaseModel):
    last_forecast_at: datetime | None
    model_version: str | None
    data_period: DataPeriod
    llm_mode: LlmMode
    generated_at: datetime
    clock: ClockInfo | None = None  # always sent; optional only for older clients
