"""Impact replay realism sensitivity (S4): imperfect delivery and the full action costs.

The stored impact backtest assumes every delivery lands on time and counts only van trips. Here
both policies are replayed again with, for every PHYSICAL delivery (van, urgent, self-fetch,
swap hand-over): P(fail) -> it arrives empty (the policy still believed it was coming), else
P(delay) -> it lands DELAY_H hours late. Digital top-ups are left as they are. Draws are seeded
per (seed, hour, agent, channel), so both policies meet the same luck. ASSUMED numbers.

Costs (BDT, synthetic assumptions from the channel rules): van trip VAN, urgent manual URGENT
(instead of a van trip), top-up fee TOPUP_PCT of the amount, self-fetch 2 x hub km x KM, swap
hand-over km x KM.
"""

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from app.models.enums import RecommendationChannel as Channel
from app.rules.swap_rules import haversine_km
from app.services.impact_sim import Delivery, Outcome, Policy, World

PHYSICAL = frozenset({Channel.van, Channel.urgent_manual, Channel.self_fetch, Channel.swap})


@dataclass(frozen=True)
class Realism:
    p_fail: float = 0.10
    p_delay: float = 0.25
    delay_h: int = 2
    seed: int = 42


@dataclass(frozen=True)
class Costs:
    van_trip_bdt: float = 1_500.0
    urgent_bdt: float = 2_500.0
    topup_pct: float = 0.5
    km_bdt: float = 10.0


class Unreliable:
    """Wraps a policy: its physical deliveries may fail or come late."""

    def __init__(self, inner: Policy, r: Realism) -> None:
        self.inner, self.r = inner, r

    def decide(self, t: int, cash: np.ndarray, em: np.ndarray, pending: np.ndarray
               ) -> list[Delivery]:
        out = []
        for d in self.inner.decide(t, cash, em, pending):
            if d.channel in PHYSICAL:
                u = np.random.default_rng([self.r.seed, t, d.row, list(Channel).index(d.channel)]
                                          ).random()
                if u < self.r.p_fail:
                    d = replace(d, failed=True)
                elif u < self.r.p_fail + self.r.p_delay:
                    d = replace(d, arrive=d.arrive + self.r.delay_h)
            out.append(d)
        return out


def action_cost(w: World, o: Outcome, c: Costs) -> dict[str, float]:
    trips = {d.trip for d in o.deliveries if d.trip and d.channel != Channel.urgent_manual}
    urgent = sum(d.channel == Channel.urgent_manual for d in o.deliveries)
    topup = sum(d.amount for d in o.deliveries if d.channel == Channel.top_up)
    fetch_km = sum(2 * (w.sites[d.row].hub_km or 0.0) for d in o.deliveries
                   if d.channel == Channel.self_fetch)
    swap_km = sum(haversine_km(w.sites[d.row].lat, w.sites[d.row].lng, w.sites[d.donor].lat,
                               w.sites[d.donor].lng)
                  for d in o.deliveries if d.channel == Channel.swap and d.donor is not None)
    parts = {"van_bdt": len(trips) * c.van_trip_bdt, "urgent_bdt": urgent * c.urgent_bdt,
             "topup_fee_bdt": topup * c.topup_pct / 100, "travel_bdt": (fetch_km + swap_km)
             * c.km_bdt}
    return {k: round(v, 2) for k, v in parts.items()} | {"total_bdt": round(sum(parts.values()),
                                                                             2)}


def summary(w: World, o: Outcome, stockout_min: float) -> dict[str, Any]:
    hit = (o.unmet_out > stockout_min) | (o.unmet_in > stockout_min)
    return {"stockout_hours": int(hit.sum()),
            "value_lost_bdt": round(float(o.unmet_out.sum() + o.unmet_in.sum()), 2),
            "deliveries": len(o.deliveries),
            "failed": sum(d.failed for d in o.deliveries)}
