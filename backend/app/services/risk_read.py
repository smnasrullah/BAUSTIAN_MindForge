"""Read the stockout + risk cache: per-agent views and the scoped, paginated risk list."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, defer

from app.core.deps import scoped_agents_query
from app.models import Agent, FloatSnapshot, ModelVersion, RiskLevel, StockoutPrediction, User
from app.models.enums import FloatType, RiskLevelCode
from app.rules.risk_rules import HEADLINE_HORIZON, SEVERITY, worst
from app.schemas.agent import AgentProfile
from app.schemas.risk import (
    AgentHorizonLevel,
    AgentRisk,
    AgentRiskPage,
    AgentRiskRow,
    AgentStockout,
    AgentSummary,
    FloatRisk,
    FloatStockout,
    FloatSummary,
    HorizonRisk,
    PredictionMeta,
    RefillAwareStockout,
    RiskSort,
)
from app.services.forecast import _utc
from app.services.model_registry import active_model
from ml.registry import FORECAST_MODEL

FLOATS = (FloatType.cash, FloatType.emoney)


@dataclass
class _Cached:
    stockouts: dict[FloatType, StockoutPrediction] = field(default_factory=dict)
    risks: dict[FloatType, list[RiskLevel]] = field(default_factory=dict)


def _load(session: Session, mv: ModelVersion, agent_ids: Sequence[int],
          horizon: int | None = None) -> dict[int, _Cached]:
    out: dict[int, _Cached] = {}
    # prob_by_hour (~1 KB JSON a row) is only for the map's time scrubber (services/risk_map).
    for s in session.scalars(select(StockoutPrediction).options(
            defer(StockoutPrediction.prob_by_hour, raiseload=True)).where(
            StockoutPrediction.model_version_id == mv.id,
            StockoutPrediction.agent_id.in_(agent_ids))):
        out.setdefault(s.agent_id, _Cached()).stockouts[s.float_type] = s
    query = select(RiskLevel).where(RiskLevel.model_version_id == mv.id,
                                    RiskLevel.agent_id.in_(agent_ids))
    if horizon is not None:
        query = query.where(RiskLevel.horizon_h == horizon)
    for r in session.scalars(query.order_by(RiskLevel.horizon_h)):
        out.setdefault(r.agent_id, _Cached()).risks.setdefault(r.float_type, []).append(r)
    return {a: c for a, c in out.items() if c.stockouts and c.risks}


def _horizon(r: RiskLevel) -> HorizonRisk:
    return HorizonRisk(horizon_h=r.horizon_h, probability=float(r.probability), level=r.level,
                       confidence=float(r.confidence))


def _headline(rows: list[RiskLevel]) -> RiskLevelCode:
    return worst(r.level for r in rows if r.horizon_h == HEADLINE_HORIZON)


def _float_risks(c: _Cached) -> list[FloatRisk]:
    return [FloatRisk(float_type=ft, level=_headline(c.risks[ft]),
                      horizons=[_horizon(r) for r in c.risks[ft]])
            for ft in FLOATS if ft in c.risks]


def _by_horizon(c: _Cached) -> list[AgentHorizonLevel]:
    rows: dict[int, list[RiskLevel]] = {}
    for found in c.risks.values():
        for r in found:
            rows.setdefault(r.horizon_h, []).append(r)
    return [AgentHorizonLevel(horizon_h=h, level=worst(r.level for r in rs),
                              probability=max(float(r.probability) for r in rs))
            for h, rs in sorted(rows.items())]


def _meta(agent_id: int, mv: ModelVersion, c: _Cached) -> PredictionMeta:
    first = next(iter(c.stockouts.values()))
    stamps = [s.generated_at for s in c.stockouts.values()]
    return PredictionMeta(agent_id=agent_id, as_of=_utc(first.ts), model_version=mv.version,
                          generated_at=_utc(max(stamps)))


def _stockouts(session: Session, agent: Agent, c: _Cached, as_of: datetime
               ) -> list[FloatStockout]:
    snap = session.scalar(select(FloatSnapshot).where(FloatSnapshot.agent_id == agent.id,
                                                      FloatSnapshot.ts == as_of))
    balance = {FloatType.cash: snap.cash_balance if snap else None,
               FloatType.emoney: snap.emoney_balance if snap else None}
    capacity = {FloatType.cash: agent.cash_capacity, FloatType.emoney: agent.emoney_capacity}
    return [FloatStockout(
        float_type=ft, balance=float(balance[ft] or 0), capacity=float(capacity[ft]),
        stockout_at=_utc(s.stockout_at) if s.stockout_at else None,
        hours_to_stockout=float(s.hours_to_stockout) if s.hours_to_stockout is not None else None,
        confidence=float(s.confidence), refill_aware=_refill_view(s, as_of),
    ) for ft in FLOATS if (s := c.stockouts.get(ft)) is not None]


def _refill_view(s: StockoutPrediction, as_of: datetime) -> RefillAwareStockout | None:
    if s.refill_prob_24h is None:
        return None
    hours = None if s.refill_hours_to_stockout is None else float(s.refill_hours_to_stockout)
    return RefillAwareStockout(
        stockout_at=None if hours is None else _utc(as_of) + timedelta(hours=hours),
        hours_to_stockout=hours, probability_24h=float(s.refill_prob_24h))


def _one(session: Session, agent: Agent) -> tuple[ModelVersion, _Cached] | None:
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        return None
    found = _load(session, mv, [agent.id]).get(agent.id)
    return None if found is None else (mv, found)


def agent_stockout(session: Session, agent: Agent) -> AgentStockout | None:
    if (hit := _one(session, agent)) is None:
        return None
    mv, c = hit
    meta = _meta(agent.id, mv, c)
    return AgentStockout(**meta.model_dump(), floats=_stockouts(session, agent, c, meta.as_of))


def agent_risk(session: Session, agent: Agent) -> AgentRisk | None:
    if (hit := _one(session, agent)) is None:
        return None
    mv, c = hit
    floats = _float_risks(c)
    return AgentRisk(**_meta(agent.id, mv, c).model_dump(), level=worst(f.level for f in floats),
                     by_horizon=_by_horizon(c), floats=floats)


def agent_summary(session: Session, agent: Agent) -> AgentSummary | None:
    if (hit := _one(session, agent)) is None:
        return None
    mv, c = hit
    meta = _meta(agent.id, mv, c)
    risks = {f.float_type: f for f in _float_risks(c)}
    floats = [FloatSummary(**s.model_dump(), level=risks[s.float_type].level,
                           horizons=risks[s.float_type].horizons)
              for s in _stockouts(session, agent, c, meta.as_of) if s.float_type in risks]
    return AgentSummary(**meta.model_dump(), agent=AgentProfile.model_validate(agent),
                        level=worst(f.level for f in floats), by_horizon=_by_horizon(c),
                        floats=floats)


def _row(agent: Agent, c: _Cached) -> AgentRiskRow:
    risks = [r for found in c.risks.values() for r in found]
    top = max(risks, key=lambda r: (SEVERITY[r.level], float(r.probability)))
    soonest = min((s for s in c.stockouts.values() if s.hours_to_stockout is not None),
                  key=lambda s: float(s.hours_to_stockout or 0), default=None)
    return AgentRiskRow(
        agent_id=agent.id, code=agent.code, name=agent.name, district=agent.district,
        upazila=agent.upazila, urban_rural=agent.urban_rural, tier=agent.tier,
        lat=agent.lat, lng=agent.lng, level=top.level, probability=float(top.probability),
        worst_float=top.float_type,
        stockout_at=_utc(soonest.stockout_at) if soonest and soonest.stockout_at else None,
        hours_to_stockout=float(soonest.hours_to_stockout)
        if soonest and soonest.hours_to_stockout is not None else None,
    )


def _sort_key(sort: RiskSort, r: AgentRiskRow) -> tuple[float | str, ...]:
    hours = math.inf if r.hours_to_stockout is None else r.hours_to_stockout
    if sort == "stockout":
        return (hours, -SEVERITY[r.level], r.code)
    if sort == "code":
        return (r.code,)
    if sort == "name":
        return (r.name.casefold(), r.code)
    return (-SEVERITY[r.level], -r.probability, hours, r.code)


def risk_page(session: Session, user: User, horizon: int, level: RiskLevelCode | None,
              sort: RiskSort, page: int, page_size: int, q: str | None) -> AgentRiskPage | None:
    """Scoped agents' risk at one horizon; None when the cache is not built yet."""
    mv = active_model(session, FORECAST_MODEL)
    if mv is None or session.scalar(select(RiskLevel.id).where(
            RiskLevel.model_version_id == mv.id).limit(1)) is None:
        return None
    query = scoped_agents_query(user)
    if q and q.strip():
        term = q.strip()
        query = query.where(or_(*(col.icontains(term, autoescape=True) for col in (
            Agent.code, Agent.name, Agent.district, Agent.upazila))))
    agents = {a.id: a for a in session.scalars(query)}
    cached = _load(session, mv, list(agents), horizon)
    rows = [_row(agents[a], c) for a, c in cached.items()]
    if level is not None:
        rows = [r for r in rows if r.level == level]
    rows.sort(key=lambda r: _sort_key(sort, r))
    start = (page - 1) * page_size
    stamps = [s for c in cached.values() for s in c.stockouts.values()]
    return AgentRiskPage(
        items=rows[start:start + page_size], total=len(rows), page=page, page_size=page_size,
        horizon_h=horizon, model_version=mv.version,
        as_of=_utc(stamps[0].ts) if stamps else None,
        generated_at=_utc(max(s.generated_at for s in stamps)) if stamps else None,
    )

