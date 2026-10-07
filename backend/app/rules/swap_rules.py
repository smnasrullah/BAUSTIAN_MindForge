"""Agent-to-agent swap matching: feasibility rules + scipy assignment (default) or split
matching (`match_flow`, SWAP_MATCHING=flow; S1 of the ML upgrade).

Receivers: amber/red agents with a top-up need in one float. Donors: agents that are not
receivers and hold surplus in that float above their own pessimistic need + buffer.
A pair is feasible when both share a distributor, sit within the radius (haversine) and the
amount min(need, donor surplus), rounded down to ROUND_BDT, reaches the minimum. Among
feasible pairs, linear_sum_assignment minimises total distance, so each agent is in at most
one swap. A swap that covers the receiver's whole need saves one van trip. Pinned receivers
(the demo cast) are assigned first, then everyone else over the remaining donors.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linear_sum_assignment, milp
from scipy.sparse import coo_array

from app.models.enums import FloatType
from app.rules.rebalance_rules import ROUND_BDT

EARTH_RADIUS_KM = 6371.0088
_INFEASIBLE = 1e9
FLOW_TIME_LIMIT_S = 10.0  # MILP stop; the best plan found so far is used (still rule-feasible)


@dataclass(frozen=True)
class SwapConfig:
    radius_km: float = 5.0
    min_amount_bdt: float = 5_000.0

    def __post_init__(self) -> None:
        if self.radius_km <= 0 or self.min_amount_bdt <= 0:
            raise ValueError("swap radius and minimum amount must be > 0")


@dataclass(frozen=True)
class Receiver:
    agent_id: int
    distributor_id: int
    lat: float
    lng: float
    float_type: FloatType
    need: float  # BDT the recommendation asks for


@dataclass(frozen=True)
class Donor:
    agent_id: int
    distributor_id: int
    lat: float
    lng: float
    surplus: dict[FloatType, float]


@dataclass(frozen=True)
class Match:
    donor: Donor
    receiver: Receiver
    amount: float
    distance_km: float
    van_trip_saved: bool
    score: float  # coverage x closeness, 0..1 (higher is better)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def swap_amount(donor: Donor, receiver: Receiver) -> float:
    give = min(receiver.need, donor.surplus.get(receiver.float_type, 0.0))
    return float(math.floor(give / ROUND_BDT) * ROUND_BDT)


def pair(donor: Donor, receiver: Receiver, cfg: SwapConfig) -> Match | None:
    """One feasible donor-receiver pair (same distributor, within radius, big enough) or None.
    Shared by swap matching and the help-request helper ranking."""
    if donor.agent_id == receiver.agent_id or donor.distributor_id != receiver.distributor_id:
        return None
    distance = haversine_km(donor.lat, donor.lng, receiver.lat, receiver.lng)
    amount = swap_amount(donor, receiver)
    if distance > cfg.radius_km or amount < cfg.min_amount_bdt:
        return None
    coverage = min(1.0, amount / receiver.need)
    return Match(donor=donor, receiver=receiver, amount=amount, distance_km=round(distance, 2),
                 van_trip_saved=amount >= receiver.need,
                 score=round(coverage * (1.0 - distance / cfg.radius_km), 4))


def _assign(donors: Sequence[Donor], receivers: Sequence[Receiver], cfg: SwapConfig
            ) -> list[Match]:
    if not donors or not receivers:
        return []
    pairs = [[pair(d, r, cfg) for r in receivers] for d in donors]
    cost = np.array([[_INFEASIBLE if p is None else p.distance_km for p in row] for row in pairs])
    rows, cols = linear_sum_assignment(cost)
    found = [pairs[i][j] for i, j in zip(rows.tolist(), cols.tolist(), strict=True)]
    return [m for m in found if m is not None]


def match(donors: Sequence[Donor], receivers: Sequence[Receiver], cfg: SwapConfig,
          first: frozenset[int] = frozenset()) -> list[Match]:
    """Distance-minimising one-to-one assignment over feasible pairs only.

    Receivers in `first` (the pinned demo cast) are assigned before the rest, so a closer
    stranger cannot take the one donor the demo story depends on. Same rules either way.
    """
    head = _assign(donors, [r for r in receivers if r.agent_id in first], cfg)
    used = {m.donor.agent_id for m in head}
    tail = _assign([d for d in donors if d.agent_id not in used],
                   [r for r in receivers if r.agent_id not in first], cfg)
    return sorted(head + tail, key=lambda m: (m.receiver.agent_id, m.donor.agent_id))


# --- S1: split matching (min-cost flow as a small MILP) ---------------------------------------


@dataclass(frozen=True)
class FlowConfig:
    """Split matching: one shortage may be covered by several donors.

    Fairness cap: a donor helps at most `max_receivers_per_donor` agents per round; a receiver
    takes at most `max_donors_per_receiver` hand-overs. Travel-time window: a donor is only
    paired when it can walk/ride the distance (`speed_kmh`) before the receiver's deadline.
    Objective (BDT): every covered BDT is worth 1; each hand-over costs `transfer_cost_bdt`
    plus `km_cost_bdt` per km, so coverage comes first and fewer, nearer hand-overs win ties."""

    max_receivers_per_donor: int = 2
    max_donors_per_receiver: int = 3
    speed_kmh: float = 15.0
    km_cost_bdt: float = 10.0
    transfer_cost_bdt: float = 200.0

    def __post_init__(self) -> None:
        if self.max_receivers_per_donor < 1 or self.max_donors_per_receiver < 1:
            raise ValueError("fairness caps must be >= 1")
        if self.speed_kmh <= 0 or self.km_cost_bdt < 0 or self.transfer_cost_bdt < 0:
            raise ValueError("speed > 0, costs >= 0")


def _flow_pairs(donors: Sequence[Donor], receivers: Sequence[Receiver], cfg: SwapConfig,
                fcfg: FlowConfig, hours_left: dict[int, float] | None
                ) -> list[tuple[int, int, float]]:
    """(donor index, receiver index, km) of every pair the rules allow."""
    out = []
    for i, d in enumerate(donors):
        for j, r in enumerate(receivers):
            if d.agent_id == r.agent_id or d.distributor_id != r.distributor_id:
                continue
            if d.surplus.get(r.float_type, 0.0) < cfg.min_amount_bdt:
                continue
            km = haversine_km(d.lat, d.lng, r.lat, r.lng)
            left = None if hours_left is None else hours_left.get(r.agent_id)
            if km > cfg.radius_km or (left is not None and km / fcfg.speed_kmh > left):
                continue
            out.append((i, j, km))
    return out


def match_flow(donors: Sequence[Donor], receivers: Sequence[Receiver], cfg: SwapConfig,
               fcfg: FlowConfig, hours_left: dict[int, float] | None = None,
               first: frozenset[int] = frozenset()) -> list[Match]:
    """Pinned receivers (`first`, the demo cast) are matched before everyone else, as in
    `match`; then the rest over the donors' remaining surplus."""
    head = _match_flow([d for d in donors], [r for r in receivers if r.agent_id in first], cfg,
                       fcfg, hours_left)
    if not head:
        return _match_flow(donors, receivers, cfg, fcfg, hours_left)
    used: dict[int, float] = {}
    count: dict[int, int] = {}
    for m in head:
        used[m.donor.agent_id] = used.get(m.donor.agent_id, 0.0) + m.amount
        count[m.donor.agent_id] = count.get(m.donor.agent_id, 0) + 1
    rest = [Donor(d.agent_id, d.distributor_id, d.lat, d.lng,
                  {ft: v - used.get(d.agent_id, 0.0) for ft, v in d.surplus.items()})
            for d in donors if count.get(d.agent_id, 0) < fcfg.max_receivers_per_donor]
    tail = _match_flow(rest, [r for r in receivers if r.agent_id not in first], cfg, fcfg,
                       hours_left)
    return sorted(head + tail, key=lambda m: (m.receiver.agent_id, m.donor.agent_id))


def _match_flow(donors: Sequence[Donor], receivers: Sequence[Receiver], cfg: SwapConfig,
                fcfg: FlowConfig, hours_left: dict[int, float] | None = None) -> list[Match]:
    """Split matching over rule-feasible pairs; one Match per hand-over (amount in ROUND_BDT
    steps, each >= the minimum swap). `van_trip_saved` = the receiver's hand-overs together
    cover its whole need. Solved exactly with scipy's MILP (HiGHS); deterministic."""
    pairs = _flow_pairs(donors, receivers, cfg, fcfg, hours_left)
    if not pairs:
        return []
    n = len(pairs)
    unit = ROUND_BDT
    cap = [math.floor(donors[i].surplus.get(receivers[j].float_type, 0.0) / unit)
           for i, j, _ in pairs]
    need = [math.floor(receivers[j].need / unit) for _, j, _ in pairs]
    upper = np.array([max(0, min(c, m)) for c, m in zip(cap, need, strict=True)], dtype=float)
    low = math.ceil(cfg.min_amount_bdt / unit)
    # variables: x (units, integer) then y (hand-over on/off, binary)
    c = np.concatenate([-unit * np.ones(n),
                        [fcfg.transfer_cost_bdt + fcfg.km_cost_bdt * km for _, _, km in pairs]])
    ri: list[int] = []
    ci: list[int] = []
    val: list[float] = []
    lo: list[float] = []
    hi: list[float] = []

    def add(cols: list[int], coefs: list[float], a: float, b: float) -> None:
        r = len(lo)
        ri.extend([r] * len(cols))
        ci.extend(cols)
        val.extend(coefs)
        lo.append(a)
        hi.append(b)

    for p in range(n):  # link: low * y <= x <= upper * y
        add([p, n + p], [1.0, -float(upper[p])], -np.inf, 0.0)
        add([p, n + p], [1.0, -float(low)], 0.0, np.inf)
    by_donor: dict[int, list[int]] = {}
    by_recv: dict[int, list[int]] = {}
    for p, (i, j, _) in enumerate(pairs):
        by_donor.setdefault(i, []).append(p)
        by_recv.setdefault(j, []).append(p)
    for i, ps in by_donor.items():
        per_ft: dict[FloatType, list[int]] = {}
        for p in ps:
            per_ft.setdefault(receivers[pairs[p][1]].float_type, []).append(p)
        for ft, qs in per_ft.items():
            add(qs, [1.0] * len(qs), 0.0, math.floor(donors[i].surplus.get(ft, 0.0) / unit))
        add([n + p for p in ps], [1.0] * len(ps), 0.0, fcfg.max_receivers_per_donor)
    for j, ps in by_recv.items():
        add(ps, [1.0] * len(ps), 0.0, math.floor(receivers[j].need / unit))
        add([n + p for p in ps], [1.0] * len(ps), 0.0, fcfg.max_donors_per_receiver)
    a_mat = coo_array((val, (ri, ci)), shape=(len(lo), 2 * n)).tocsr()
    a_mat.indices = a_mat.indices.astype(np.int32)  # HiGHS takes 32-bit sparse indices
    a_mat.indptr = a_mat.indptr.astype(np.int32)
    res = milp(c, constraints=LinearConstraint(a_mat, lo, hi), integrality=np.ones(2 * n),
               bounds=Bounds(np.zeros(2 * n), np.concatenate([upper, np.ones(n)])),
               options={"time_limit": FLOW_TIME_LIMIT_S})
    if res.x is None:
        return []
    x = np.round(res.x[:n]).astype(int)
    got: dict[int, float] = {}
    for p, (_, j, _) in enumerate(pairs):
        got[j] = got.get(j, 0.0) + x[p] * unit
    out = []
    for p, (i, j, km) in enumerate(pairs):
        if x[p] <= 0:
            continue
        d, r = donors[i], receivers[j]
        amount = float(x[p] * unit)
        out.append(Match(donor=d, receiver=r, amount=amount, distance_km=round(km, 2),
                         van_trip_saved=got[j] >= r.need,
                         score=round(min(1.0, amount / r.need) * (1.0 - km / cfg.radius_km), 4)))
    return sorted(out, key=lambda m: (m.receiver.agent_id, m.donor.agent_id))
