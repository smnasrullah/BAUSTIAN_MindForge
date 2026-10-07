"""Rebalance + swap cache: recommendations and swap suggestions at SIM_NOW, built after risk.

Re-running replaces only open recommendations and pending swaps; decided swaps stay with
their audit trail. Open recommendations that already have a request history are expired
instead of deleted. Each recommendation gets a delivery channel (app/rules/channel_rules.py).
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Agent,
    Distributor,
    Recommendation,
    RecommendationRequest,
    RiskLevel,
    StockoutPrediction,
    SwapSuggestion,
    SystemMeta,
)
from app.models.enums import (
    FloatType,
    RecommendationChannel,
    RecommendationKind,
    RecommendationStatus,
    RiskLevelCode,
    SwapStatus,
)
from app.rules.channel_rules import ChannelConfig, Choice, Shortage, SwapCover, choose
from app.rules.rebalance_rules import Advice, Need, RebalanceConfig, advise, assess
from app.rules.risk_rules import HEADLINE_HORIZON, SEVERITY
from app.rules.swap_rules import (
    Donor,
    FlowConfig,
    Match,
    Receiver,
    SwapConfig,
    haversine_km,
    match,
    match_flow,
)
from app.services import forecast, notify, risk
from app.services.model_registry import active_model
from app.services.seed import DEMO_AGENTS
from ml.registry import FORECAST_MODEL

log = logging.getLogger(__name__)
CACHE_KEY = "rebalance_cache"
DEMO_CODES = frozenset(s.code for s in DEMO_AGENTS)
KIND = {FloatType.cash: RecommendationKind.add_cash,
        FloatType.emoney: RecommendationKind.add_emoney}
CHANNEL_KIND = {RecommendationChannel.swap: RecommendationKind.swap,
                RecommendationChannel.van: RecommendationKind.van}
NEEDS_HELP = (RiskLevelCode.amber, RiskLevelCode.red)
Key = tuple[int, FloatType]


@dataclass(frozen=True)
class _Plan:
    agent: Agent
    float_type: FloatType
    need: Need
    advice: Advice
    level: RiskLevelCode
    probability: float


def configs(settings: Settings) -> tuple[RebalanceConfig, SwapConfig, ChannelConfig]:
    return (RebalanceConfig(horizon_h=settings.rebalance_horizon_h,
                            lead_time_h=settings.rebalance_lead_time_h,
                            buffer_share=settings.rebalance_buffer_share,
                            buffer_min_bdt=settings.rebalance_buffer_min_bdt),
            SwapConfig(radius_km=settings.swap_radius_km,
                       min_amount_bdt=settings.swap_min_amount_bdt),
            ChannelConfig(van_min_batch_amount_bdt=settings.van_min_batch_amount_bdt,
                          van_lead_time_h=settings.van_lead_time_h,
                          van_cluster_radius_km=settings.van_cluster_radius_km,
                          van_cost_per_trip_bdt=settings.van_cost_per_trip_bdt,
                          topup_fee_pct=settings.topup_fee_pct,
                          topup_eta_h=settings.topup_eta_h,
                          self_fetch_max_km=settings.self_fetch_max_km,
                          self_fetch_speed_kmh=settings.self_fetch_speed_kmh,
                          travel_cost_per_km_bdt=settings.travel_cost_per_km_bdt,
                          urgent_manual_cost_bdt=settings.urgent_manual_cost_bdt))


def flow_config(settings: Settings, ccfg: ChannelConfig) -> FlowConfig | None:
    """Split matching settings, or None for the one-to-one assignment (the default)."""
    if settings.swap_matching != "flow":
        return None
    return FlowConfig(settings.swap_max_receivers_per_donor,
                      settings.swap_max_donors_per_receiver, ccfg.self_fetch_speed_kmh,
                      ccfg.travel_cost_per_km_bdt)


def _headline(session: Session, mv_id: int) -> dict[Key, tuple[RiskLevelCode, float]]:
    found = session.execute(select(RiskLevel.agent_id, RiskLevel.float_type, RiskLevel.level,
                                   RiskLevel.probability)
                            .where(RiskLevel.model_version_id == mv_id,
                                   RiskLevel.horizon_h == HEADLINE_HORIZON)).all()
    return {(a, ft): (lvl, float(p)) for a, ft, lvl, p in found}


def _median_hours(session: Session, mv_id: int) -> dict[Key, float | None]:
    found = session.execute(select(StockoutPrediction.agent_id, StockoutPrediction.float_type,
                                   StockoutPrediction.hours_to_stockout)
                            .where(StockoutPrediction.model_version_id == mv_id)).all()
    return {(a, ft): None if h is None else float(h) for a, ft, h in found}


def _receivers(plans: list[_Plan]) -> dict[int, _Plan]:
    """Worst amber/red cash float per agent (e-money shortages are topped up digitally)."""
    out: dict[int, _Plan] = {}
    for p in plans:
        if p.level not in NEEDS_HELP or p.float_type != FloatType.cash:
            continue
        cur = out.get(p.agent.id)
        if cur is None or (SEVERITY[p.level], p.probability) > (SEVERITY[cur.level],
                                                                 cur.probability):
            out[p.agent.id] = p
    return out


def _rationale(p: _Plan, now: datetime, rcfg: RebalanceConfig) -> dict[str, Any]:
    return {"as_of": now.isoformat(), "horizon_h": rcfg.horizon_h,
            "lead_time_h": rcfg.lead_time_h, "balance_bdt": round(p.need.balance, 2),
            "capacity_bdt": round(p.need.capacity, 2), "need_bdt": round(p.need.peak_drain, 2),
            "shortfall_bdt": round(p.need.shortfall, 2), "buffer_bdt": round(p.need.buffer, 2),
            "stockout_at": p.advice.stockout_at.isoformat(), "urgent": p.advice.urgent,
            "capped": p.advice.capped, "risk_level": p.level.value,
            "risk_probability": p.probability}


def _write_swaps(session: Session, mv_id: int, matches: list[Match]) -> dict[Key, SwapCover]:
    """Insert pending swaps; returns (receiver agent id, float) -> cover."""
    out: dict[Key, SwapCover] = {}
    for m in matches:
        row = SwapSuggestion(model_version_id=mv_id, donor_agent_id=m.donor.agent_id,
                             receiver_agent_id=m.receiver.agent_id,
                             float_type=m.receiver.float_type, amount_bdt=m.amount,
                             distance_km=m.distance_km, van_trip_saved=m.van_trip_saved,
                             score=m.score)
        session.add(row)
        session.flush()
        _cover(out, (m.receiver.agent_id, m.receiver.float_type), row.id, m.amount,
               m.distance_km)
    return out


def _cover(out: dict[Key, SwapCover], key: Key, swap_id: int, amount: float, km: float) -> None:
    """A receiver's hand-overs add up (split matching); the first swap id names the cover."""
    cur = out.get(key)
    out[key] = SwapCover(swap_id, amount, km) if cur is None else SwapCover(
        cur.swap_id, cur.amount + amount, max(cur.distance_km, km))


def _approved(session: Session, mv_id: int) -> tuple[set[int], dict[Key, SwapCover]]:
    """Agents already in an approved swap (not re-matched) and (receiver, float) -> cover."""
    found = session.scalars(select(SwapSuggestion).where(
        SwapSuggestion.model_version_id == mv_id,
        SwapSuggestion.status == SwapStatus.approved)).all()
    busy = {a for s in found for a in (s.donor_agent_id, s.receiver_agent_id)}
    covers: dict[Key, SwapCover] = {}
    for s in sorted(found, key=lambda s: s.id):
        _cover(covers, (s.receiver_agent_id, s.float_type), s.id, float(s.amount_bdt),
               float(s.distance_km))
    return busy, covers


def _channels(session: Session, plans: list[_Plan], swaps: dict[Key, SwapCover],
              now: datetime, ccfg: ChannelConfig) -> dict[int, Choice]:
    """Channel per plan index."""
    hubs = {d.id: (d.hub_lat, d.hub_lng) for d in session.scalars(select(Distributor))}
    shortages = []
    for i, p in enumerate(plans):
        hub = hubs.get(p.agent.distributor_id)
        hub_km = None if hub is None else haversine_km(p.agent.lat, p.agent.lng, *hub)
        left = (p.advice.deadline_at - now).total_seconds() / 3600
        shortages.append(Shortage(
            key=i, distributor_id=p.agent.distributor_id, lat=p.agent.lat, lng=p.agent.lng,
            float_type=p.float_type, amount=p.advice.amount, hours_to_deadline=max(0.0, left),
            hub_km=hub_km, swap=swaps.get((p.agent.id, p.float_type))))
    return choose(shortages, ccfg)


def _channel_rationale(choice: Choice) -> dict[str, Any]:
    return {"channel": choice.channel.value, "van_route_id": choice.van_route_id,
            "alternatives": [asdict(a) for a in choice.alternatives],
            "rule_trace": [asdict(t) for t in choice.trace]}


def _plans(session: Session, mv_id: int, now: datetime, rcfg: RebalanceConfig
           ) -> tuple[dict[int, Agent], list[_Plan], dict[int, dict[FloatType, float]]]:
    """Per agent and float: pessimistic need, top-up advice, giveable surplus."""
    quantiles = risk.load_quantiles(session, mv_id, rcfg.horizon_h)
    balances = risk.load_balances(session, now)
    headline, medians = _headline(session, mv_id), _median_hours(session, mv_id)
    ids = sorted({a for a, _ in quantiles} & set(balances))
    agents = {a.id: a for a in session.scalars(select(Agent).where(Agent.id.in_(ids)))}
    plans: list[_Plan] = []
    surplus: dict[int, dict[FloatType, float]] = {}
    for agent_id, agent in agents.items():
        capacity = {FloatType.cash: float(agent.cash_capacity),
                    FloatType.emoney: float(agent.emoney_capacity)}
        for ft in KIND:
            drain = quantiles.get((agent_id, ft))
            inflow = quantiles.get((agent_id, risk.INFLOW_OF[ft]))
            if drain is None or inflow is None or (agent_id, ft) not in headline:
                continue
            need = assess(balances[agent_id][ft], capacity[ft], drain[:, 2], inflow[:, 0], rcfg)
            surplus.setdefault(agent_id, {})[ft] = need.surplus
            advice = advise(need, now, medians.get((agent_id, ft)), rcfg)
            if advice is not None and advice.amount > 0:
                level, prob = headline[(agent_id, ft)]
                plans.append(_Plan(agent, ft, need, advice, level, prob))
    return agents, plans, surplus


def precompute(session: Session, rcfg: RebalanceConfig, scfg: SwapConfig,
               ccfg: ChannelConfig | None = None, force: bool = False) -> int:
    """Write recommendations + swap suggestions. Returns recommendations written."""
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        raise RuntimeError("no active forecast model; run the forecast precompute first")
    ccfg = ccfg or ChannelConfig()
    fcfg = flow_config(get_settings(), ccfg)
    risk_meta = session.get(SystemMeta, risk.CACHE_KEY)
    key = {"risk": risk_meta.value if risk_meta else None, "rules": asdict(rcfg),
           "swap": asdict(scfg), "channel": asdict(ccfg),
           "matching": None if fcfg is None else asdict(fcfg)}
    meta = session.get(SystemMeta, CACHE_KEY)
    if not force and meta is not None and meta.value.get("key") == key:
        log.info("rebalance cache current (%s)", mv.version)
        return 0
    now = forecast.sim_now(session)
    agents, plans, surplus = _plans(session, mv.id, now, rcfg)
    receivers = _receivers(plans)
    busy, swaps = _approved(session, mv.id)
    # Demo logins first: otherwise a closer stranger takes the donor pinned for their story.
    demo = frozenset(a.id for a in agents.values() if a.code in DEMO_CODES)
    donors = [Donor(a.id, a.distributor_id, a.lat, a.lng, surplus.get(a.id, {}))
              for a in agents.values() if a.id not in receivers and a.id not in busy]
    wanted = [Receiver(p.agent.id, p.agent.distributor_id, p.agent.lat, p.agent.lng,
                       p.float_type, p.advice.amount)
              for p in receivers.values() if p.agent.id not in busy]
    if fcfg is None:
        matches = match(donors, wanted, scfg, first=demo)
    else:
        left = {p.agent.id: max(0.0, (p.advice.deadline_at - now).total_seconds() / 3600)
                for p in receivers.values()}
        matches = match_flow(donors, wanted, scfg, fcfg, left, first=demo)
    requested = select(RecommendationRequest.recommendation_id)
    session.execute(update(Recommendation).where(
        Recommendation.status == RecommendationStatus.open, Recommendation.id.in_(requested))
        .values(status=RecommendationStatus.expired))
    session.execute(delete(Recommendation).where(
        Recommendation.status == RecommendationStatus.open))
    known = notify.pending_swap_keys(session)
    session.execute(delete(SwapSuggestion).where(SwapSuggestion.status == SwapStatus.pending))
    swaps |= _write_swaps(session, mv.id, matches)
    notify.swap_offers(session, known)
    choices = _channels(session, plans, swaps, now, ccfg)
    rows: list[dict[str, Any]] = []
    for i, p in enumerate(plans):
        choice = choices[i]
        rationale = _rationale(p, now, rcfg) | _channel_rationale(choice)
        hit = swaps.get((p.agent.id, p.float_type))
        if hit is not None:
            rationale |= {"swap_id": hit.swap_id, "swap_amount_bdt": hit.amount}
        rows.append({"agent_id": p.agent.id, "model_version_id": mv.id,
                     "kind": CHANNEL_KIND.get(choice.channel, KIND[p.float_type]),
                     "float_type": p.float_type, "amount_bdt": p.advice.amount,
                     "deadline_at": p.advice.deadline_at, "channel": choice.channel,
                     "van_route_id": choice.van_route_id, "rationale": rationale})
    if rows:
        session.execute(insert(Recommendation), rows)
    session.merge(SystemMeta(key=CACHE_KEY, value={
        "key": key, "generated_at": datetime.now(UTC).isoformat()}))
    log.info("rebalance cache: %d recommendations, %d swaps (%s)", len(rows), len(matches),
             mv.version)
    return len(rows)
