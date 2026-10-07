"""Empirical hour-to-hour residual correlation and rho sensitivity of the stockout projection.

1. rho_hat: the Gaussian-copula correlation of consecutive hours, estimated on the VALIDATION
   period (forecast origins whose 24 h window ends before the blind test). Each realised hour
   is mapped through the served q10/q50/q90 quantile function to a probability (the inverse of
   stockout.demand_quantile), then to a normal score; rho_hat = Pearson correlation of the
   scores of hour h and h+1 inside one forecast, pooled. Longer lags are shown beside it: the
   model assumes one shared factor, so every pair of hours has correlation rho.
2. Sensitivity: the 24 h projection re-run with rho in RHOS (same seeds and paths otherwise);
   change in stockout probability and median time-to-stockout, and alert quality at the amber
   cut against the realised stockouts of the validation period.

Synthetic data only. Needs the seeded DB (as stockout_cut.py validation).

    python -m ml.training.rho_sensitivity [--max-agents N] [--paths N] [--out FILE]
"""

import argparse
import json
import sys
import time
from typing import Any

import numpy as np
from scipy.special import ndtri
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.models import Agent
from app.rules.risk_rules import HEADLINE_HORIZON, build_config
from app.services import holdout_inputs, impact
from ml.data_gen.dataset import build_dataset
from ml.evaluation.stockout_eval import STOCKOUT_MIN_BDT
from ml.features.panel import load_panel
from ml.inference.forecaster import Forecaster
from ml.inference.stockout import LEVELS, StockoutConfig, project
from ml.training.splits import FIXED_SPLIT

RHOS = (0.4, 0.6, 0.8)
BASE_RHO = 0.6
HORIZON_H = HEADLINE_HORIZON
LAGS = (1, 2, 3, 6, 12)
_SPAN = LEVELS[1] - LEVELS[0]


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def normal_scores(y: np.ndarray, q: np.ndarray) -> np.ndarray:
    """(.., H) realised demand and (.., H, 3) quantiles -> normal scores (NaN where the band
    is degenerate). Inverse of the two-piece linear quantile function used for sampling."""
    lo, mid, hi = q[..., 0], q[..., 1], q[..., 2]
    up = np.where(hi - mid > 1e-6, (y - mid) / np.maximum(hi - mid, 1e-6), 0.0)
    dn = np.where(mid - lo > 1e-6, (mid - y) / np.maximum(mid - lo, 1e-6), 0.0)
    u = np.where(y >= mid, LEVELS[1] + _SPAN * up, LEVELS[1] - _SPAN * dn)
    z = ndtri(np.clip(u, 0.001, 0.999))
    return np.where(hi - lo > 1e-6, z, np.nan)


def lag_corr(z: np.ndarray, lag: int) -> float | None:
    """Pooled Pearson correlation of scores `lag` hours apart. z: (N, H)."""
    a, b = z[:, :-lag].ravel(), z[:, lag:].ravel()
    ok = ~(np.isnan(a) | np.isnan(b))
    return float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 2 else None


def residual_correlation(scores: list[np.ndarray]) -> dict[str, Any]:
    z = np.concatenate(scores, axis=0)
    by_lag = {str(k): _r(lag_corr(z, k)) for k in LAGS if z.shape[1] > k}
    return {"rho_hat_lag1": by_lag.get("1"), "by_lag": by_lag,
            "hours_scored": int(np.sum(~np.isnan(z)))}


def summarise_rho(p: np.ndarray, t: np.ndarray, y: np.ndarray, cut: float,
                  base_p: np.ndarray, base_t: np.ndarray) -> dict[str, Any]:
    """p (N,) P(stockout in H); t (N,) median hours (NaN = none); y (N,) realised."""
    flag = p >= cut
    tp = float((flag & y).sum())
    both = ~np.isnan(t) & ~np.isnan(base_t)
    return {
        "mean_p": _r(p.mean()), "brier": _r(np.mean((p - y) ** 2)),
        "median_tts_h": _r(np.median(t[~np.isnan(t)])) if (~np.isnan(t)).any() else None,
        "share_with_tts": _r(np.mean(~np.isnan(t))),
        "alerts": int(flag.sum()),
        "recall": _r(tp / y.sum()) if y.sum() else None,
        "precision": _r(tp / flag.sum()) if flag.sum() else None,
        "mean_abs_dp_vs_base": _r(np.mean(np.abs(p - base_p))),
        "mean_dp_vs_base": _r(np.mean(p - base_p)),
        "median_dtts_h_vs_base": _r(np.median(t[both] - base_t[both])) if both.any() else None,
    }


def run(max_agents: int | None, n_paths: int) -> dict[str, Any]:
    settings = get_settings()
    split = FIXED_SPLIT
    with Session(get_engine()) as session:
        panel = load_panel(session)
        ds = build_dataset(settings.seed, len(panel.agent_ids))
        by_id = {a.id: a for a in session.scalars(select(Agent))}
    code_index = {a.code: i for i, a in enumerate(ds.agents)}
    rows = np.array([r for r, aid in enumerate(panel.agent_ids.tolist())
                     if by_id[aid].code in code_index], dtype=np.int64)
    if max_agents:
        rows = rows[:max_agents]
    agents = [by_id[int(panel.agent_ids[r])] for r in rows]
    idx = [code_index[a.code] for a in agents]
    h0, end = split.train_end, split.val_end
    cfg = impact.impact_config(settings)
    starts = [o for o in holdout_inputs.origins(h0, cfg, end) if o + HORIZON_H <= end]
    fc = Forecaster.load(settings.artifacts_dir, settings.forecast_conformal)
    fc.threads = 0
    raw = holdout_inputs.predict(fc, panel, rows, starts, HORIZON_H, end)

    scores: list[np.ndarray] = []
    for o in starts:
        for target in ("cash_out", "cash_in"):
            y = panel.demand[target][rows, o:o + HORIZON_H]
            scores.append(normal_scores(y, raw[o][target]))
    corr = residual_correlation(scores)

    fl = ds.floats
    balance = (fl.cash[idx, h0:end], fl.emoney[idx, h0:end])
    unmet = (fl.unmet_out[idx, h0:end], fl.unmet_in[idx, h0:end])
    t0 = time.perf_counter()
    p: dict[float, list[float]] = {r: [] for r in RHOS}
    tts: dict[float, list[float]] = {r: [] for r in RHOS}
    real: list[bool] = []
    for o in starts:
        w = o - h0
        out_q, in_q = raw[o]["cash_out"], raw[o]["cash_in"]
        for a, agent in enumerate(agents):
            for fi, (b, drain, inflow) in enumerate(((balance[0], out_q, in_q),
                                                     (balance[1], in_q, out_q))):
                real.append(bool((unmet[fi][a, w:w + HORIZON_H] > STOCKOUT_MIN_BDT).any()))
                for rho in RHOS:
                    res = project(float(b[a, w]), drain[a], inflow[a],
                                  StockoutConfig(n_paths=n_paths, rho=rho),
                                  np.random.default_rng([settings.seed, agent.id, fi, o]))
                    p[rho].append(res.prob_within(HORIZON_H))
                    tts[rho].append(np.nan if res.hours is None else res.hours)
    y = np.array(real)
    cut = build_config(settings.risk_thresholds).cuts[HORIZON_H].amber
    base_p, base_t = np.array(p[BASE_RHO]), np.array(tts[BASE_RHO])
    table = {str(r): summarise_rho(np.array(p[r]), np.array(tts[r]), y, cut, base_p, base_t)
             for r in RHOS}
    hat = corr["rho_hat_lag1"]
    lo_r, hi_r = min(RHOS), max(RHOS)
    return {
        "data": "synthetic", "period_h": [h0, end], "rounds": len(starts),
        "agents": len(agents), "n_paths": n_paths, "horizon_h": HORIZON_H, "cut": cut,
        "cases": int(len(y)), "realised_rate": _r(y.mean()),
        "empirical": corr, "seconds": round(time.perf_counter() - t0, 1),
        "by_rho": table,
        "reading": {
            "rho_hat_inside_grid": hat is not None and lo_r <= hat <= hi_r,
            "base_rho": BASE_RHO,
            "base_minus_rho_hat": None if hat is None else _r(BASE_RHO - hat),
            "recall_by_rho": {k: v["recall"] for k, v in table.items()},
            "brier_by_rho": {k: v["brier"] for k, v in table.items()},
            "max_mean_abs_dp_between_rhos": _r(max(
                v["mean_abs_dp_vs_base"] or 0.0 for v in table.values())),
        },
        "caveat": "served q50 was trained on targets including the validation period; the "
                  "logged history includes the agents' own refills (no-refill projection "
                  "over-predicts)",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-agents", type=int, default=None)
    ap.add_argument("--paths", type=int, default=500)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    res = run(args.max_agents, args.paths)
    e = res["empirical"]
    print(f"rho_hat (lag 1, validation) = {e['rho_hat_lag1']}; by lag {e['by_lag']}")
    print(f"{'rho':>5} {'mean_p':>7} {'brier':>6} {'med_tts_h':>9} {'recall':>6} {'prec':>6} "
          f"{'|dP|':>6} {'dTTS_h':>7}")
    for k, v in res["by_rho"].items():
        print(f"{k:>5} {v['mean_p']!s:>7} {v['brier']!s:>6} {v['median_tts_h']!s:>9} "
              f"{v['recall']!s:>6} {v['precision']!s:>6} {v['mean_abs_dp_vs_base']!s:>6} "
              f"{v['median_dtts_h_vs_base']!s:>7}")
    print(json.dumps(res["reading"]))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
