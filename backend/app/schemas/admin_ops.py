"""Admin console: synthetic data, model registry, forecast-error drift, LLM call log + usage."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.enums import FloatType, GeneratedBy, GuardResult, Lang, LlmIntent
from app.schemas.system import DataPeriod

# --- synthetic data -----------------------------------------------------------------------------


class DataCount(BaseModel):
    table: str
    rows: int


class DataSummary(BaseModel):
    seed: int | None
    configured_seed: int
    data_version: str | None
    period: DataPeriod
    counts: list[DataCount]
    labelled_anomalous_agents: int
    generated_at: datetime


class AssumptionsDoc(BaseModel):
    title: str
    markdown: str  # rendered by the UI as plain React nodes, never as raw HTML


# --- models -------------------------------------------------------------------------------------


class MetricItem(BaseModel):
    key: str  # dotted path in the stored metrics, e.g. "cash_out.mae_skill"
    value: float


class ModelVersionItem(BaseModel):
    id: int
    model_name: str
    version: str
    trained_at: datetime
    is_active: bool
    artifact_sha256: str
    metrics: list[MetricItem]
    created_at: datetime


class ModelRegistry(BaseModel):
    items: list[ModelVersionItem]
    generated_at: datetime


# --- drift --------------------------------------------------------------------------------------

DriftStatus = Literal["stable", "watch", "drift", "no_data"]


class DriftBucket(BaseModel):
    horizon: str  # "1-6" | "7-24" | "25-72"
    mae: float | None  # live: cached forecast vs realised demand
    reference_mae: float | None  # holdout MAE from the model's manifest
    ratio: float | None
    status: DriftStatus


class DriftPoint(BaseModel):
    horizon_h: int
    mae: float


class DriftFloat(BaseModel):
    float_type: FloatType
    buckets: list[DriftBucket]
    by_horizon: list[DriftPoint]
    hours_compared: int
    status: DriftStatus
    # Calibration drift: share of realised hours inside the served q10-q90 band vs the
    # model's own held-out coverage (manifest). Advisory reading like the MAE ratio.
    coverage: float | None = None
    reference_coverage: float | None = None
    calibration_status: DriftStatus = "no_data"


class RetrainSuggestion(BaseModel):
    """Advisory only: nothing retrains by itself; an admin decides (Admin > Jobs)."""

    suggested: bool
    reasons: list[str]  # e.g. "cash.error_drift", "emoney.calibration_drift"


class DriftReport(BaseModel):
    model_version: str | None
    origin: datetime | None  # forecast origin (SIM_NOW)
    watch_ratio: float
    drift_ratio: float
    floats: list[DriftFloat]
    status: DriftStatus
    generated_at: datetime
    retrain: RetrainSuggestion | None = None


# --- LLM log ------------------------------------------------------------------------------------


class LlmLogItem(BaseModel):
    id: int
    created_at: datetime
    user_id: uuid.UUID | None
    user_email: str | None
    intent: LlmIntent
    provider: str
    model: str | None
    lang: Lang
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    generated_by: GeneratedBy
    guard_result: GuardResult
    cache_hit: bool
    error: str | None


class LlmLogPage(BaseModel):
    items: list[LlmLogItem]
    total: int
    page: int
    page_size: int


class LlmUsageDay(BaseModel):
    day: date
    calls: int
    live_calls: int
    cache_hits: int
    replay: int
    template: int
    guard_failures: int
    prompt_tokens: int
    completion_tokens: int


class LlmUsage(BaseModel):
    days: list[LlmUsageDay]
    calls_today: int  # live provider calls since 00:00 UTC (what the cap counts)
    daily_cap: int
    cap_used: float  # calls_today / daily_cap
    total_calls: int
    cache_hit_rate: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    guard_failures: int
    generated_at: datetime
