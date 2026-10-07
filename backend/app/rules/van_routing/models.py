"""Inputs and outputs of the van route optimizer (pure data, no I/O).

Time is in hours from the van's departure (the plan's wall-clock now). Money is BDT.
Every default is a synthetic assumption (docs/SYNTHETIC_ASSUMPTIONS.md) and a VAN_* setting.
"""

from dataclasses import dataclass, field
from typing import Literal

# deadline_missed: hard-deadline mode only (evaluation policy C), never in a served plan.
# excluded: the distributor took the stop out of the plan (stability.py).
DropReason = Literal["swap_suggested", "cost_gt_value", "capacity", "deadline_missed",
                     "excluded"]
SolverName = Literal["ortools", "fallback", "separate_trips", "nearest_neighbour"]
DistanceSource = Literal["road_cache", "estimate"]
WindowMode = Literal["soft", "hard"]


@dataclass(frozen=True)
class VanConfig:
    vehicles: int = 2
    capacity_bdt: float = 1_500_000.0  # cash a van can carry
    cash_cap_bdt: float = 1_500_000.0  # safety cap per van; the load limit is the smaller one
    shift_h: float = 8.0  # depot to depot
    cost_per_km_bdt: float = 25.0
    cost_per_hour_bdt: float = 200.0  # driver + guard time
    fixed_trip_bdt: float = 1_500.0  # per van that leaves the depot
    minutes_per_stop: float = 10.0
    speed_kmh: float = 25.0  # estimate path only (road_cache legs carry their own minutes)
    road_factor: float = 1.35  # haversine -> road km when a pair is not in the road cache
    horizon_h: float = 24.0  # a skipped agent is counted as stocked out until here
    time_limit_s: float = 10.0
    solution_limit: int = 300  # fixed search budget: same input -> same plan on any machine
    # Fairness guard (fairness.py), per area group: no arrival later than max_wait_h after
    # departure, and at least min_service_rate of each group's agents served when a van can.
    max_wait_h: float = 8.0
    min_service_rate: float = 0.5
    # Safety (safety.py): a seeded pick among stop orders within this share of the best cost.
    near_optimal_pct: float = 0.03
    # Robustness (robust.py): driving time may run this much faster / slower than planned.
    eta_lo_factor: float = 0.85
    eta_hi_factor: float = 1.3

    def __post_init__(self) -> None:
        if self.vehicles < 1:
            raise ValueError("van count must be >= 1")
        if min(self.capacity_bdt, self.cash_cap_bdt, self.shift_h, self.speed_kmh,
               self.horizon_h, self.time_limit_s) <= 0:
            raise ValueError("van capacity, cash cap, shift, speed, horizon and limit must be > 0")
        if min(self.cost_per_km_bdt, self.cost_per_hour_bdt, self.fixed_trip_bdt,
               self.minutes_per_stop) < 0:
            raise ValueError("van costs and stop minutes must be >= 0")
        if self.road_factor < 1 or self.solution_limit < 1:
            raise ValueError("road factor must be >= 1 and solution limit >= 1")
        if self.max_wait_h <= 0 or not 0 <= self.min_service_rate <= 1:
            raise ValueError("max wait must be > 0 and min service rate in [0, 1]")
        if not 0 <= self.near_optimal_pct <= 0.2:
            raise ValueError("near-optimal share must be in [0, 0.2]")
        if not 0 < self.eta_lo_factor <= 1 <= self.eta_hi_factor:
            raise ValueError("ETA factors must satisfy 0 < lo <= 1 <= hi")

    @property
    def load_cap_bdt(self) -> float:
        return min(self.capacity_bdt, self.cash_cap_bdt)


@dataclass(frozen=True)
class Stop:
    agent_id: int
    lat: float
    lng: float
    amount_bdt: float
    deadline_h: float  # expected stockout, hours after departure (may be <= 0: already late)
    lost_per_h_bdt: float  # turned-away cash-out per stockout hour (impact model unit)
    district: str = ""
    group: str = ""  # e.g. "urban/tier2"; the fairness guard works on the area ("urban")
    must_serve: bool = False  # locked, included or frozen (stability.py)
    vehicle: int | None = None  # locked / frozen to this van number (1-based)


@dataclass(frozen=True)
class Visit:
    stop: int  # index into the stop list
    arrival_h: float
    late_h: float
    late_penalty_bdt: float


@dataclass(frozen=True)
class Route:
    vehicle_no: int
    visits: tuple[Visit, ...]
    km: float
    minutes: float
    cash_load_bdt: float
    cost_bdt: float  # van cost only (fixed + km + time); penalties are per visit


@dataclass(frozen=True)
class Drop:
    stop: int
    reason: DropReason
    skip_penalty_bdt: float
    insertion_cost_bdt: float | None  # cheapest feasible insertion; None = none fits


@dataclass(frozen=True)
class Objective:
    van_fixed_bdt: float
    van_km_bdt: float
    van_time_bdt: float
    late_penalty_bdt: float
    skip_penalty_bdt: float

    @property
    def van_bdt(self) -> float:
        return self.van_fixed_bdt + self.van_km_bdt + self.van_time_bdt

    @property
    def total_bdt(self) -> float:
        return self.van_bdt + self.late_penalty_bdt + self.skip_penalty_bdt


@dataclass(frozen=True)
class Solution:
    routes: tuple[Route, ...]
    drops: tuple[Drop, ...]
    objective: Objective
    solver: SolverName
    stopped_by: str  # solution_limit | time_limit | heuristic | empty
    solve_ms: float
    notes: tuple[str, ...] = field(default=())
    forced: tuple[int, ...] = field(default=())  # served only because of the fairness guard
    fairness_short: tuple[str, ...] = field(default=())  # groups no van could bring up to bound
    choice: str = "best"  # "k/n": seeded pick k of n near-optimal orders (safety.py)

    @property
    def km(self) -> float:
        return sum(r.km for r in self.routes)

    @property
    def trips(self) -> int:
        return len(self.routes)
