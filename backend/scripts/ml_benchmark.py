"""ML benchmark on the FIXED clock (synthetic data only): one JSON with every number the ML upgrade
report compares (docs/ML_UPGRADE_RESULTS.md).

Run on the isolated verify stack (CLOCK_MODE=fixed, seeded), source mounted:
    python -m scripts.ml_benchmark --out /app/ml_bench.json [--artifacts DIR] [--skip impact]

Sections: forecast (blind holdout, overall + per group), stockout (reliability vs realised
stockouts on the holdout, per projector), impact + matching (holdout replay), anomaly (manifest).
"""

import argparse
import json
import logging
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.models import Agent, FloatSnapshot
from app.models.enums import UrbanRural
from app.rules.risk_rules import HEADLINE_HORIZON, build_config
from app.rules.swap_rules import FlowConfig
from app.services import holdout_inputs, impact, impact_realism, rebalance, risk
from app.services.impact_policies import AiPolicy, BaselinePolicy
from app.services.impact_sim import run
from ml.data_gen.dataset import build_dataset
from ml.data_gen.timeline import HOLDOUT_START, N_HOURS, hour_index
from ml.evaluation import forecast_eval, stockout_eval
from ml.features.anomaly import REFILL_MIN_BDT, Series, load_series
from ml.features.build import WEEK_H
from ml.features.panel import TARGETS, Panel, hour_of, load_panel
from ml.inference import refill
from ml.inference.anomaly import load_detector
from ml.inference.conformal import CLOSED_BDT
from ml.inference.forecaster import Forecaster
from ml.inference.stockout import StockoutConfig, project
from ml.inference.stockout_joint import Refill, load_dependence, run_paths, sample_joint
from ml.registry import ANOMALY_MANIFEST, read_manifest
from ml.training import anomaly as anomaly_train
from ml.training import anomaly_compare
from ml.training.evaluate import holdout_grid

log = logging.getLogger("ml_benchmark")
STOCKOUT_HORIZON_H = 24
STOCKOUT_PATHS = 500


def group_labels(session: Session, panel: Panel, rows: np.ndarray) -> dict[str, np.ndarray]:
    by_id = {a.id: a for a in session.scalars(select(Agent))}
    agents = [by_id[int(i)] for i in panel.agent_ids]
    area = np.array([UrbanRural(a.urban_rural).value for a in agents])
    tier = np.array([str(a.tier) for a in agents])
    region = np.array([a.region for a in agents])
    return {"urban_rural": area[rows], "tier": tier[rows], "region": region[rows]}


def forecast_section(session: Session, fc: Forecaster, panel: Panel) -> dict[str, Any]:
    """Served band (calibrated when the artifacts have it) and the raw band, all hours and
    open hours only (raw q90 >= CLOSED_BDT: closed hours are ~always covered at 0..0)."""
    h0 = hour_index(HOLDOUT_START)
    rows, origins, hs = holdout_grid(len(panel.agent_ids), h0, N_HOURS)
    t = origins + hs - 1
    labels = group_labels(session, panel, rows)
    out: dict[str, Any] = {"model_version": fc.model_version, "period": "blind holdout",
                           "calibrated": fc.conformal is not None}
    fc.threads = 4
    for target in TARGETS:
        y = panel.demand[target][rows, t]
        raw, scale = fc.raw_rows(panel, target, rows, origins, hs)
        pred = fc.band(panel, target, rows, hs, raw, scale)
        res = forecast_eval.by_group(y, pred, labels)
        base = panel.demand[target][rows, t - WEEK_H]
        res["overall"]["mae_baseline_bdt"] = round(float(np.mean(np.abs(y - base))), 4)
        res["baselines_mae_bdt"] = baselines(panel.demand[target], rows, t, y)
        is_open = raw[:, 2] >= CLOSED_BDT
        res["open_hours"] = forecast_eval.by_group(
            y[is_open], pred[is_open], {k: v[is_open] for k, v in labels.items()})
        res["open_hours"]["share_of_rows"] = round(float(is_open.mean()), 4)
        if fc.conformal is not None:
            res["raw_band"] = forecast_eval.by_group(y, raw, labels)
            res["raw_band_open_hours"] = forecast_eval.by_group(
                y[is_open], raw[is_open], {k: v[is_open] for k, v in labels.items()})
        out[target] = res
    return out


ETS_ALPHA = 0.3
ETS_WEEKS = 8


def baselines(demand: np.ndarray, rows: np.ndarray, t: np.ndarray, y: np.ndarray
              ) -> dict[str, float]:
    """S2 comparison baselines (every lag is a whole week back, so before the origin for
    horizons <= 72 h): same hour last week; mean of the same hour over 4 weeks; exponential
    smoothing (alpha ETS_ALPHA) over the same hour of the last ETS_WEEKS weeks."""
    lag = {k: demand[rows, t - k * WEEK_H] for k in range(1, ETS_WEEKS + 1)}
    level = lag[ETS_WEEKS]
    for k in range(ETS_WEEKS - 1, 0, -1):
        level = ETS_ALPHA * lag[k] + (1 - ETS_ALPHA) * level
    preds = {"same_hour_last_week": lag[1],
             "seasonal_naive_4w_mean": np.mean([lag[k] for k in range(1, 5)], axis=0),
             "exp_smoothing_weekly": level}
    return {k: round(float(np.mean(np.abs(y - v))), 4) for k, v in preds.items()}


def current_projector(seed: int, agent_ids: list[int]) -> stockout_eval.Projector:
    """The method risk.py uses today: each float alone, rho 0.6, no refill."""
    cfg = StockoutConfig(n_paths=STOCKOUT_PATHS)

    def f(a: int, o: int, cash0: float, em0: float, out_q: np.ndarray, in_q: np.ndarray
          ) -> dict[str, tuple[float, float | None]]:
        res = {}
        for fi, (name, b0, drain, inflow) in enumerate(
                (("cash", cash0, out_q, in_q), ("emoney", em0, in_q, out_q))):
            r = project(b0, drain, inflow, cfg, np.random.default_rng([seed, agent_ids[a], fi, o]))
            res[name] = (r.prob_within(len(out_q)), r.hours)
        return res
    return f


def joint_projector(seed: int, agents: list[Agent], h0: int, artifacts: Path, panel: Panel,
                    hist: dict[str, np.ndarray] | None, with_refill: bool
                    ) -> stockout_eval.Projector:
    """The joint method risk.py uses (estimated copula, coupled floats); with_refill adds the
    agent's refill habit from its history (hist) before each round. Rounds are hours after
    timeline hour h0."""
    cfg = StockoutConfig(n_paths=STOCKOUT_PATHS)
    table = load_dependence(artifacts)
    deps = [risk.dependence_for(table, a) for a in agents]
    cache: dict[int, list[Refill]] = {}

    def habits_at(o: int) -> list[Refill]:
        if hist is None:
            raise ValueError("the refill-aware view needs the history arrays")
        if o not in cache:
            t0 = h0 + o
            cache[o] = refill.habits(hist["cash"], hist["emoney"], hist["served_in"],
                                     hist["served_out"], panel.dow.astype(np.int64),
                                     panel.hour.astype(np.int64), t0, STOCKOUT_HORIZON_H)
        return cache[o]

    def f(a: int, o: int, cash0: float, em0: float, out_q: np.ndarray, in_q: np.ndarray
          ) -> dict[str, tuple[float, float | None]]:
        rng = np.random.default_rng([seed, agents[a].id, risk.JOINT_STREAM, o])
        d_out, d_in = sample_joint(out_q, in_q, deps[a], cfg.n_paths, rng)
        habit = habits_at(o)[a] if with_refill else None
        j = run_paths(cash0, em0, d_out, d_in, cfg, habit, rng if with_refill else None)
        return {"cash": (j.cash.prob_within(len(out_q)), j.cash.hours),
                "emoney": (j.emoney.prob_within(len(out_q)), j.emoney.hours)}
    return f


def history_arrays(session: Session, h: holdout_inputs.Holdout, panel: Panel,
                   rows: np.ndarray) -> dict[str, np.ndarray]:
    """Whole-timeline balances (top of hour) and served flows, in h.agents order."""
    row = {a.id: i for i, a in enumerate(h.agents)}
    cash = np.full((len(h.agents), N_HOURS), np.nan)
    em = np.full_like(cash, np.nan)
    for aid, ts, c, e in session.execute(select(
            FloatSnapshot.agent_id, FloatSnapshot.ts, FloatSnapshot.cash_balance,
            FloatSnapshot.emoney_balance)).tuples():
        t, r = hour_of(ts), row.get(aid)
        if r is not None and 0 <= t < N_HOURS:
            cash[r, t], em[r, t] = float(c), float(e)
    return {"cash": cash, "emoney": em, "served_in": panel.demand["cash_in"][rows],
            "served_out": panel.demand["cash_out"][rows]}


def stockout_rounds(h: holdout_inputs.Holdout) -> list[int]:
    return sorted(o for o, fc in h.forecasts.items()
                  if fc[TARGETS[0]].shape[1] >= STOCKOUT_HORIZON_H
                  and o + STOCKOUT_HORIZON_H <= h.world.n_hours)


def stockout_section(h: holdout_inputs.Holdout, projectors: dict[str, stockout_eval.Projector],
                     cut: float) -> dict[str, Any]:
    unmet = {"cash": h.unmet["cash_out"], "emoney": h.unmet["cash_in"]}
    rounds = stockout_rounds(h)
    out: dict[str, Any] = {"rounds": len(rounds), "horizon_h": STOCKOUT_HORIZON_H,
                           "n_paths": STOCKOUT_PATHS}
    for name, proj in projectors.items():
        t0 = time.perf_counter()
        c = stockout_eval.collect(rounds, h.balance, unmet, h.forecasts, proj, STOCKOUT_HORIZON_H)
        out[name] = stockout_eval.report(c, cut)
        out[name]["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def _outcome(w: Any, pol: Any) -> dict[str, Any]:
    cells = impact.tally(w, run(w, pol))
    actions: Counter[str] = Counter()
    for c in cells.values():
        actions.update(c.actions)
    return {"stockout_hours": sum(c.stockout_hours for c in cells.values()),
            "value_lost_bdt": round(sum(c.lost for c in cells.values()), 2),
            "van_trips": sum(len(c.trips) for c in cells.values()),
            "actions": dict(sorted(actions.items()))}


def _spied(policy: AiPolicy, rounds: list[dict[str, float]]) -> AiPolicy:
    """Record each planning round's matching result (same scenarios for every matcher)."""
    inner = policy._swaps

    def spy(orders: Any, surplus: Any, now: Any = None) -> Any:
        found = inner(orders, surplus, now)
        cash = [o for o in orders if o.float_type.value == "cash"]
        per_donor: Counter[int] = Counter(m.donor.agent_id for ms in found.values() for m in ms)
        rounds.append({
            "receivers": len(cash), "matched": len(found),
            "transfers": sum(len(ms) for ms in found.values()),
            "full_cover": sum(any(m.van_trip_saved for m in ms) for ms in found.values()),
            "km": sum(m.distance_km for ms in found.values() for m in ms),
            "bdt": sum(m.amount for ms in found.values() for m in ms),
            "need_bdt": sum(o.advice.amount for o in cash),
            "max_receivers_one_donor": max(per_donor.values(), default=0)})
        return found
    policy._swaps = spy  # type: ignore[method-assign]
    return policy


def _matching(rounds: list[dict[str, float]]) -> dict[str, Any]:
    keys = ("receivers", "matched", "transfers", "full_cover", "km", "bdt", "need_bdt")
    tot = {k: sum(r[k] for r in rounds) for k in keys}
    return {
        "rounds": len(rounds), **{k: round(v, 2) for k, v in tot.items()},
        "match_rate": round(tot["matched"] / tot["receivers"], 4) if tot["receivers"] else None,
        "full_cover_rate": round(tot["full_cover"] / tot["receivers"], 4)
        if tot["receivers"] else None,
        "need_covered_share": round(tot["bdt"] / tot["need_bdt"], 4) if tot["need_bdt"] else None,
        "km_per_transfer": round(tot["km"] / tot["transfers"], 3) if tot["transfers"] else None,
        "max_receivers_one_donor": max((r["max_receivers_one_donor"] for r in rounds), default=0)}


def impact_section(h: holdout_inputs.Holdout) -> dict[str, Any]:
    settings = get_settings()
    rcfg, scfg, ccfg = rebalance.configs(settings)
    cfg = impact.impact_config(settings)
    w = h.world
    out: dict[str, Any] = {"baseline": _outcome(w, BaselinePolicy(w, cfg, ccfg.topup_eta_h))}
    flow = FlowConfig(settings.swap_max_receivers_per_donor,
                      settings.swap_max_donors_per_receiver, ccfg.self_fetch_speed_kmh,
                      ccfg.travel_cost_per_km_bdt)
    for name, fcfg in (("ai", None), ("ai_flow_matching", flow)):
        rounds: list[dict[str, float]] = []
        t0 = time.perf_counter()
        pol = _spied(AiPolicy(w, h.forecasts, cfg, rcfg, scfg, ccfg, fcfg), rounds)
        out[name] = _outcome(w, pol) | {"matching": _matching(rounds),
                                        "seconds": round(time.perf_counter() - t0, 1)}
    out["value_saved_bdt"] = round(out["baseline"]["value_lost_bdt"]
                                   - out["ai"]["value_lost_bdt"], 2)
    out["matching"] = out["ai"]["matching"]
    out["realism"] = realism_section(h)
    return out


def realism_section(h: holdout_inputs.Holdout) -> dict[str, Any]:
    """S4: perfect delivery vs failures/delays, with the full action costs."""
    settings = get_settings()
    rcfg, scfg, ccfg = rebalance.configs(settings)
    cfg = impact.impact_config(settings)
    w = h.world
    costs = impact_realism.Costs(cfg.van_cost_per_trip_bdt, ccfg.urgent_manual_cost_bdt,
                                 ccfg.topup_fee_pct, ccfg.travel_cost_per_km_bdt)
    out: dict[str, Any] = {"assumptions": asdict(impact_realism.Realism()) | asdict(costs)}
    for label, real in (("perfect", None), ("imperfect", impact_realism.Realism(
            seed=settings.seed))):
        row: dict[str, Any] = {}
        for name, pol in (("baseline", BaselinePolicy(w, cfg, ccfg.topup_eta_h)),
                          ("ai", AiPolicy(w, h.forecasts, cfg, rcfg, scfg, ccfg))):
            o = run(w, pol if real is None else impact_realism.Unreliable(pol, real))
            row[name] = impact_realism.summary(w, o, impact.STOCKOUT_MIN_BDT) | {
                "cost": impact_realism.action_cost(w, o, costs)}
        b, a = row["baseline"], row["ai"]
        row["stockout_hours_avoided"] = b["stockout_hours"] - a["stockout_hours"]
        row["value_saved_bdt"] = round(b["value_lost_bdt"] - a["value_lost_bdt"], 2)
        row["extra_action_cost_bdt"] = round(a["cost"]["total_bdt"] - b["cost"]["total_bdt"], 2)
        out[label] = row
    p, i = out["perfect"], out["imperfect"]
    out["shrink"] = {
        "stockout_hours_avoided": _share(i["stockout_hours_avoided"], p["stockout_hours_avoided"]),
        "value_saved": _share(i["value_saved_bdt"], p["value_saved_bdt"])}
    return out


def _share(new: float, old: float) -> float | None:
    """Relative change of a headline (negative = it shrank)."""
    return round(new / old - 1, 4) if old else None


def refill_section(s: Series, seed: int) -> dict[str, Any]:
    """ML-6: refills found by each rule against the generator's own refill events (synthetic
    truth). A refill that leaves cash where the ledger puts it cannot be seen by any rule."""
    ds = build_dataset(seed, len(s.agent_ids))
    code_index = {a.code: i for i, a in enumerate(ds.agents)}
    rows = [r for r, c in enumerate(s.codes) if c in code_index]
    true = ds.floats.refill[[code_index[s.codes[r]] for r in rows], :]
    true[:, 0] = False  # the first hour has no previous snapshot for either rule
    if s.cash is None:
        raise ValueError("refill section needs the cash balances")
    ledger = refill.refill_mask(s.cash[rows], s.cash_in[rows], s.cash_out[rows])
    old = np.zeros_like(ledger)
    with np.errstate(invalid="ignore"):
        old[:, 1:] = np.abs(np.diff(s.total[rows], axis=1)) > REFILL_MIN_BDT

    def rule(found: np.ndarray) -> dict[str, Any]:
        tp = int((found & true).sum())
        return {"found": int(found.sum()), "true_found": tp,
                "recall": round(tp / max(1, int(true.sum())), 4),
                "precision": round(tp / max(1, int(found.sum())), 4)}

    return {"agents": len(rows), "true_refills": int(true.sum()), "ledger_rule": rule(ledger),
            "total_float_rule": rule(old)}


def anomaly_section(artifacts: Path) -> dict[str, Any]:
    m = read_manifest(artifacts, ANOMALY_MANIFEST) or {}
    a = m.get("anomaly", {})
    return {"model_version": m.get("model_version"), "contamination": a.get("contamination"),
            "features": a.get("features"), "burst_k": a.get("burst_k"),
            "metrics": a.get("metrics")}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[bench] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--artifacts", default=None)
    ap.add_argument("--skip", nargs="*", default=[])
    args = ap.parse_args()
    settings = get_settings()
    artifacts = Path(args.artifacts) if args.artifacts else settings.artifacts_dir
    result: dict[str, Any] = {"clock": "fixed", "data": "synthetic", "seed": settings.seed}
    timings: dict[str, float] = {}
    with Session(get_engine()) as session:
        t0 = time.perf_counter()
        panel = load_panel(session)
        fc = Forecaster.load(artifacts)
        timings["panel"] = time.perf_counter() - t0
        if "forecast" not in args.skip:
            t0 = time.perf_counter()
            result["forecast"] = forecast_section(session, fc, panel)
            timings["forecast"] = time.perf_counter() - t0
        need_holdout = {"stockout", "impact"} - set(args.skip)
        if need_holdout:
            t0 = time.perf_counter()
            cfg = impact.impact_config(settings)
            horizon = max(rebalance.configs(settings)[0].horizon_h, STOCKOUT_HORIZON_H)
            h = holdout_inputs.load(session, settings, cfg, horizon)
            timings["holdout_inputs"] = time.perf_counter() - t0
            if h is None:
                raise SystemExit("holdout inputs unavailable (is the DB the fixed seeded set?)")
            ids = [a.id for a in h.agents]
            if "stockout" not in args.skip:
                t0 = time.perf_counter()
                cut = build_config(settings.risk_thresholds).cuts[HEADLINE_HORIZON].amber
                projectors = {"independent_no_refill": current_projector(settings.seed, ids)}
                if load_dependence(artifacts) is not None:
                    rows = np.array([int(np.flatnonzero(panel.agent_ids == a.id)[0])
                                     for a in h.agents])
                    hist = history_arrays(session, h, panel, rows)
                    for name, ref in (("joint_no_refill", False), ("joint_refill_aware", True)):
                        projectors[name] = joint_projector(settings.seed, h.agents, h.h0,
                                                           artifacts, panel, hist, ref)
                result["stockout"] = stockout_section(h, projectors, cut)
                timings["stockout"] = time.perf_counter() - t0
            if "impact" not in args.skip:
                t0 = time.perf_counter()
                result["impact"] = impact_section(h)
                timings["impact"] = time.perf_counter() - t0
    result["anomaly"] = anomaly_section(artifacts)
    if "anomaly_compare" not in args.skip:
        t0 = time.perf_counter()
        with Session(get_engine()) as session:
            series = load_series(session)
            spans = anomaly_train.label_spans(anomaly_train._labels(session))
        result["anomaly"]["refills"] = refill_section(series, settings.seed)
        result["anomaly"]["compare_blind"] = anomaly_compare.compare(
            series, spans, load_detector(artifacts), settings.seed)
        timings["anomaly_compare"] = time.perf_counter() - t0
    result["timings_s"] = {k: round(v, 1) for k, v in timings.items()}
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
