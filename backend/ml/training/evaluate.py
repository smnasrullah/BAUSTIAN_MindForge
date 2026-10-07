"""Backtest of one period (blind test: last 14 days; validation: the 14 days before) vs the
same-hour-last-week baseline. With a conformal calibration loaded, the served (calibrated) band
is scored and the raw band's coverage is reported beside it."""

from typing import Any

import numpy as np

from ml.features.build import MAX_HORIZON_H, WEEK_H
from ml.features.panel import TARGETS, Panel
from ml.inference.forecaster import Forecaster
from ml.registry import QUANTILES

ORIGIN_HOURS = (8, 20)  # forecasts issued every holdout day at 08:00 and 20:00 local
HORIZON_BUCKETS = ((1, 6), (7, 24), (25, 72))


def pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    diff = y - pred
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def holdout_grid(n_agents: int, holdout_start: int, n_hours: int
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origins = [d + h for d in range(holdout_start, n_hours, 24) for h in ORIGIN_HOURS]
    rows, o, hs = [], [], []
    for t0 in origins:
        horizon = min(MAX_HORIZON_H, n_hours - t0)
        rows.append(np.repeat(np.arange(n_agents), horizon))
        o.append(np.full(n_agents * horizon, t0))
        hs.append(np.tile(np.arange(1, horizon + 1), n_agents))
    return np.concatenate(rows), np.concatenate(o), np.concatenate(hs)


def _r(x: float) -> float:
    return round(float(x), 4)


def _baselines(y: np.ndarray, panel_y: np.ndarray, rows: np.ndarray, t: np.ndarray,
               holdout_start: int) -> dict[str, np.ndarray]:
    """Four reference forecasts for the target hours `t` (all use data strictly before t)."""
    lags = [panel_y[rows, t - k * WEEK_H] for k in (1, 2, 3, 4)]
    hist = panel_y[:, :holdout_start]
    how = np.arange(hist.shape[1]) % WEEK_H  # hour-of-week key (day_of_week x hour)
    profile = np.stack([hist[:, how == k].mean(axis=1) for k in range(WEEK_H)], axis=1)
    return {
        "last_week": lags[0],
        "mean_4w": np.mean(lags, axis=0),
        "yesterday": panel_y[rows, t - 24],
        "agent_profile": profile[rows, t % WEEK_H],
    }


def _target_metrics(y: np.ndarray, pred: np.ndarray, bases: dict[str, np.ndarray],
                    hs: np.ndarray) -> dict[str, Any]:
    base = bases["last_week"]
    mae, mae_b = np.mean(np.abs(y - pred[:, 1])), np.mean(np.abs(y - base))
    per_base = {k: {"mae_bdt": _r(np.mean(np.abs(y - b))),
                    "mae_skill": _r(1 - mae / np.mean(np.abs(y - b)))}
                for k, b in bases.items()}
    pin = {str(q): pinball(y, pred[:, i], q) for i, q in enumerate(QUANTILES)}
    pin_b = {str(q): pinball(y, base, q) for q in QUANTILES}
    by_h = {}
    for lo, hi in HORIZON_BUCKETS:
        m = (hs >= lo) & (hs <= hi)
        by_h[f"{lo}-{hi}"] = {"mae": _r(np.mean(np.abs(y[m] - pred[m, 1]))),
                              "mae_baseline": _r(np.mean(np.abs(y[m] - base[m])))}
    return {
        "rows": int(len(y)),
        "mean_demand_bdt": _r(np.mean(y)),
        "mae_bdt": _r(mae),
        "mae_baseline_bdt": _r(mae_b),
        "mae_skill": _r(1 - mae / mae_b),
        "pinball": {k: _r(v) for k, v in pin.items()} | {"mean": _r(np.mean(list(pin.values())))},
        "pinball_baseline": {k: _r(v) for k, v in pin_b.items()}
        | {"mean": _r(np.mean(list(pin_b.values())))},
        "pinball_q10": _r(pin["0.1"]),
        "pinball_q50": _r(pin["0.5"]),
        "pinball_q90": _r(pin["0.9"]),
        "coverage_q10": _r(np.mean(y <= pred[:, 0])),  # target 0.10
        "coverage_q90": _r(np.mean(y <= pred[:, 2])),  # target 0.90
        "coverage_in_band": _r(np.mean((y >= pred[:, 0]) & (y <= pred[:, 2]))),
        "coverage_q10_q90": _r(np.mean((y >= pred[:, 0]) & (y <= pred[:, 2]))),
        "baselines": per_base,
        "mae_by_horizon_h": by_h,
    }


def evaluate(fc: Forecaster, panel: Panel, holdout_start: int, n_hours: int) -> dict[str, Any]:
    rows, origins, hs = holdout_grid(len(panel.agent_ids), holdout_start, n_hours)
    t = origins + hs - 1
    out: dict[str, Any] = {"origins_local_hours": list(ORIGIN_HOURS),
                           "baseline": "same hour last week (y[t-168]) for every quantile",
                           "baselines": {"last_week": "y[t-168]",
                                         "mean_4w": "mean of y[t-168..t-672]",
                                         "yesterday": "y[t-24]",
                                         "agent_profile": "agent mean per (day_of_week, hour) "
                                                          "before the holdout"}}
    for target in TARGETS:
        y = panel.demand[target]
        raw, scale = fc.raw_rows(panel, target, rows, origins, hs)
        pred = fc.band(panel, target, rows, hs, raw, scale)
        bases = _baselines(y[rows, t], y, rows, t, holdout_start)
        out[target] = _target_metrics(y[rows, t], pred, bases, hs)
        if fc.conformal is not None:
            yt = y[rows, t]
            out[target]["coverage_q10_q90_raw"] = _r(np.mean((yt >= raw[:, 0])
                                                             & (yt <= raw[:, 2])))
        out[target]["coverage_by_group"] = _group_coverage(y[rows, t], pred, panel, rows)
    return out


def _group_coverage(y: np.ndarray, pred: np.ndarray, panel: Panel, rows: np.ndarray
                    ) -> dict[str, dict[str, float]]:
    """q10-q90 coverage by tier and by area (panel codes: 0 urban, 1 peri-urban, 2 rural)."""
    hit = (y >= pred[:, 0]) & (y <= pred[:, 2])
    out: dict[str, dict[str, float]] = {}
    groups = [("tier", panel.tier[rows]), ("area", panel.area[rows])]
    if panel.region is not None:
        groups.append(("region", panel.region[rows]))
    for name, codes in groups:
        out[name] = {str(int(c)): _r(np.mean(hit[codes == c])) for c in np.unique(codes)}
    return out
