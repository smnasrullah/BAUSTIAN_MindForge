"""Stockout + risk cache: projected at bootstrap (and each live tick) from the forecast cache
and the balances at the data clock's "now". Method: docs/METHODS.md §2."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.models import (
    Agent,
    FloatSnapshot,
    Forecast,
    RiskLevel,
    StockoutPrediction,
    SystemMeta,
)
from app.models.enums import FloatType, UrbanRural
from app.rules.risk_rules import (
    HEADLINE_HORIZON,
    HORIZONS,
    RiskConfig,
    level_confidence,
    level_for,
)
from app.services import forecast, notify
from app.services.model_registry import active_model
from app.services.risk_history import load_history
from ml.features.panel import AREA_CODE
from ml.inference import refill
from ml.inference.stockout import StockoutConfig, StockoutResult, project
from ml.inference.stockout_joint import (
    POOLED,
    Dependence,
    Refill,
    load_dependence,
    run_paths,
    sample_joint,
    segment,
)
from ml.registry import FORECAST_MODEL

log = logging.getLogger(__name__)
CACHE_KEY = "risk_cache"
METHOD = "mc-copula-2"  # independent floats, fixed rho 0.6 (2: + prob_by_hour)
METHOD_JOINT = "mc-joint-1"  # both floats from joint paths, estimated copula, coupled serving
JOINT_STREAM = 2  # rng stream id beside FLOAT_INDEX (0 cash, 1 e-money) of the old method
REFILL_VIEW = "joint-habit-2"  # refill-aware extra view: joint paths + own refill habit
# Paths of the refill-aware view when it is only the extra reading (independent decision
# input): it is not a decision input, and 2,000 paths cost ~19 s per tick for 300 agents.
REFILL_VIEW_PATHS = 500
PROJECT_THREADS = 4  # live ticks: 300 agents 9.9 s -> 3.3 s (8 or 12 threads were slower)
FLOAT_INDEX = {FloatType.cash: 0, FloatType.emoney: 1}
# Forecasts are stored per float as the demand that drains it (cash <- cash_out,
# e-money <- cash_in); the other float's drain is this float's inflow.
INFLOW_OF = {FloatType.cash: FloatType.emoney, FloatType.emoney: FloatType.cash}

Quantiles = dict[tuple[int, FloatType], np.ndarray]


def path_rng(seed: int, agent_id: int, float_type: FloatType) -> np.random.Generator:
    """Seeded per (seed, agent, float): what-if replays exactly the cached paths."""
    return np.random.default_rng([seed, agent_id, FLOAT_INDEX[float_type]])


def load_quantiles(session: Session, model_version_id: int, horizon: int,
                   agent_id: int | None = None) -> Quantiles:
    query = (select(Forecast.agent_id, Forecast.float_type, Forecast.q_low, Forecast.q_mid,
                    Forecast.q_high)
             .where(Forecast.model_version_id == model_version_id, Forecast.horizon_h <= horizon)
             .order_by(Forecast.agent_id, Forecast.float_type, Forecast.horizon_h))
    if agent_id is not None:
        query = query.where(Forecast.agent_id == agent_id)
    found = session.execute(query).all()
    grouped: dict[tuple[int, FloatType], list[tuple[float, float, float]]] = {}
    for agent_id, float_type, lo, mid, hi in found:
        grouped.setdefault((agent_id, float_type), []).append((float(lo), float(mid), float(hi)))
    return {k: np.array(v) for k, v in grouped.items() if len(v) == horizon}


def load_balances(session: Session, now: datetime) -> dict[int, dict[FloatType, float]]:
    found = session.execute(select(FloatSnapshot.agent_id, FloatSnapshot.cash_balance,
                                   FloatSnapshot.emoney_balance)
                            .where(FloatSnapshot.ts == now)).all()
    return {a: {FloatType.cash: float(c), FloatType.emoney: float(e)} for a, c, e in found}


def joint_rng(seed: int, agent_id: int) -> np.random.Generator:
    """Seeded per (seed, agent): what-if replays exactly the cached joint paths."""
    return np.random.default_rng([seed, agent_id, JOINT_STREAM])


def dependence_for(table: dict[str, Dependence] | None, agent: Agent) -> Dependence:
    """The agent segment's estimated copula; the old assumption when there is no table."""
    if table is None:
        return Dependence()
    key = segment(int(agent.tier), AREA_CODE[UrbanRural(agent.urban_rural)])
    return table.get(key, table[POOLED])


@dataclass
class Projection:
    base: dict[FloatType, StockoutResult]  # no refill: the decision input
    refill: dict[FloatType, StockoutResult] = field(default_factory=dict)  # extra view


def project_agent(agent: Agent, b: dict[FloatType, float], q: Quantiles, sc: StockoutConfig,
                  seed: int, method: str, table: dict[str, Dependence] | None,
                  habit: Refill | None) -> Projection | None:
    """Decision input by `method`; the refill-aware view (joint paths, the agent's refill
    habit) whenever a habit is given."""
    out_q, in_q = q.get((agent.id, FloatType.cash)), q.get((agent.id, FloatType.emoney))
    if out_q is None or in_q is None:
        return None
    rng = joint_rng(seed, agent.id)
    joint, view_cfg = None, sc
    if method == "joint":
        joint = sample_joint(out_q, in_q, dependence_for(table, agent), sc.n_paths, rng)
    elif habit is not None:
        view_cfg = replace(sc, n_paths=min(sc.n_paths, REFILL_VIEW_PATHS))
        joint = sample_joint(out_q, in_q, dependence_for(table, agent), view_cfg.n_paths, rng)
    if method == "independent" or joint is None:
        proj = Projection({ft: project(b[ft], q[(agent.id, ft)], q[(agent.id, INFLOW_OF[ft])],
                                       sc, path_rng(seed, agent.id, ft)) for ft in FLOAT_INDEX})
    else:
        base = run_paths(b[FloatType.cash], b[FloatType.emoney], *joint, sc)
        proj = Projection({FloatType.cash: base.cash, FloatType.emoney: base.emoney})
    if habit is not None and joint is not None:
        ref = run_paths(b[FloatType.cash], b[FloatType.emoney], *joint, view_cfg, habit, rng)
        proj.refill = {FloatType.cash: ref.cash, FloatType.emoney: ref.emoney}
    return proj


def _rows(proj: Projection, base: dict[str, Any], now: datetime, cfg: RiskConfig
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stockouts, risks = [], []
    for ft, res in proj.base.items():
        row = base | {"float_type": ft}
        ref = proj.refill.get(ft)
        stockouts.append(row | {
            "stockout_at": None if res.hours is None else now + timedelta(hours=res.hours),
            "hours_to_stockout": None if res.hours is None else round(res.hours, 2),
            "confidence": round(res.confidence, 4),
            "prob_by_hour": [round(p, 4) for p in res.by_hour()],
            "refill_hours_to_stockout": None if ref is None or ref.hours is None
            else round(ref.hours, 2),
            "refill_prob_24h": None if ref is None
            else round(ref.prob_within(HEADLINE_HORIZON), 4),
        })
        for h in HORIZONS:
            p = round(res.prob_within(h), 4)
            risks.append(row | {"horizon_h": h, "probability": p, "level": level_for(p, h, cfg),
                                "confidence": round(level_confidence(p), 4), "shap_top": []})
    return stockouts, risks


def precompute(session: Session, cfg: RiskConfig, seed: int, force: bool = False,
               stockout_cfg: StockoutConfig | None = None) -> int:
    """Project every agent's floats; write stockout + risk rows. Returns agents written.

    Decision input (risk levels, stockout time): the no-refill projection of
    settings.stockout_method. When the artifacts carry the estimated copula, a refill-aware
    projection (joint paths, coupled floats, the agent's own refill habit) is stored beside it
    as an extra reading only."""
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        raise RuntimeError("no active forecast model; run the forecast precompute first")
    settings = get_settings()
    method = settings.stockout_method
    sc = stockout_cfg or StockoutConfig()
    now = forecast.sim_now(session)
    fc_meta = session.get(SystemMeta, forecast.CACHE_KEY)
    key = {"forecast": fc_meta.value if fc_meta else None, "model_version": mv.version,
           "sim_now": now.isoformat(), "rules": cfg.as_dict(),
           "method": METHOD if method == "independent" else METHOD_JOINT,
           "refill_view": REFILL_VIEW,
           "stockout": asdict(sc), "seed": seed}
    meta = session.get(SystemMeta, CACHE_KEY)
    if not force and meta is not None and meta.value == key:
        log.info("risk cache current (%s)", mv.version)
        return 0
    horizon = max(HORIZONS)
    quantiles = load_quantiles(session, mv.id, horizon)
    balances = load_balances(session, now)
    generated_at = datetime.now(UTC)
    agent_ids = sorted({a for a, _ in quantiles} & set(balances))
    agents = {a.id: a for a in session.scalars(select(Agent).where(Agent.id.in_(agent_ids)))}
    table = load_dependence(settings.artifacts_dir)
    t0 = time.perf_counter()
    habits: dict[int, Refill] = {}
    if table is not None and agent_ids:  # the refill-aware view needs the estimated copula
        hist = load_history(session, now, agent_ids, horizon)
        habits = dict(zip(agent_ids, refill.habits(
            hist.cash, hist.emoney, hist.served_in, hist.served_out, hist.dow, hist.hod,
            hist.t0, horizon), strict=True))
    stockouts: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []

    def one(agent_id: int) -> Projection | None:
        return project_agent(agents[agent_id], balances[agent_id], quantiles, sc, seed, method,
                             table, habits.get(agent_id))

    # Every agent has its own seeded generators, so threads give the same rows as one loop.
    # numpy releases the GIL in the sampling; live ticks have a time budget (fixed: one thread).
    workers = PROJECT_THREADS if clock.is_live() else 1
    t1 = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        projections = list(pool.map(one, agent_ids))
    t2 = time.perf_counter()
    for agent_id, proj in zip(agent_ids, projections, strict=True):
        if proj is None:
            continue
        s, r = _rows(proj, {"model_version_id": mv.id, "agent_id": agent_id, "ts": now,
                            "generated_at": generated_at}, now, cfg)
        stockouts += s
        risks += r
    before = notify.headline_levels(session)
    session.execute(delete(RiskLevel))
    session.execute(delete(StockoutPrediction))
    if stockouts:
        session.execute(insert(StockoutPrediction), stockouts)
        session.execute(insert(RiskLevel), risks)
    notify.risk_changed(session, before, notify.headline_levels(session))
    session.merge(SystemMeta(key=CACHE_KEY, value=key))
    written = len(stockouts) // len(FLOAT_INDEX)
    log.info("risk cache: %d agents at %s (%s, %s); refill history %.1f s, projections %.1f s "
             "(%d threads), write %.1f s", written, now.isoformat(), mv.version, method, t1 - t0,
             t2 - t1, workers, time.perf_counter() - t2)
    return written
