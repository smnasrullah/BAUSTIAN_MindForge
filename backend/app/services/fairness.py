"""Fairness by agent group (F12) on the 14 held-out days: does the AI serve every group equally?

At every planning round of the impact backtest with a full 24 h ahead (forecasts from the logged
history before the round only):
- forecast MAE of q50 vs logged served demand, hours 1..24, vs same hour last week;
- stockout recall: of the real stockouts (customers turned away in the logged history within
  24 h, per float), the share the 24 h risk level flagged amber/red at that round (Monte Carlo
  as in risk.py, fewer paths); precision alongside.
Groups: urban_rural, tier, region. Stored in system_meta["fairness_cache"].
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Agent, ModelVersion, SystemMeta
from app.models.enums import FLOAT_DEMAND, FloatType
from app.schemas.responsible_ai import (
    FairnessGap,
    FairnessGroup,
    FairnessReport,
    ForecastFairness,
    GroupBy,
    StockoutFairness,
)
from app.services.holdout_inputs import Holdout
from app.services.impact import STOCKOUT_MIN_BDT
from app.services.impact_policies import INFLOW_OF
from app.services.model_registry import active_model
from app.services.risk import FLOAT_INDEX, JOINT_STREAM, dependence_for
from ml.data_gen.timeline import BDT
from ml.features.build import WEEK_H
from ml.features.panel import TARGETS
from ml.inference.stockout import StockoutConfig, project
from ml.inference.stockout_joint import Dependence, load_dependence, project_joint
from ml.registry import FORECAST_MODEL

log = logging.getLogger(__name__)
CACHE_KEY = "fairness_cache"
HORIZON_H = 24
N_PATHS = 500
GROUP_OF: dict[GroupBy, Callable[[Agent], str]] = {
    GroupBy.urban_rural: lambda a: str(a.urban_rural),
    GroupBy.tier: lambda a: str(a.tier),
    GroupBy.region: lambda a: a.region,
}


@dataclass
class _Acc:
    """Per-agent sums over all rounds."""

    n: int
    err: dict[str, np.ndarray] = field(default_factory=dict)
    err_base: dict[str, np.ndarray] = field(default_factory=dict)
    demand: dict[str, np.ndarray] = field(default_factory=dict)
    hours: np.ndarray = field(init=False)
    events: np.ndarray = field(init=False)
    flagged: np.ndarray = field(init=False)
    caught: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        for d in (self.err, self.err_base, self.demand):
            d.update({t: np.zeros(self.n) for t in TARGETS})
        self.hours, self.events = np.zeros(self.n), np.zeros(self.n, dtype=np.int64)
        self.flagged, self.caught = np.zeros_like(self.events), np.zeros_like(self.events)


def _rounds(h: Holdout) -> list[int]:
    return sorted(o for o, fc in h.forecasts.items()
                  if fc[TARGETS[0]].shape[1] >= HORIZON_H and h.h0 + o >= WEEK_H)


def accumulate(h: Holdout, amber_cut: float, seed: int) -> _Acc:
    acc = _Acc(len(h.agents))
    cfg = StockoutConfig(n_paths=N_PATHS)
    table = load_dependence(get_settings().artifacts_dir)
    for o in _rounds(h):
        fc, t0 = h.forecasts[o], h.h0 + o
        for target in TARGETS:
            y = h.served[target][:, t0:t0 + HORIZON_H]
            base = h.served[target][:, t0 - WEEK_H:t0 - WEEK_H + HORIZON_H]
            acc.err[target] += np.abs(y - fc[target][:, :HORIZON_H, 1]).sum(axis=1)
            acc.err_base[target] += np.abs(y - base).sum(axis=1)
            acc.demand[target] += y.sum(axis=1)
        acc.hours += HORIZON_H
        probs = _probabilities(h, o, fc, cfg, seed, table)
        for ft in FloatType:
            unmet = h.unmet[FLOAT_DEMAND[ft].value][:, o:o + HORIZON_H]
            real = (unmet > STOCKOUT_MIN_BDT).any(axis=1)
            for a in range(len(h.agents)):
                flag = probs[ft][a] >= amber_cut
                acc.events[a] += int(real[a])
                acc.flagged[a] += int(flag)
                acc.caught[a] += int(flag and real[a])
    return acc


def _probabilities(h: Holdout, o: int, fc: dict[str, np.ndarray], cfg: StockoutConfig,
                   seed: int, table: dict[str, Dependence] | None
                   ) -> dict[FloatType, list[float]]:
    """P(stockout within HORIZON_H) per float and agent with the risk cache's method (no
    refill: the decision input)."""
    out: dict[FloatType, list[float]] = {ft: [] for ft in FloatType}
    joint = get_settings().stockout_method == "joint"
    for a, agent in enumerate(h.agents):
        if joint:
            rng = np.random.default_rng([seed, agent.id, JOINT_STREAM, o])
            res = project_joint(float(h.balance["cash"][a, o]), float(h.balance["emoney"][a, o]),
                                fc["cash_out"][a, :HORIZON_H], fc["cash_in"][a, :HORIZON_H],
                                cfg, dependence_for(table, agent), rng)
            out[FloatType.cash].append(res.cash.prob_within(HORIZON_H))
            out[FloatType.emoney].append(res.emoney.prob_within(HORIZON_H))
            continue
        for ft in FloatType:
            drain, inflow = fc[FLOAT_DEMAND[ft].value], fc[FLOAT_DEMAND[INFLOW_OF[ft]].value]
            rng = np.random.default_rng([seed, agent.id, FLOAT_INDEX[ft], o])
            out[ft].append(project(float(h.balance[ft.value][a, o]), drain[a, :HORIZON_H],
                                   inflow[a, :HORIZON_H], cfg, rng).prob_within(HORIZON_H))
    return out


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _group(name: str, m: np.ndarray, acc: _Acc) -> FairnessGroup:
    hours = float(acc.hours[m].sum())
    forecast = []
    for t in TARGETS:
        mae, mae_b = float(acc.err[t][m].sum()) / hours, float(acc.err_base[t][m].sum()) / hours
        mean = float(acc.demand[t][m].sum()) / hours
        forecast.append(ForecastFairness(
            target=t, mean_demand_bdt=round(mean, 2), mae_bdt=round(mae, 2),
            mae_baseline_bdt=round(mae_b, 2), nmae=round(mae / mean, 4) if mean else 0.0,
            skill=round(1 - mae / mae_b, 4) if mae_b else 0.0))
    ev, fl, ca = (int(x[m].sum()) for x in (acc.events, acc.flagged, acc.caught))
    return FairnessGroup(group=name, n_agents=int(m.sum()), forecast=forecast,
                         stockout=StockoutFairness(events=ev, flagged=fl, caught=ca,
                                                   recall=_ratio(ca, ev), precision=_ratio(ca, fl)))


def _gap(groups: list[FairnessGroup]) -> FairnessGap:
    nmae = {}
    for i, t in enumerate(TARGETS):
        vals = [g.forecast[i].nmae for g in groups]
        nmae[t] = round(max(vals) - min(vals), 4) if vals else 0.0
    recalls = [g.stockout.recall for g in groups if g.stockout.recall is not None]
    return FairnessGap(nmae=nmae, recall=round(max(recalls) - min(recalls), 4) if recalls
                       else None)


def report(h: Holdout, acc: _Acc) -> dict[str, Any]:
    by: dict[str, Any] = {}
    for gb, key in GROUP_OF.items():
        labels = np.array([key(a) for a in h.agents])
        groups = [_group(v, labels == v, acc) for v in sorted(set(labels.tolist()))]
        by[gb.value] = {"groups": [g.model_dump() for g in groups],
                        "gap": _gap(groups).model_dump()}
    overall = _group("all", np.ones(len(h.agents), dtype=bool), acc)
    return {"by": by, "overall": overall.model_dump()}


def store(session: Session, h: Holdout, mv: ModelVersion, amber_cut: float, seed: int,
          key: dict[str, Any]) -> int:
    rounds = _rounds(h)
    if not rounds:
        log.warning("fairness skipped: no planning round with %d h ahead", HORIZON_H)
        return 0
    result = report(h, accumulate(h, amber_cut, seed))
    hours = sorted({int(h.world.hod[o]) for o in rounds})
    first, last = (h.world.start + timedelta(hours=o) for o in (rounds[0], rounds[-1]))
    session.merge(SystemMeta(key=CACHE_KEY, value={
        "key": key, "model_version": mv.version, "generated_at": datetime.now(UTC).isoformat(),
        "method": {"start": first.astimezone(BDT).date().isoformat(),
                   "end": last.astimezone(BDT).date().isoformat(), "rounds_local_hours": hours,
                   "horizon_h": HORIZON_H, "amber_cut_24h": amber_cut, "n_paths": N_PATHS},
        **result}))
    log.info("fairness: %d rounds x %d agents", len(rounds), len(h.agents))
    return len(rounds)


def read(session: Session, group_by: GroupBy) -> FairnessReport | None:
    mv = active_model(session, FORECAST_MODEL)
    meta = session.get(SystemMeta, CACHE_KEY)
    if mv is None or meta is None or meta.value.get("model_version") != mv.version:
        return None
    v = meta.value
    part = v["by"][group_by.value]
    return FairnessReport(group_by=group_by, groups=part["groups"], overall=v["overall"],
                          gap=part["gap"], method=v["method"], model_version=mv.version,
                          generated_at=datetime.fromisoformat(v["generated_at"]))


def gaps(session: Session) -> dict[GroupBy, FairnessGap]:
    """Gap per grouping for the model card ({} before the backtest ran)."""
    out: dict[GroupBy, FairnessGap] = {}
    for gb in GroupBy:
        r = read(session, gb)
        if r is not None:
            out[gb] = r.gap
    return out
