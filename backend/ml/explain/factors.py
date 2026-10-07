"""TreeSHAP of the median (q50) forecast, grouped into human factors and summed over a window.

LightGBM's `pred_contrib` is the exact TreeSHAP algorithm (same values as shap.TreeExplainer).
SHAP is additive, so per-hour contributions (model units x the agent's scale) add up to BDT over
the window: expected window demand = usual + sum of factor impacts.
"""

from dataclasses import dataclass

import numpy as np

from ml.features.build import FEATURES, build, grid
from ml.features.panel import Panel
from ml.inference.forecaster import Forecaster
from ml.registry import QUANTILES

EXPLAIN_WINDOW_H = 24
MEDIAN = QUANTILES.index(0.5)

FACTOR_OF: dict[str, str] = {
    "ev_salary": "salary", "ev_wage": "salary", "dom": "salary",  # salary days are fixed dates
    "ev_eid_day": "eid", "ev_holiday": "holiday", "ev_hat": "hat_bazar",
    "rain_mm": "rain", "ev_severe_weather": "rain", "temp_c": "temperature",
    "lag_168": "last_week", "lag_336": "last_week", "same_hour_4w": "last_week",
    "lag_day": "recent_demand", "roll_24": "recent_demand", "last_hour": "recent_demand",
    "hour": "time_of_day", "horizon_h": "time_of_day", "dow": "weekday",
    "tier": "agent_profile", "area": "agent_profile", "district": "agent_profile",
    "cash_cap_k": "agent_profile", "emoney_cap_k": "agent_profile", "log_scale": "agent_profile",
}
FACTORS: tuple[str, ...] = tuple(dict.fromkeys(FACTOR_OF[f] for f in FEATURES))
_GROUP = np.array([FACTORS.index(FACTOR_OF[f]) for f in FEATURES])


@dataclass(frozen=True)
class WindowShap:
    usual: np.ndarray  # (A,) BDT: model base value over the window (a "usual" window)
    impacts: np.ndarray  # (A, len(FACTORS)) BDT, signed


def window_shap(forecaster: Forecaster, panel: Panel, target: str, origin: int,
                window_h: int = EXPLAIN_WINDOW_H, num_threads: int = 1) -> WindowShap:
    """Every panel agent's next `window_h` hours of `target` demand, explained by factor.
    num_threads 0 = all cores (live ticks); each row's values do not depend on it."""
    n = len(panel.agent_ids)
    rows, origins, hs = grid(n, origin, window_h)
    x, scale = build(panel, target, rows, origins, hs)
    booster = forecaster.boosters[target][MEDIAN]
    contrib = np.asarray(booster.predict(x, pred_contrib=True, num_threads=num_threads))
    per_agent = (contrib * scale[:, None]).reshape(n, window_h, -1).sum(axis=1)
    impacts = np.zeros((n, len(FACTORS)))
    np.add.at(impacts.T, _GROUP, per_agent[:, :-1].T)
    return WindowShap(usual=per_agent[:, -1], impacts=impacts)
