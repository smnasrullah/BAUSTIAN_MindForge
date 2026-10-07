"""Van plan inputs from the existing caches: cash recommendations (rebalance), forecasts, swaps,
events and weather. ML supplies the numbers here; app/rules/van_routing decides.

Times: recommendations live on the forecast timeline (origin = data_now); the vans leave at wall
now. clock.forecast_to_wall keeps each stockout's distance from the origin.

Forecast-aware (V3): a red agent gets the rebalance amount (pessimistic q90 drain vs q10 inflow);
an amber agent gets the same rule on the median path (q50 vs q50), or the q90 amount when the
median path needs nothing. The deadline is the hour the agent's P(stockout) curve reaches
VAN_STOCKOUT_P_LIMIT, else the recommendation's stockout time.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.models import (
    Agent,
    Distributor,
    Event,
    Forecast,
    Recommendation,
    StockoutPrediction,
    SwapSuggestion,
    WeatherDaily,
)
from app.models.enums import EventType, FloatType, RecommendationChannel, SwapStatus
from app.rules.rebalance_rules import advise, assess
from app.rules.van_routing.robust import p_crossing
from app.services import risk
from app.services.forecast import _utc
from app.services.model_registry import active_model
from app.services.rebalance import configs
from app.services.recommendation_read import LIVE
from ml.data_gen.timeline import BDT
from ml.registry import FORECAST_MODEL

Q90, Q50 = "q90", "q50"  # red: pessimistic drain (q90) vs inflow (q10); amber: median path
COVERED = (SwapStatus.pending, SwapStatus.approved)


class VanInputError(Exception):
    """not_ready: no active forecast model yet (503)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Candidate:
    agent: Agent
    recommendation_id: int
    amount_bdt: float
    stockout_at: datetime  # wall clock
    deadline_h: float  # hours after departure
    lost_per_h_bdt: float
    time_factor: float
    source_quantile: str = Q90
    deadline_rule: str = "recommendation"  # or "p_limit" (stockout curve)
    curve: tuple[float, ...] | None = None  # P(stockout by forecast hour h), h = 0..72


@dataclass(frozen=True)
class Inputs:
    origin: datetime
    now: datetime
    model_version: str
    routable: list[Candidate]
    swapped: list[Candidate]  # covered by a pending/approved swap: listed, not routed
    lag_h: float = 0.0  # forecast hours already behind the wall clock (live mode)

    def fingerprint(self) -> list[Any]:
        return [[c.agent.id, c.recommendation_id, c.amount_bdt, round(c.deadline_h, 2),
                 round(c.lost_per_h_bdt, 2), c.time_factor, c in self.swapped,
                 c.source_quantile, c.deadline_rule]
                for c in sorted(self.routable + self.swapped, key=lambda c: c.agent.id)]


def _lost_per_h(session: Session, mv_id: int, ids: list[int], horizon_h: int
                ) -> dict[int, float]:
    """Mean forecast cash-out per hour (q50): what a stocked-out agent turns away each hour,
    the same unit as the impact model's value_lost_bdt."""
    rows = session.execute(
        select(Forecast.agent_id, func.avg(Forecast.q_mid))
        .where(Forecast.model_version_id == mv_id, Forecast.float_type == FloatType.cash,
               Forecast.horizon_h <= horizon_h, Forecast.agent_id.in_(ids))
        .group_by(Forecast.agent_id)).tuples().all()
    return {a: float(v or 0) for a, v in rows}


def _curves(session: Session, mv_id: int, ids: list[int]) -> dict[int, tuple[float, ...]]:
    rows = session.execute(
        select(StockoutPrediction.agent_id, StockoutPrediction.prob_by_hour)
        .where(StockoutPrediction.model_version_id == mv_id,
               StockoutPrediction.float_type == FloatType.cash,
               StockoutPrediction.agent_id.in_(ids))).tuples().all()
    return {a: tuple(float(x) for x in c) for a, c in rows if c}


def _median_amounts(session: Session, mv_id: int, agents: list[Agent], origin: datetime,
                    s: Settings) -> dict[int, float]:
    """Amber agents: the rebalance rule on the median path (q50 drain vs q50 inflow)."""
    if not agents:
        return {}
    rcfg = configs(s)[0]
    q = risk.load_quantiles(session, mv_id, rcfg.horizon_h)
    balances = risk.load_balances(session, origin)
    out: dict[int, float] = {}
    for a in agents:
        drain = q.get((a.id, FloatType.cash))
        inflow = q.get((a.id, risk.INFLOW_OF[FloatType.cash]))
        if drain is None or inflow is None or a.id not in balances:
            continue
        need = assess(balances[a.id][FloatType.cash], float(a.cash_capacity), drain[:, 1],
                      inflow[:, 1], rcfg)
        advice = advise(need, origin, None, rcfg)
        if advice is not None and advice.amount > 0:
            out[a.id] = advice.amount
    return out


def day_factors(session: Session, origin: datetime, districts: set[str],
                s: Settings) -> dict[str, float]:
    """Travel-time multiplier per district at the origin: the slowest of Eid, hat-bazar and
    rain/severe weather (not compounded)."""
    by_type = {EventType.eid: s.van_eid_time_factor, EventType.hat_bazar:
               s.van_hat_bazar_time_factor, EventType.weather: s.van_rain_time_factor}
    events = session.execute(select(Event.type, Event.district).where(
        Event.type.in_(list(by_type)), Event.starts_at <= origin,
        Event.ends_at > origin)).tuples().all()
    wet = set(session.scalars(select(WeatherDaily.district).where(
        WeatherDaily.date == origin.astimezone(BDT).date(), WeatherDaily.district.in_(districts),
        (WeatherDaily.severe.is_(True)) | (WeatherDaily.rain_mm >= s.van_rain_mm))))
    out: dict[str, float] = {}
    for d in districts:
        f = max([1.0] + [by_type[t] for t, where in events if where in (None, d)])
        out[d] = max(f, s.van_rain_time_factor) if d in wet else f
    return out


def gather(session: Session, distributor: Distributor, horizon_h: int, s: Settings,
           now: datetime) -> Inputs:
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        raise VanInputError("not_ready")
    origin = clock.data_now(session)
    lag = clock.lag_h(origin, now)
    rows = session.execute(
        select(Recommendation, Agent).join(Agent, Agent.id == Recommendation.agent_id)
        .where(Agent.distributor_id == distributor.id, Recommendation.model_version_id == mv.id,
               Recommendation.float_type == FloatType.cash, Recommendation.status.in_(LIVE))
        .order_by(Agent.id, Recommendation.deadline_at, Recommendation.id)).tuples().all()
    covered = set(session.scalars(select(SwapSuggestion.receiver_agent_id).where(
        SwapSuggestion.status.in_(COVERED), SwapSuggestion.float_type == FloatType.cash,
        SwapSuggestion.model_version_id == mv.id)))
    ids = sorted({a.id for _, a in rows})
    lost = _lost_per_h(session, mv.id, ids, horizon_h)
    factors = day_factors(session, origin, {a.district for _, a in rows}, s)
    curves = _curves(session, mv.id, ids)
    amber = {a.id: a for rec, a in rows if rec.rationale.get("risk_level") == "amber"}
    median = _median_amounts(session, mv.id, list(amber.values()), origin, s)
    seen: set[int] = set()
    routable: list[Candidate] = []
    swapped: list[Candidate] = []
    for rec, agent in rows:
        if agent.id in seen:
            continue
        seen.add(agent.id)
        curve = curves.get(agent.id)
        cross = None if curve is None else p_crossing(curve, s.van_stockout_p_limit)
        if cross is not None:
            stockout = origin + timedelta(hours=cross)
        else:
            raw = rec.rationale.get("stockout_at")
            stockout = _utc(datetime.fromisoformat(raw)) if raw else _utc(rec.deadline_at)
        deadline_h = (stockout - origin).total_seconds() / 3600 - lag
        if deadline_h > horizon_h:
            continue
        q50 = median.get(agent.id)
        c = Candidate(agent=agent, recommendation_id=rec.id,
                      amount_bdt=float(rec.amount_bdt) if q50 is None else q50,
                      stockout_at=clock.forecast_to_wall(stockout, origin, now),
                      deadline_h=deadline_h, lost_per_h_bdt=lost.get(agent.id, 0.0),
                      time_factor=factors.get(agent.district, 1.0),
                      source_quantile=Q90 if q50 is None else Q50,
                      deadline_rule="recommendation" if cross is None else "p_limit",
                      curve=curve)
        is_swap = rec.channel == RecommendationChannel.swap or agent.id in covered
        (swapped if is_swap else routable).append(c)
    return Inputs(origin=origin, now=now, model_version=mv.version, routable=routable,
                  swapped=swapped, lag_h=lag)
