from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.models.enums import AnomalyStatus

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
# Raw window measures (ml/features/anomaly.py RAW); `deviation` is the model's peer z input.
# Burst measures (peak / burst days / rate change vs the same weekday) are used by newer models.
Feature = Literal["cash_out_growth", "hour_shift", "refills_per_day", "out_in_log_ratio",
                  "burst_peak_ratio", "burst_days", "rate_change"]


class AnomalyAgent(BaseModel):
    agent_id: int
    code: str
    name: str
    district: str
    upazila: str | None


class AnomalyReason(BaseModel):
    feature: Feature
    value: float
    peer_median: float
    deviation: float  # robust z vs the peer group (median / MAD); one-sided measures >= 0
    direction: Literal["high", "low"]


class AnomalyItem(BaseModel):
    id: int
    agent: AnomalyAgent
    window_start: datetime
    window_end: datetime
    score: float  # Isolation Forest score 0..1, higher = more unusual
    threshold: float  # the peer group's flag cut-off
    peer_group: str  # "t{tier}-{urban_rural}" or "all"
    reasons: list[AnomalyReason]
    status: AnomalyStatus
    reviewed_at: datetime | None
    note: str | None
    model_version: str
    generated_at: datetime


class AnomalyPage(BaseModel):
    items: list[AnomalyItem]
    total: int
    page: int
    page_size: int
    advisory: Literal[True] = True  # a lead for human review, not an accusation


class PeerFeature(BaseModel):
    """One feature of the flagged window against the same window of its peer group."""

    name: Feature
    value: float
    deviation: float
    percentile: float  # agent's rank among peers, 0..100
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float


class PeerScores(BaseModel):
    p50: float
    p90: float
    max: float


class AnomalyContext(BaseModel):
    cash_out_bdt: float
    cash_in_bdt: float
    baseline_cash_out_bdt: float  # own prior 28 days, scaled to the window length
    refills: int


class AnomalyDetail(AnomalyItem):
    peer_count: int
    window_h: int
    history_h: int
    features: list[PeerFeature]
    peer_scores: PeerScores
    context: AnomalyContext
    reviewed_by: str | None  # reviewer's full name
    advisory: Literal[True] = True


class AnomalyReviewIn(BaseModel):
    decision: Literal["confirmed", "dismissed"]
    note: Note
