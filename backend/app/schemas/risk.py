from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.enums import FloatType, RiskLevelCode, UrbanRural
from app.schemas.agent import AgentProfile

RiskSort = Literal["risk", "stockout", "code", "name"]


class PredictionMeta(BaseModel):
    agent_id: int
    as_of: datetime  # simulated "now" the projection starts at
    model_version: str
    generated_at: datetime


class RefillAwareStockout(BaseModel):
    """Extra reading, never the decision input: the same projection when the agent keeps its
    usual refills (chance and level by weekday and hour, from its own history)."""

    stockout_at: datetime | None
    hours_to_stockout: float | None
    probability_24h: float  # P(stockout within 24 h) with the usual refills


class FloatStockout(BaseModel):
    float_type: FloatType
    balance: float  # BDT at as_of
    capacity: float
    # Median first-passage time if a stockout within 72 h is more likely than not; else null.
    stockout_at: datetime | None
    hours_to_stockout: float | None
    # stockout_at set: P(stockout within the window around it); null: P(no stockout within 72 h).
    confidence: float
    # Additional view (no refill above is what risk levels and recommendations use); null when
    # the stockout method has no refill view.
    refill_aware: RefillAwareStockout | None = None


class HorizonRisk(BaseModel):
    horizon_h: int
    probability: float  # P(stockout within horizon_h)
    level: RiskLevelCode
    confidence: float  # max(p, 1 - p)


class FloatRisk(BaseModel):
    float_type: FloatType
    level: RiskLevelCode  # at the headline horizon (24 h)
    horizons: list[HorizonRisk]


class AgentHorizonLevel(BaseModel):
    horizon_h: int
    level: RiskLevelCode  # worst float
    probability: float  # highest float probability


class AgentStockout(PredictionMeta):
    unit: Literal["BDT"] = "BDT"
    floats: list[FloatStockout]


class AgentRisk(PredictionMeta):
    level: RiskLevelCode  # worst float at the headline horizon (24 h)
    by_horizon: list[AgentHorizonLevel]
    floats: list[FloatRisk]


class FloatSummary(FloatStockout):
    level: RiskLevelCode  # at the headline horizon (24 h)
    horizons: list[HorizonRisk]


class AgentSummary(PredictionMeta):
    agent: AgentProfile
    unit: Literal["BDT"] = "BDT"
    level: RiskLevelCode  # worst float at the headline horizon (24 h)
    by_horizon: list[AgentHorizonLevel]
    floats: list[FloatSummary]


class AgentRiskRow(BaseModel):
    agent_id: int
    code: str
    name: str
    district: str
    upazila: str | None
    urban_rural: UrbanRural
    tier: int
    lat: float
    lng: float
    level: RiskLevelCode  # at the requested horizon, worst float
    probability: float
    worst_float: FloatType
    stockout_at: datetime | None  # soonest over floats
    hours_to_stockout: float | None


class AgentRiskPage(BaseModel):
    items: list[AgentRiskRow]
    total: int
    page: int
    page_size: int
    horizon_h: int
    as_of: datetime | None
    model_version: str
    generated_at: datetime | None
