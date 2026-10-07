"""Robustness of a plan: ETA ranges and the chance an agent runs out before the van arrives.

ETA range: driving time may run faster or slower than planned (VanConfig.eta_lo_factor /
eta_hi_factor); stop minutes are kept. Stockout chance: read from the forecast's P(stockout by
hour h) curve (StockoutPrediction.prob_by_hour, h = 0..72 from the forecast origin), at the
late end of the ETA range.
"""

from collections.abc import Sequence

from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import Route, VanConfig


def eta_range(r: Route, m: Matrix, cfg: VanConfig) -> list[tuple[float, float]]:
    """(earliest, latest) arrival per visit, hours after departure, in route order."""
    out: list[tuple[float, float]] = []
    drive = service = 0.0
    prev = 0
    for v in r.visits:
        node = v.stop + 1
        drive += m.minutes[prev][node]
        out.append(((drive * cfg.eta_lo_factor + service) / 60,
                    (drive * cfg.eta_hi_factor + service) / 60))
        service += cfg.minutes_per_stop
        prev = node
    return out


def p_at(curve: Sequence[float], h: float) -> float:
    """P(stockout by hour h) by linear interpolation; flat after the curve's last hour."""
    if not curve:
        raise ValueError("empty stockout curve")
    if h <= 0:
        return float(curve[0])
    k = int(h)
    if k >= len(curve) - 1:
        return float(curve[-1])
    return float(curve[k] + (curve[k + 1] - curve[k]) * (h - k))


def p_crossing(curve: Sequence[float], limit: float) -> float | None:
    """First hour at which P(stockout) reaches `limit` (interpolated); None if it never does."""
    for k, p in enumerate(curve):
        if p >= limit:
            if k == 0:
                return 0.0
            before = curve[k - 1]
            return k - 1 + (limit - before) / (p - before) if p > before else float(k)
    return None
