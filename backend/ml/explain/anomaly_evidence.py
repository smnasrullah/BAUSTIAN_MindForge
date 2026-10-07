"""Peer evidence for one flagged agent window: where each feature sits in its peer group.

Stored as `anomalies.features`; the API and the LLM narrative only read it (numbers come from
here, never from the LLM).
"""

from typing import Any

import numpy as np

from ml.features.anomaly import HISTORY_H, WINDOW_H, Window

REASON_MIN_DEVIATION = 2.0  # model input (peer z); weaker deviations are not named as reasons
MAX_REASONS = 3
PERCENTILES = (10, 25, 50, 75, 90)


def _r(v: float, nd: int = 4) -> float:
    return round(float(v), nd)


def percentile_rank(values: np.ndarray, v: float) -> float:
    """Share of values below v (ties count half), 0..100."""
    below, equal = float((values < v).sum()), float((values == v).sum())
    return _r(100 * (below + 0.5 * equal) / len(values), 1)


def evidence(w: Window, score: np.ndarray, threshold: np.ndarray, groups: np.ndarray,
             i: int) -> dict[str, Any]:
    peers = groups == groups[i]
    features: list[dict[str, Any]] = []
    for j, name in enumerate(w.names):
        col = w.raw[peers, j]
        p = np.percentile(col, PERCENTILES)
        features.append({"name": name, "value": _r(w.raw[i, j]), "deviation": _r(w.x[i, j], 2),
                         "percentile": percentile_rank(col, w.raw[i, j]),
                         **{f"p{q}": _r(v) for q, v in zip(PERCENTILES, p, strict=True)}})
    ranked = sorted(features, key=lambda f: -abs(f["deviation"]))
    strong = [f for f in ranked if abs(f["deviation"]) >= REASON_MIN_DEVIATION]
    reasons = [{"feature": f["name"], "value": f["value"], "peer_median": f["p50"],
                "deviation": f["deviation"], "direction": "high" if f["deviation"] >= 0 else "low"}
               for f in (strong or ranked[:1])[:MAX_REASONS]]
    peer_scores = score[peers]
    return {
        "peer_group": str(groups[i]), "peer_count": int(peers.sum()),
        "window_h": WINDOW_H, "history_h": HISTORY_H,
        "score": _r(score[i]), "threshold": _r(threshold[i]),
        "peer_scores": {"p50": _r(np.median(peer_scores)),
                        "p90": _r(np.percentile(peer_scores, 90)),
                        "max": _r(peer_scores.max())},
        "features": features, "reasons": reasons,
        "context": {"cash_out_bdt": _r(w.cash_out_bdt[i], 0),
                    "cash_in_bdt": _r(w.cash_in_bdt[i], 0),
                    "baseline_cash_out_bdt": _r(w.baseline_cash_out_bdt[i], 0),
                    "refills": int(w.refills[i])},
    }
