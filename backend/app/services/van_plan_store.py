"""Stores a solved van plan: routes with their legs, every stop with the numbers behind it, and the
objective with the separate-trips comparison and the fairness report.

Each stop keeps why it is where it is: ETA range, deadline, lateness, P(stockout before the late
ETA) and its flag, the fairness guard, the distributor's pin or the freeze window, or its drop
reason with insertion cost vs skip penalty.
"""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import VanPlan, VanRoute, VanStop
from app.rules.van_routing import fairness, robust
from app.rules.van_routing.cost import skip_penalty
from app.rules.van_routing.matrix import Matrix, Point
from app.rules.van_routing.models import Solution, Stop, VanConfig
from app.rules.van_routing.stability import Applied, Pin
from app.services.van_inputs import Candidate, Inputs


def group(c: Candidate) -> str:
    return f"{c.agent.urban_rural.value}/tier{c.agent.tier}"


def legs(seq: list[int], points: list[Point], m: Matrix) -> list[dict[str, Any]]:
    nodes = [0, *[i + 1 for i in seq], 0]
    return [{"from_key": points[a].key, "to_key": points[b].key, "km": round(m.km[a][b], 3),
             "minutes": round(m.minutes[a][b], 2),
             "source": "road_cache" if m.cached[a][b] else "estimate"}
            for a, b in zip(nodes, nodes[1:], strict=False)]


def at_risk(c: Candidate, inputs: Inputs, hi_h: float, limit: float
            ) -> tuple[float | None, bool | None]:
    """P(stockout before the late ETA) from the agent's stockout curve, and whether it is above
    the limit. (None, None) when the forecast has no curve for the agent."""
    if c.curve is None:
        return None, None
    p = robust.p_at(c.curve, inputs.lag_h + hi_h)
    return round(p, 4), p > limit


def objective(sol: Solution, base: Solution, stops: Sequence[Stop], cfg: VanConfig,
              not_routed: int, flagged: int) -> dict[str, Any]:
    o, b = sol.objective, base.objective
    breakdown = asdict(o) | {"van_bdt": o.van_bdt, "total_bdt": o.total_bdt}
    return {"breakdown": {k: round(v, 2) for k, v in breakdown.items()},
            "separate": {"km": round(base.km, 2), "trips": base.trips,
                         "van_bdt": round(b.van_bdt, 2), "total_bdt": round(b.total_bdt, 2)},
            "served": sum(len(r.visits) for r in sol.routes),
            "dropped": len(sol.drops) + not_routed, "trips": sol.trips, "km": round(sol.km, 2),
            "total_bdt": round(o.total_bdt, 2), "notes": list(sol.notes),
            "fairness": fairness.report(sol, stops, cfg),
            "fairness_short": list(sol.fairness_short), "fairness_forced": len(sol.forced),
            "choice": sol.choice, "flagged": flagged}


def flagged(sol: Solution, cands: Sequence[Candidate], inputs: Inputs, m: Matrix,
            cfg: VanConfig, limit: float) -> int:
    return sum(1 for r in sol.routes
               for v, (_, hi) in zip(r.visits, robust.eta_range(r, m, cfg), strict=True)
               if at_risk(cands[v.stop], inputs, hi, limit)[1])


def persist(session: Session, plan: VanPlan, sol: Solution, inputs: Inputs, applied: Applied,
            points: list[Point], m: Matrix, cfg: VanConfig, limit: float,
            pins: dict[int, Pin]) -> None:
    every = inputs.routable
    cands = [every[i] for i in applied.index]
    frozen = {every[i].agent.id for i in applied.frozen}
    forced = set(sol.forced)

    def base(c: Candidate, **extra: Any) -> dict[str, Any]:
        return {"plan_id": plan.id, "agent_id": c.agent.id,
                "recommendation_id": c.recommendation_id, "amount": round(c.amount_bdt, 2),
                "deadline": c.stockout_at, "source_quantile": c.source_quantile, **extra}

    def details(c: Candidate, **extra: Any) -> dict[str, Any]:
        pin = "frozen" if c.agent.id in frozen else (
            pins[c.agent.id].action if c.agent.id in pins else None)
        return {"group": group(c), "lost_per_h_bdt": round(c.lost_per_h_bdt, 2),
                "deadline_h": round(c.deadline_h, 3), "time_factor": c.time_factor,
                "deadline_rule": c.deadline_rule, "pin": pin, **extra}

    for r in sol.routes:
        row = VanRoute(plan_id=plan.id, vehicle_no=r.vehicle_no, km=round(r.km, 2),
                       minutes=round(r.minutes, 1), cash_load=round(r.cash_load_bdt, 2),
                       cost_bdt=round(r.cost_bdt, 2),
                       legs=legs([v.stop for v in r.visits], points, m))
        session.add(row)
        session.flush()
        for k, (v, (lo, hi)) in enumerate(zip(r.visits, robust.eta_range(r, m, cfg),
                                              strict=True), start=1):
            c = cands[v.stop]
            p, flag = at_risk(c, inputs, hi, limit)
            session.add(VanStop(
                **base(c), route_id=row.id, seq=k, eta_lo=inputs.now + timedelta(hours=lo),
                eta_hi=inputs.now + timedelta(hours=hi), penalty_bdt=round(v.late_penalty_bdt, 2),
                stockout_before_arrival_p=p, status="planned",
                details=details(c, arrival_h=round(v.arrival_h, 3), late_h=round(v.late_h, 3),
                                eta_lo_h=round(lo, 3), eta_hi_h=round(hi, 3),
                                stockout_flag=flag, fairness_forced=v.stop in forced)))
    for d in sol.drops:
        c = cands[d.stop]
        ins = None if d.insertion_cost_bdt is None else round(d.insertion_cost_bdt, 2)
        session.add(VanStop(**base(c), penalty_bdt=round(d.skip_penalty_bdt, 2),
                            status="dropped", reason=d.reason,
                            details=details(c, insertion_cost_bdt=ins)))
    for i in applied.excluded:
        c = every[i]
        lost = skip_penalty(Stop(c.agent.id, c.agent.lat, c.agent.lng, c.amount_bdt,
                                 c.deadline_h, c.lost_per_h_bdt), cfg)
        session.add(VanStop(**base(c), penalty_bdt=round(lost, 2), status="dropped",
                            reason="excluded", details=details(c)))
    for c in inputs.swapped:
        session.add(VanStop(**base(c), penalty_bdt=0, status="dropped", reason="swap_suggested",
                            details=details(c)))
