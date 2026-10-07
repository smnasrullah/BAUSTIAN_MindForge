"""Automatic liquidity help: finds agents short of float and plans who to ask. Reads only.

The writes live in help_trigger_run.py (requests) and help_waves.py (wave advance). The demo
shortage (admin helper, DEMO_MODE only) is applied here and every result it produces is marked
simulated; the admin's own "simulate shortage" run (force=True) is not held back by the
cooldown, the daily cap, the demo auto cap or the recent-ask window. Nothing here moves money.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.models import (
    Agent,
    AuditLog,
    Distributor,
    LiquidityRequest,
    LiquidityRequestRecipient,
    RiskLevel,
    StockoutPrediction,
    SystemMeta,
    User,
)
from app.models.enums import FloatType, HelpResponse, RiskLevelCode, UserRole
from app.rules import help_request_rules as hrules
from app.rules import help_trigger_rules as rules
from app.rules.help_trigger_rules import Helper, TriggerPolicy, Verdict
from app.rules.rebalance_rules import ROUND_BDT
from app.rules.risk_rules import HEADLINE_HORIZON
from app.rules.swap_rules import Donor, Receiver, SwapConfig, haversine_km, pair
from app.services import explanation, forecast, help_demo, help_reason, risk
from app.services import liquidity_requests as help_requests
from app.services.forecast import _utc
from app.services.model_registry import active_model
from ml.data_gen.timeline import BDT
from ml.inference import helper_accept
from ml.registry import FORECAST_MODEL

DEMO_KEY = "help_demo_shortage"
DEMO_MINUTES = 30
Key = tuple[int, FloatType]


class TriggerError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Demo:
    agent_id: int
    float_type: FloatType
    until: datetime


@dataclass(frozen=True)
class Signal:
    """One agent and float on the pessimistic path. drain / inflow: hourly BDT (low, mid, high)."""

    agent: Agent
    float_type: FloatType
    balance: float
    level: RiskLevelCode | None
    drain: np.ndarray
    inflow: np.ndarray
    median_h: float | None
    buffer: float
    simulated: bool


@dataclass(frozen=True)
class Ask:
    user_id: uuid.UUID
    display: str  # agent or distributor code, never an e-mail
    role: UserRole
    distance_km: float


@dataclass(frozen=True)
class Pool:
    distributors: list[Ask]  # always asked in wave 1
    agents: list[Ask]  # best first
    accept_p: list[float] | None = None  # model chance of a yes per agent (same order)

    def wave(self, cap: int) -> list[Ask]:
        """Agents for one wave: the rule cap, or fewer with learned wave sizing."""
        settings = get_settings()
        if settings.help_wave_sizing and self.accept_p is not None:
            cap = rules.learned_wave_size(self.accept_p, cap, settings.help_wave_target)
        return self.agents[:cap]


@dataclass
class AgentPlan:
    agent_id: int
    agent_code: str
    float_type: FloatType
    verdict: Verdict
    simulated: bool
    needed_by: datetime | None = None  # wall clock, like stockout_at
    stockout_at: datetime | None = None  # the agent page's stock-out, placed on the wall clock
    urgent: bool = False
    asap: bool = False  # deadline_after_stockout: the floor put needed_by after the stock-out
    skipped: str | None = None
    reason: help_reason.HelpReason | None = None
    asks: list[Ask] = field(default_factory=list)

    @property
    def would_create(self) -> bool:
        return self.verdict.fires and self.skipped is None


def current_demo(session: Session, now: datetime) -> Demo | None:
    """The simulated shortage, if one is active. Never when DEMO_MODE is off."""
    if not get_settings().demo_mode:
        return None
    row = session.get(SystemMeta, DEMO_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    until = _utc(datetime.fromisoformat(str(row.value["until"])))
    if until <= now:
        return None
    return Demo(int(row.value["agent_id"]), FloatType(row.value["float_type"]), until)


def signals(session: Session, now: datetime, tp: TriggerPolicy,
            demo: Demo | None) -> dict[Key, Signal]:
    """Every agent and float the forecast covers. Empty when no forecast model is active."""
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        return {}
    quantiles = risk.load_quantiles(session, mv.id, max(tp.horizon_h, rules.DAY_HOURS))
    balances = risk.load_balances(session, forecast.sim_now(session))
    levels = {(a, f): lvl for a, f, lvl in session.execute(
        select(RiskLevel.agent_id, RiskLevel.float_type, RiskLevel.level).where(
            RiskLevel.model_version_id == mv.id,
            RiskLevel.horizon_h == HEADLINE_HORIZON)).all()}
    medians = {(a, f): None if h is None else float(h) for a, f, h in session.execute(
        select(StockoutPrediction.agent_id, StockoutPrediction.float_type,
               StockoutPrediction.hours_to_stockout).where(
            StockoutPrediction.model_version_id == mv.id)).all()}
    agents = {a.id: a for a in session.scalars(select(Agent).where(Agent.is_active.is_(True)))}
    out: dict[Key, Signal] = {}
    for (agent_id, ft), drain in quantiles.items():
        inflow = quantiles.get((agent_id, risk.INFLOW_OF[ft]))
        if inflow is None or agent_id not in agents or agent_id not in balances:
            continue
        simulated = demo is not None and demo.agent_id == agent_id and demo.float_type == ft
        balance, level = balances[agent_id][ft], levels.get((agent_id, ft))
        if simulated:
            balance, level = 0.0, RiskLevelCode.red
        daily = float(drain[:rules.DAY_HOURS, 1].sum())  # the agent's own expected 24 h demand
        out[(agent_id, ft)] = Signal(
            agent=agents[agent_id], float_type=ft, balance=balance, level=level, drain=drain,
            inflow=inflow, median_h=medians.get((agent_id, ft)),
            buffer=rules.buffer_bdt(daily, tp), simulated=simulated)
    return out


def abuse_block(session: Session, agent_id: int, now: datetime,
                hp: hrules.HelpPolicy) -> str | None:
    earlier = session.scalars(select(LiquidityRequest.created_at).where(
        LiquidityRequest.requester_agent_id == agent_id,
        LiquidityRequest.created_at > help_demo.window_start(session, agent_id, now)))
    return hrules.abuse_block((_utc(t) for t in earlier), now, hp)


def _stats(session: Session, user_ids: list[uuid.UUID], now: datetime
           ) -> dict[uuid.UUID, tuple[int, int, int, datetime | None]]:
    """user -> (asked ever, accepted ever, asked in the fairness window, last asked).
    DEMO_MODE: asks before the last demo reset do not count."""
    if not user_ids:
        return {}
    r = LiquidityRequestRecipient
    since = help_demo.reset_at(session)
    scope = [r.recipient_user_id.in_(user_ids)]
    if since is not None:
        scope.append(r.notified_at > since)
    rows = session.execute(select(
        r.recipient_user_id, func.count(),
        func.count(case((r.response == HelpResponse.accepted, 1))),
        func.count(case((r.notified_at > now - rules.ASK_WINDOW, 1))),
        func.max(r.notified_at)).where(*scope)
        .group_by(r.recipient_user_id)).all()
    return {uid: (asked, acc, recent, _utc(last) if last else None)
            for uid, asked, acc, recent, last in rows}


def _near_helpers(requester: Agent, float_type: FloatType, amount: float, tp: TriggerPolicy,
                  sigs: dict[Key, Signal]) -> dict[int, tuple[Signal, float, float]]:
    """Agents that can cover the whole amount alone, after their own need and buffer.
    Feasibility is the swap rule (same distributor, within radius), not a second copy of it."""
    cfg = SwapConfig(radius_km=tp.radius_km, min_amount_bdt=ROUND_BDT)
    receiver = Receiver(requester.id, requester.distributor_id, requester.lat, requester.lng,
                        float_type, amount)
    out: dict[int, tuple[Signal, float, float]] = {}
    for (aid, ft), sig in sigs.items():
        agent = sig.agent
        same_team = agent.distributor_id == requester.distributor_id
        if ft != float_type or aid == requester.id or not same_team:
            continue
        if agent.help_opt_out or not agent.is_active:
            continue
        surplus = rules.surplus_bdt(sig.balance, sig.drain[:, 2], sig.inflow[:, 0], sig.buffer, tp)
        if surplus <= 0:
            continue
        donor = Donor(aid, agent.distributor_id, agent.lat, agent.lng, {float_type: surplus})
        match = pair(donor, receiver, cfg)
        if match is not None and match.van_trip_saved:
            out[aid] = (sig, match.distance_km, surplus)
    return out


def ranked_helpers(session: Session, requester: Agent, float_type: FloatType, amount: float,
                   now: datetime, tp: TriggerPolicy, sigs: dict[Key, Signal],
                   exclude: set[uuid.UUID], ignore_recent: bool = False) -> Pool:
    """Distributor users (always, no surplus test) and agent users ranked by rank_score.
    Excluded: already asked in this request, opted out, inactive, asked recently (unless
    ignore_recent: the admin's demo simulation)."""
    distributor = session.get(Distributor, requester.distributor_id)
    dist_asks: list[Ask] = []
    if distributor is not None:
        km = haversine_km(requester.lat, requester.lng, distributor.hub_lat, distributor.hub_lng)
        for u in session.scalars(select(User).where(
                User.role == UserRole.distributor, User.distributor_id == distributor.id,
                User.is_active.is_(True))):
            if u.id not in exclude:
                dist_asks.append(Ask(u.id, distributor.code, UserRole.distributor, round(km, 2)))
    near = _near_helpers(requester, float_type, amount, tp, sigs)
    users = [u for u in session.scalars(select(User).where(
        User.role == UserRole.agent, User.agent_id.in_(list(near)),
        User.is_active.is_(True))) if u.id not in exclude and u.agent_id is not None]
    stats = _stats(session, [u.id for u in users], now)
    helpers: list[Helper] = []
    asks: dict[uuid.UUID, Ask] = {}
    tiers: dict[uuid.UUID, int] = {}
    for u in users:
        sig, km, surplus = near[u.agent_id or 0]
        asked, accepted, recent, last = stats.get(u.id, (0, 0, 0, None))
        if not ignore_recent and rules.asked_recently(last, now, tp):
            continue
        helpers.append(Helper(u.id, km, surplus, recent, asked, accepted))
        asks[u.id] = Ask(u.id, sig.agent.code, UserRole.agent, round(km, 2))
        tiers[u.id] = int(sig.agent.tier)
    ordered = rules.rank(helpers)
    probs = _accept_chances(ordered, tiers, amount, now)
    if probs is not None and get_settings().help_rank_model == "learned":
        # Highest chance first; the rule order breaks ties. Same helpers, only reordered.
        idx = sorted(range(len(ordered)), key=lambda i: (-probs[i], i))
        ordered, probs = [ordered[i] for i in idx], [probs[i] for i in idx]
    return Pool(dist_asks, [asks[h.user_id] for h in ordered], probs)


def _accept_chances(helpers: list[Helper], tiers: dict[uuid.UUID, int], amount: float,
                    now: datetime) -> list[float] | None:
    """Model chance of a yes per helper; None when neither learned order nor learned wave
    sizing is on, or the model artifact is missing."""
    settings = get_settings()
    if not helpers or (settings.help_rank_model != "learned" and not settings.help_wave_sizing):
        return None
    model = helper_accept.load(settings.artifacts_dir)
    if model is None:
        return None
    hod = clock.as_utc(now).astimezone(BDT).hour
    x = np.array([helper_accept.feature_row(h.distance_km, hod, h.asks_in_window, h.surplus,
                                            amount, tiers[h.user_id], h.asked, h.accepted)
                  for h in helpers])
    return [float(p) for p in model.predict(x)]


def _reason(session: Session, sig: Signal, v: Verdict) -> help_reason.HelpReason:
    """Code + parameters from the agent's own explanation (rendered per reader language)."""
    hit = explanation.load(session, sig.agent.id, sig.float_type)
    return help_reason.forecast_short(sig.float_type, v.stockout_h, sig.simulated,
                                      hit[1] if hit else None)


def _plan_one(session: Session, sig: Signal, now: datetime, tp: TriggerPolicy,
              hp: hrules.HelpPolicy, sigs: dict[Key, Signal], force: bool,
              lag: float = 0.0) -> AgentPlan:
    """`now` is wall-clock time; the forecast's hours count from its origin, which is placed at
    `now` (app/core/clock.py), so needed_by and stockout_at are wall-clock times. `lag`: hours
    of the forecast already passed (live clock: the origin is the start of the current hour).
    force: the admin's simulation; a simulated signal skips the requester and helper limits."""
    v = rules.evaluate(sig.balance, sig.drain[:, 2], sig.inflow[:, 0], sig.buffer, sig.level,
                       sig.median_h, tp)
    item = AgentPlan(sig.agent.id, sig.agent.code, sig.float_type, v, sig.simulated)
    if not v.fires:
        return item
    shown_h = v.stockout_h if sig.simulated or sig.median_h is None else sig.median_h
    item.stockout_at = clock.hours_after(now, max(shown_h - lag, 0.0))
    item.needed_by = clock.as_utc(now) + rules.deadline_after(max(v.stockout_h - lag, 0.0), tp)
    item.urgent = rules.is_urgent(v.stockout_h, tp)
    item.asap = rules.deadline_after_stockout(v.stockout_h, tp)
    key = help_requests.dedupe_key(sig.agent.id, sig.float_type)
    if help_requests.active_for(session, key) is not None:
        item.skipped = "active_request"
        return item
    bypass = force and sig.simulated
    if not bypass:
        item.skipped = abuse_block(session, sig.agent.id, now, hp)
        if item.skipped is None and help_demo.auto_capped(session, sig.agent.id,
                                                          sig.float_type, now):
            item.skipped = "demo_daily_auto"
        if item.skipped:
            return item
    pool = ranked_helpers(session, sig.agent, sig.float_type, v.amount_bdt, now, tp, sigs, set(),
                          ignore_recent=bypass)
    item.asks = pool.distributors + pool.wave(wave_one_cap(item.urgent, tp, hp))
    if not item.asks:
        item.skipped = "no_candidates"
    else:
        item.reason = _reason(session, sig, v)
    return item


def wave_one_cap(urgent: bool, tp: TriggerPolicy, hp: hrules.HelpPolicy) -> int:
    return rules.wave_one_agents(hp.max_recipients_per_wave, urgent, tp)


def plan(session: Session, now: datetime, tp: TriggerPolicy, hp: hrules.HelpPolicy,
         agent_ids: set[int] | None = None, demo: Demo | None = None,
         force: bool = False) -> list[AgentPlan]:
    """Every agent and float: verdict, skip reason and who would be asked. Never writes."""
    sigs = signals(session, now, tp, demo)
    keys = sorted(k for k in sigs if agent_ids is None or k[0] in agent_ids)
    lag = clock.lag_h(forecast.sim_now(session), now)
    return [_plan_one(session, sigs[k], now, tp, hp, sigs, force, lag) for k in keys]


def simulate_shortage(session: Session, user: User, agent_id: int, float_type: FloatType,
                      now: datetime) -> datetime:
    """Admin, DEMO_MODE only: the agent looks short of this float for DEMO_MINUTES. Audited."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise TriggerError("unknown_agent")
    until = now + timedelta(minutes=DEMO_MINUTES)
    value = {"agent_id": agent.id, "float_type": float_type.value, "until": until.isoformat()}
    session.merge(SystemMeta(key=DEMO_KEY, value=value))
    session.add(AuditLog(user_id=user.id, action="help_demo.simulate_shortage",
                         entity_type="agent", entity_id=str(agent.id), note=None,
                         payload={**value, "simulated": True, "agent_code": agent.code}))
    session.flush()
    return until


def set_opt_out(session: Session, user: User, opted_out: bool) -> bool:
    """An agent chooses whether they can be asked for help. Audited."""
    agent = session.get(Agent, user.agent_id) if user.agent_id is not None else None
    if agent is None:
        raise TriggerError("forbidden")
    agent.help_opt_out = opted_out
    session.add(AuditLog(user_id=user.id, action="help.opt_out", entity_type="agent",
                         entity_id=str(agent.id), note=None, payload={"opted_out": opted_out}))
    session.flush()
    return opted_out
