"""Shared inputs of the holdout backtests (impact F11, fairness F12).

Ground truth = the seeded generator re-run in memory (same seed and agent count as the database):
it holds the full customer demand, incl. what the logged history turned away, plus each agent's
routine refill plan. It is checked against the stored balances before use. Forecasts are made at
every planning round of the 14 held-out days from the logged history before that round only.

Live clock: the held-out days are the 14 days before the current origin; ground truth comes from
the live engine (deterministic per date) and the opening balances from the database. The world
ends at the origin: no future demand is used.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.models import Agent, Distributor, FloatSnapshot
from app.rules.impact_rules import ImpactConfig
from app.rules.swap_rules import haversine_km
from app.services.impact_policies import Forecasts
from app.services.impact_sim import Site, World
from ml.data_gen import live_load
from ml.data_gen.dataset import Dataset, build_dataset
from ml.data_gen.live import H1, Engine, local
from ml.data_gen.timeline import HOLDOUT_START, N_HOURS, Window, hour_index, hour_of_day
from ml.features.build import MIN_HISTORY_H
from ml.features.panel import TARGETS, Panel, load_panel
from ml.inference.forecaster import Forecaster

log = logging.getLogger(__name__)
BALANCE_TOLERANCE_BDT = 1.0  # stored balances are rounded to whole BDT


@dataclass
class Holdout:
    h0: int  # timeline hour index of world hour 0 (= HOLDOUT_START)
    agents: list[Agent]  # DB rows, world order
    world: World
    forecasts: Forecasts  # world hour of each planning round -> target -> (A, H, 3)
    served: dict[str, np.ndarray]  # target -> (A, N_HOURS) logged served demand (panel)
    balance: dict[str, np.ndarray]  # "cash" / "emoney" -> (A, T) logged balance, top of hour
    unmet: dict[str, np.ndarray]  # target -> (A, T) logged turned-away demand


def origins(h0: int, cfg: ImpactConfig, limit: int = N_HOURS) -> list[int]:
    """Timeline hour index of every planning round inside the holdout (before `limit`)."""
    return [d + h for d in range(h0, limit, 24) for h in sorted(cfg.decision_hours)
            if d + h < limit]


def predict(fc: Forecaster, panel: Panel, rows: np.ndarray, starts: list[int], horizon: int,
            limit: int = N_HOURS) -> dict[int, dict[str, np.ndarray]]:
    """origin -> target -> (len(rows), H, 3); H shrinks only at the end (`limit`)."""
    spans = [min(horizon, limit - o) for o in starts]
    r = np.concatenate([np.repeat(rows, h) for h in spans])
    o = np.concatenate([np.full(len(rows) * h, s) for s, h in zip(starts, spans, strict=True)])
    hs = np.concatenate([np.tile(np.arange(1, h + 1), len(rows)) for h in spans])
    pred = {t: fc.predict_rows(panel, t, r, o, hs) for t in TARGETS}
    out: dict[int, dict[str, np.ndarray]] = {}
    at = 0
    for s, h in zip(starts, spans, strict=True):
        n = len(rows) * h
        out[s] = {t: pred[t][at:at + n].reshape(len(rows), h, 3) for t in TARGETS}
        at += n
    return out


def _matches_db(session: Session, ds: Dataset, idx: list[int], agents: list[Agent],
                h0: int) -> bool:
    stored = dict(session.execute(
        select(FloatSnapshot.agent_id, FloatSnapshot.cash_balance)
        .where(FloatSnapshot.ts == HOLDOUT_START.astimezone(UTC))).tuples().all())
    return all(a.id in stored and abs(float(stored[a.id]) - ds.floats.cash[i, h0])
               <= BALANCE_TOLERANCE_BDT for a, i in zip(agents, idx, strict=True))


def _world(session: Session, ds: Dataset, idx: list[int], agents: list[Agent], h0: int
           ) -> World:
    hubs = {d.id: (d.hub_lat, d.hub_lng) for d in session.scalars(select(Distributor))}
    sites = [Site(a.id, a.distributor_id, a.lat, a.lng,
                  None if a.distributor_id not in hubs
                  else haversine_km(a.lat, a.lng, *hubs[a.distributor_id])) for a in agents]
    fl, d, span = ds.floats, ds.demand, slice(h0, N_HOURS)
    return World(
        sites=sites, start=HOLDOUT_START.astimezone(UTC), hod=hour_of_day()[span],
        cash_cap=np.array([float(a.cash_capacity) for a in agents]),
        em_cap=np.array([float(a.emoney_capacity) for a in agents]),
        demand_in=d.amt_in[idx, span].astype(float), demand_out=d.amt_out[idx, span].astype(float),
        scheduled=fl.scheduled[idx, span], cash_target=fl.cash_target[idx, span],
        em_target=fl.emoney_target[idx], cash0=fl.cash[idx, h0], em0=fl.emoney[idx, h0])


def _sites(session: Session, agents: list[Agent]) -> list[Site]:
    hubs = {d.id: (d.hub_lat, d.hub_lng) for d in session.scalars(select(Distributor))}
    return [Site(a.id, a.distributor_id, a.lat, a.lng,
                 None if a.distributor_id not in hubs
                 else haversine_km(a.lat, a.lng, *hubs[a.distributor_id])) for a in agents]


def _balances(session: Session, agents: list[Agent], win: Window, h0: int, end: int
              ) -> tuple[np.ndarray, np.ndarray]:
    row = {a.id: i for i, a in enumerate(agents)}
    cash = np.full((len(agents), end - h0), np.nan)
    em = np.full_like(cash, np.nan)
    for aid, ts, c, e in session.execute(
            select(FloatSnapshot.agent_id, FloatSnapshot.ts, FloatSnapshot.cash_balance,
                   FloatSnapshot.emoney_balance).where(
                FloatSnapshot.ts >= win.ts_of(h0), FloatSnapshot.ts < win.ts_of(end))).tuples():
        t, r = win.hour_index(clock.as_utc(ts)) - h0, row.get(aid)
        if r is not None and 0 <= t < end - h0:
            cash[r, t], em[r, t] = float(c), float(e)
    return cash, em


def _load_live(session: Session, settings: Settings, cfg: ImpactConfig, horizon: int
               ) -> Holdout | None:
    origin: datetime = clock.data_now(session)
    win = clock.window_at(origin)
    h0, end = win.hour_index(win.holdout_start), win.hour_index(origin)
    world = live_load.world_for(session, settings.seed)
    code_index = {a.code: i for i, a in enumerate(world.agents)}
    panel = load_panel(session, end=end, window=win, since=h0 - MIN_HISTORY_H - 24)
    by_id = {a.id: a for a in session.scalars(select(Agent))}
    rows = np.array([r for r, aid in enumerate(panel.agent_ids.tolist())
                     if by_id[aid].code in code_index], dtype=np.int64)
    agents = [by_id[int(panel.agent_ids[r])] for r in rows]
    idx = [code_index[a.code] for a in agents]
    if not agents:
        log.warning("holdout backtest skipped: no live agents")
        return None
    engine = Engine(world)
    t_n = end - h0
    shape = (len(agents), t_n)
    d_in, d_out, cash_t = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    sched = np.zeros(shape, dtype=bool)
    for k in range(t_n):
        lt = local(win.holdout_start + k * H1)
        blk = engine.block(lt.date())
        d_in[:, k], d_out[:, k] = blk.amt_in[idx, lt.hour], blk.amt_out[idx, lt.hour]
        sched[:, k], cash_t[:, k] = blk.scheduled[idx, lt.hour], blk.cash_target[idx]
    cash, em = _balances(session, agents, win, h0, end)
    if np.isnan(cash[:, 0]).any():
        log.warning("holdout backtest skipped: no balances at the live holdout start")
        return None
    served = {t: panel.demand[t][rows] for t in TARGETS}
    over = served["cash_out"][:, h0:end] - d_out > 1.0
    if over.mean() > 0.001:  # the stored flows must fit inside the engine's demand
        log.warning("holdout backtest skipped: stored data does not match the live engine")
        return None
    world_in = World(
        sites=_sites(session, agents), start=win.holdout_start.astimezone(UTC),
        hod=np.array([local(win.holdout_start + k * H1).hour for k in range(t_n)]),
        cash_cap=np.array([float(a.cash_capacity) for a in agents]),
        em_cap=np.array([float(a.emoney_capacity) for a in agents]),
        demand_in=d_in, demand_out=d_out, scheduled=sched, cash_target=cash_t,
        em_target=engine.em_target[idx], cash0=cash[:, 0], em0=em[:, 0])
    starts = origins(h0, cfg, end)
    fc = Forecaster.load(settings.artifacts_dir, settings.forecast_conformal)
    fc.threads = 0  # all cores: row-parallel prediction, same numbers as one thread
    raw = predict(fc, panel, rows, starts, horizon, end)
    return Holdout(
        h0=h0, agents=agents, world=world_in, forecasts={o - h0: v for o, v in raw.items()},
        served=served, balance={"cash": np.nan_to_num(cash), "emoney": np.nan_to_num(em)},
        unmet={"cash_out": np.maximum(d_out - served["cash_out"][:, h0:end], 0),
               "cash_in": np.maximum(d_in - served["cash_in"][:, h0:end], 0)})


def load(session: Session, settings: Settings, cfg: ImpactConfig, horizon: int
         ) -> Holdout | None:
    """None (logged) when the stored data is not the seeded synthetic data."""
    if clock.is_live():
        return _load_live(session, settings, cfg, horizon)
    n = session.scalar(select(func.count(distinct(FloatSnapshot.agent_id)))) or 0
    if n == 0:
        log.warning("holdout backtest skipped: no float snapshots")
        return None
    ds = build_dataset(settings.seed, n)
    code_index = {a.code: i for i, a in enumerate(ds.agents)}
    panel = load_panel(session)
    by_id = {a.id: a for a in session.scalars(select(Agent))}
    rows = np.array([r for r, aid in enumerate(panel.agent_ids.tolist())
                     if by_id[aid].code in code_index], dtype=np.int64)
    agents = [by_id[int(panel.agent_ids[r])] for r in rows]
    idx = [code_index[a.code] for a in agents]
    h0 = hour_index(HOLDOUT_START)
    if not agents or not _matches_db(session, ds, idx, agents, h0):
        log.warning("holdout backtest skipped: stored data does not match seed %d", settings.seed)
        return None
    starts = origins(h0, cfg)
    fc = Forecaster.load(settings.artifacts_dir, settings.forecast_conformal)
    fc.threads = 0  # all cores: row-parallel prediction, same numbers as one thread
    raw = predict(fc, panel, rows, starts, horizon)
    fl, span = ds.floats, slice(h0, N_HOURS)
    return Holdout(
        h0=h0, agents=agents, world=_world(session, ds, idx, agents, h0),
        forecasts={o - h0: v for o, v in raw.items()},
        served={t: panel.demand[t][rows] for t in TARGETS},
        balance={"cash": fl.cash[idx, span], "emoney": fl.emoney[idx, span]},
        unmet={"cash_out": fl.unmet_out[idx, span], "cash_in": fl.unmet_in[idx, span]})
