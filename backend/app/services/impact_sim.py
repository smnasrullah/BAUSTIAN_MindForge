"""Counterfactual replay of the holdout (F11): true demand served hour by hour under one policy.

Same world for every policy: opening balances, the agents' own scheduled refills and the full
customer demand (incl. what was turned away in the logged history). Each hour: scheduled refill
-> deliveries that land -> the policy orders -> customers are served (simulator rules) -> balances
move. A policy only differs in what it orders, when, and how it travels.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import numpy as np

from app.models.enums import FloatType
from app.models.enums import RecommendationChannel as Channel
from ml.data_gen.simulate import serve

FLOATS = (FloatType.cash, FloatType.emoney)  # column order of `pending`


@dataclass(frozen=True)
class Site:
    agent_id: int
    distributor_id: int
    lat: float
    lng: float
    hub_km: float | None  # agent to its distributor point


@dataclass
class World:
    sites: list[Site]
    start: datetime  # UTC time of world hour 0
    hod: np.ndarray  # (T,) local hour of day
    cash_cap: np.ndarray  # (A,)
    em_cap: np.ndarray  # (A,)
    demand_in: np.ndarray  # (A, T) true cash-in demand, BDT
    demand_out: np.ndarray  # (A, T) true cash-out demand, BDT
    scheduled: np.ndarray  # (A, T) bool: the agent's own routine refill
    cash_target: np.ndarray  # (A, T) cash level a refill restores
    em_target: np.ndarray  # (A,)
    cash0: np.ndarray  # (A,) balances at world hour 0, before its refill
    em0: np.ndarray

    @property
    def n_hours(self) -> int:
        return int(self.demand_in.shape[1])

    def capacity(self, ft: FloatType) -> np.ndarray:
        return self.cash_cap if ft == FloatType.cash else self.em_cap


@dataclass(frozen=True)
class Delivery:
    ordered: int  # world hour
    arrive: int
    row: int  # receiving agent (index into World.sites)
    float_type: FloatType
    amount: float
    channel: Channel
    trip: str | None = None  # van trip key; deliveries sharing one count one trip
    donor: int | None = None  # swap partner row
    failed: bool = False  # realism sensitivity: arrives empty (the policy still counted it)


@dataclass
class Outcome:
    unmet_in: np.ndarray  # (A, T) BDT turned away
    unmet_out: np.ndarray
    deliveries: list[Delivery] = field(default_factory=list)


class Policy(Protocol):
    def decide(self, t: int, cash: np.ndarray, em: np.ndarray, pending: np.ndarray
               ) -> list[Delivery]: ...


def _land(d: Delivery, cash: np.ndarray, em: np.ndarray, w: World) -> None:
    r = d.row
    if d.failed:
        return
    if d.donor is not None:  # cash for e-money between two agents, as much as both can cover
        give = min(d.amount, cash[d.donor], em[r])
        cash[d.donor] -= give
        em[d.donor] += give
        cash[r] += give
        em[r] -= give
    elif d.float_type == FloatType.cash:
        cash[r] = min(w.cash_cap[r], cash[r] + d.amount)
    else:
        em[r] = min(w.em_cap[r], em[r] + d.amount)


def run(w: World, policy: Policy) -> Outcome:
    n, hours = w.demand_in.shape
    cash, em = w.cash0.astype(float), w.em0.astype(float)
    pending = np.zeros((n, len(FLOATS)))
    inbox: dict[int, list[Delivery]] = {}
    out = Outcome(np.zeros((n, hours)), np.zeros((n, hours)))
    for t in range(hours):
        sched = w.scheduled[:, t]
        cash = np.where(sched, w.cash_target[:, t], cash)
        em = np.where(sched, w.em_target, em)
        for d in inbox.pop(t, []):
            pending[d.row, FLOATS.index(d.float_type)] -= d.amount
            _land(d, cash, em, w)
        for d in policy.decide(t, cash, em, pending):
            out.deliveries.append(d)
            pending[d.row, FLOATS.index(d.float_type)] += d.amount
            inbox.setdefault(d.arrive, []).append(d)
        d_in, d_out = w.demand_in[:, t], w.demand_out[:, t]
        s_in, s_out = serve(cash, em, d_in, d_out)
        out.unmet_in[:, t], out.unmet_out[:, t] = d_in - s_in, d_out - s_out
        cash, em = cash + s_in - s_out, em - s_in + s_out
    return out
