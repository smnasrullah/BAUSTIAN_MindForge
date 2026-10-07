"""Stockout probability reliability against realised stockouts (synthetic holdout only).

At every planning round with a full `horizon_h` ahead, a projector gives P(stockout within the
horizon) and the median time to stockout per agent and float. Realised = the logged history
turned customers away (> STOCKOUT_MIN_BDT in an hour) within the horizon. The logged history
includes the agents' own refills and no AI action, so a no-refill projection is expected to
over-predict there (it is the conservative decision input, not a calibrated forecast of it).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.metrics import roc_auc_score

STOCKOUT_MIN_BDT = 0.5
FLOATS = ("cash", "emoney")
N_BINS = 10

# (agent row, world hour of the round, cash0, emoney0, out_q (H, 3), in_q (H, 3))
#   -> {"cash": (P within horizon, median hours | None), "emoney": (...)}
Projector = Callable[[int, int, float, float, np.ndarray, np.ndarray],
                     dict[str, tuple[float, float | None]]]


@dataclass
class Collected:
    p: dict[str, list[float]]
    real: dict[str, list[bool]]
    t_pred: dict[str, list[float | None]]
    t_real: dict[str, list[float | None]]


def collect(rounds: list[int], balance: dict[str, np.ndarray], unmet: dict[str, np.ndarray],
            forecasts: dict[int, dict[str, np.ndarray]], project: Projector,
            horizon_h: int) -> Collected:
    """balance / unmet: float -> (A, T) world hours; unmet keyed by float (cash <- cash_out).
    forecasts: world hour -> target -> (A, H, 3)."""
    c = Collected({f: [] for f in FLOATS}, {f: [] for f in FLOATS},
                  {f: [] for f in FLOATS}, {f: [] for f in FLOATS})
    n_agents = balance["cash"].shape[0]
    for o in rounds:
        fc = forecasts[o]
        for a in range(n_agents):
            res = project(a, o, float(balance["cash"][a, o]), float(balance["emoney"][a, o]),
                          fc["cash_out"][a, :horizon_h], fc["cash_in"][a, :horizon_h])
            for f in FLOATS:
                hit = unmet[f][a, o:o + horizon_h] > STOCKOUT_MIN_BDT
                p, t = res[f]
                c.p[f].append(p)
                c.real[f].append(bool(hit.any()))
                c.t_pred[f].append(t)
                c.t_real[f].append(float(np.argmax(hit)) + 0.5 if hit.any() else None)
    return c


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def reliability(p: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> list[dict[str, Any]]:
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            out.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(m.sum()),
                        "mean_p": _r(p[m].mean()), "observed": _r(y[m].mean())})
    return out


def summarise(p_list: list[float], real_list: list[bool], t_pred: list[float | None],
              t_real: list[float | None], cut: float) -> dict[str, Any]:
    p, y = np.array(p_list), np.array(real_list, dtype=float)
    flag = p >= cut
    tp = float((flag & (y == 1)).sum())
    base = float(y.mean()) if len(y) else 0.0
    brier = float(np.mean((p - y) ** 2)) if len(y) else None
    both = [(pr, tr) for pr, tr in zip(t_pred, t_real, strict=True) if tr is not None]
    found = [(pr, tr) for pr, tr in both if pr is not None]
    errs = [abs(pr - tr) for pr, tr in found]
    return {
        "cases": int(len(y)), "realised_rate": _r(base), "mean_p": _r(p.mean() if len(p) else 0),
        "brier": _r(brier),
        "auc": _r(roc_auc_score(y, p)) if 0 < base < 1 else None,
        "brier_skill_vs_base_rate": _r(1 - brier / (base * (1 - base))) if brier is not None
        and 0 < base < 1 else None,
        "recall_at_cut": _r(tp / y.sum()) if y.sum() else None,
        "precision_at_cut": _r(tp / flag.sum()) if flag.sum() else None,
        "cut": cut,
        "tts_events": len(both),
        "tts_with_prediction": len(found),
        "tts_mae_h": _r(np.mean(errs)) if errs else None,
        "tts_median_error_h": _r(np.median([a - b for a, b in found])) if found else None,
        "reliability": reliability(p, y),
    }


def report(c: Collected, cut: float) -> dict[str, Any]:
    out = {f: summarise(c.p[f], c.real[f], c.t_pred[f], c.t_real[f], cut) for f in FLOATS}
    out["both"] = summarise(c.p["cash"] + c.p["emoney"], c.real["cash"] + c.real["emoney"],
                            c.t_pred["cash"] + c.t_pred["emoney"],
                            c.t_real["cash"] + c.t_real["emoney"], cut)
    return out
