from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import GeneratedBy, Lang

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
DistanceSource = Literal["road_cache", "estimate"]
PlanStatus = Literal["pending", "approved", "rejected", "superseded"]
StopStatus = Literal["planned", "dropped", "delivered"]
DropReason = Literal["swap_suggested", "cost_gt_value", "capacity", "excluded"]
PinAction = Literal["lock", "include", "exclude"]
StopPin = Literal["lock", "include", "exclude", "frozen"]


class VehiclesIn(BaseModel):
    """Per-plan overrides of the VAN_* defaults (docs/SYNTHETIC_ASSUMPTIONS.md)."""

    model_config = ConfigDict(extra="forbid")
    count: int | None = Field(default=None, ge=1, le=10)
    capacity_bdt: float | None = Field(default=None, gt=0, le=10_000_000)
    cash_cap_bdt: float | None = Field(default=None, gt=0, le=10_000_000)


class VanPlanOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_limit_s: float | None = Field(default=None, gt=0, le=30)


class VanPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizon_h: int | None = Field(default=None, ge=1, le=72)
    vehicles: VehiclesIn = Field(default_factory=VehiclesIn)
    options: VanPlanOptions = Field(default_factory=VanPlanOptions)


class VanDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: Note


class VanPinIn(BaseModel):
    """Lock, include or exclude one stop; the plan is re-solved as a new pending plan."""

    model_config = ConfigDict(extra="forbid")
    note: Note | None = None


class VanDeliveredIn(BaseModel):
    delivered_amount_bdt: float = Field(ge=0, le=10_000_000)
    note: Note | None = None


class VanLeg(BaseModel):
    from_key: str
    to_key: str
    km: float
    minutes: float
    source: DistanceSource
    polyline: str | None  # encoded polyline (road_cache depot legs only)


class VanStopOut(BaseModel):
    id: int
    seq: int | None
    agent_id: int
    agent_code: str
    agent_name: str
    lat: float
    lng: float
    group: str
    amount_bdt: float
    source_quantile: str
    eta_lo: datetime | None
    eta_hi: datetime | None
    deadline: datetime | None
    late_h: float | None
    penalty_bdt: float
    lost_per_h_bdt: float
    stockout_before_arrival_p: float | None
    status: StopStatus
    reason: DropReason | None
    delivered_at: datetime | None
    delivered_amount_bdt: float | None
    # V3 (additive): P(stockout before the late ETA) above the plan's limit; null = no curve.
    stockout_risk_flag: bool | None = None
    pin: StopPin | None = None  # distributor pin, or frozen by the approved plan
    fairness_forced: bool = False  # served because its group was below the service bound
    deadline_rule: str | None = None  # p_limit (stockout curve) | recommendation


class VanRouteOut(BaseModel):
    id: int
    vehicle_no: int
    km: float
    minutes: float
    cash_load_bdt: float
    cost_bdt: float
    legs: list[VanLeg]
    stops: list[VanStopOut]


class VanObjective(BaseModel):
    van_fixed_bdt: float
    van_km_bdt: float
    van_time_bdt: float
    late_penalty_bdt: float
    skip_penalty_bdt: float
    van_bdt: float
    total_bdt: float


class VanComparison(BaseModel):
    """Policy A (one separate trip per agent) on the same inputs, for the savings panel."""

    km: float
    trips: int
    van_bdt: float
    total_bdt: float


class VanFairnessGroup(BaseModel):
    """Service rate and longest wait of one area group, against the plan's bounds."""

    group: str
    needed: int
    served: int
    service_rate: float
    max_wait_h: float
    min_service_rate: float
    max_wait_bound_h: float
    ok: bool


class VanDepot(BaseModel):
    code: str
    name: str
    lat: float
    lng: float


class VanPlanSummary(BaseModel):
    id: int
    distributor_id: int
    status: PlanStatus
    planned_at: datetime
    clock_origin: datetime
    horizon_h: int
    solver: str
    stopped_by: str
    solve_ms: int
    distance_source: DistanceSource
    model_version: str | None
    generated_at: datetime
    input_hash: str
    served: int
    dropped: int
    trips: int
    km: float
    total_bdt: float
    advisory: Literal[True] = True


class VanPlanOut(VanPlanSummary):
    reused: bool = False  # same inputs as a pending plan: that plan is returned, not re-solved
    params: dict[str, Any]
    objective: VanObjective
    separate_trips: VanComparison
    depot: VanDepot
    routes: list[VanRouteOut]
    unrouted: list[VanStopOut]  # dropped stops, each with its reason
    decided_by: str | None
    decided_at: datetime | None
    note: str | None
    # V3 (additive)
    fairness: list[VanFairnessGroup] = []
    fairness_short: list[str] = []  # groups no van could bring up to the service bound
    stockout_p_limit: float | None = None
    flagged: int = 0  # planned stops whose stockout risk before arrival is above the limit
    choice: str | None = None  # "k/n": seeded pick among n near-optimal stop orders


class VanPlanPage(BaseModel):
    items: list[VanPlanSummary]
    total: int
    page: int
    page_size: int


class VanNarrativeOut(BaseModel):
    plan_id: int
    lang: Lang
    text: str
    generated_by: GeneratedBy
    model_version: str | None
    generated_at: datetime
    distance_source: DistanceSource
    fallback_reason: str | None = None  # why the template was served (additive)
    no_api_key: bool = False


class VanStat(BaseModel):
    """Mean over seeds with a 95% t-interval (synthetic data)."""

    mean: float
    lo: float
    hi: float


class VanPolicyEval(BaseModel):
    name: str
    metrics: dict[str, VanStat]
    service_rate_by_area: dict[str, float]
    drop_reasons: dict[str, float]  # mean count per seed


class VanContrast(BaseModel):
    """Paired difference of total BDT cost per seed (first policy minus second)."""

    first: str
    second: str
    diff_total_bdt: VanStat
    seeds_first_lower: int
    seeds: int
    verdict: Literal["lower", "higher", "no_clear_difference"]


class VanSensitivityRow(BaseModel):
    factor: str
    value: float
    policies: dict[str, dict[str, float]]


class VanEvalOut(BaseModel):
    label: Literal["synthetic data"]
    model_version: str  # van rules version the evaluation ran
    generated_at: datetime
    distance_source: DistanceSource
    seeds: list[int]
    instances: int
    stops: int
    policies: list[VanPolicyEval]
    d_vs_c: VanContrast
    d_vs_a: VanContrast
    sensitivity: list[VanSensitivityRow]
    sensitivity_seed: int
    reference: dict[str, Any] | None = None  # seed of the database with the road cache
    notes: list[str] = []
