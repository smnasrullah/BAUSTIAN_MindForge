"""Forecast accuracy and q10-q90 band coverage, overall and per agent group.

`pred` is (n, 3) BDT [q10, q50, q90]; `labels` maps a grouping name (urban_rural, tier, region)
to one label per row. Nominal coverage of the q10-q90 band is 0.80.
"""

from typing import Any

import numpy as np

from ml.registry import QUANTILES
from ml.training.evaluate import pinball

NOMINAL_COVERAGE = QUANTILES[-1] - QUANTILES[0]


def _r(x: float) -> float:
    return round(float(x), 4)


def block(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    """MAE of q50, mean pinball over the three quantiles, coverage, tail misses, band width."""
    if len(y) == 0:
        return {"rows": 0}
    pin = [pinball(y, pred[:, i], q) for i, q in enumerate(QUANTILES)]
    return {
        "rows": int(len(y)),
        "mae_bdt": _r(np.mean(np.abs(y - pred[:, 1]))),
        "pinball_mean": _r(np.mean(pin)),
        "coverage_q10_q90": _r(np.mean((y >= pred[:, 0]) & (y <= pred[:, 2]))),
        "below_q10": _r(np.mean(y < pred[:, 0])),
        "above_q90": _r(np.mean(y > pred[:, 2])),
        "mean_width_bdt": _r(np.mean(pred[:, 2] - pred[:, 0])),
        # Exact-zero hours: any band starting at 0 covers them (they cap how low coverage gets).
        "zero_demand_share": _r(np.mean(y == 0)),
    }


def by_group(y: np.ndarray, pred: np.ndarray, labels: dict[str, np.ndarray]
             ) -> dict[str, Any]:
    """{"overall": block, "<grouping>": {"<label>": block}, "worst_group_gap": ...}."""
    out: dict[str, Any] = {"overall": block(y, pred)}
    worst = 0.0
    for name, lab in labels.items():
        part: dict[str, Any] = {}
        for value in sorted(set(lab.tolist())):
            m = lab == value
            part[str(value)] = block(y[m], pred[m])
            worst = max(worst, abs(part[str(value)]["coverage_q10_q90"] - NOMINAL_COVERAGE))
        out[name] = part
    out["max_group_coverage_gap"] = _r(worst)
    return out
