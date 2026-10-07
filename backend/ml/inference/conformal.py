"""Split-conformal calibration of the q10-q90 band (conformalized quantile regression, CQR;
Romano, Patterson & Candes 2019), one offset per tail, per Mondrian cell.

Fitted on the validation period only (the served model never trained on it). Scores are in
units of the agent's `scale` (trailing 7-day mean hourly demand), like the model target:
    lower  e_lo = (q10 - y) / scale        upper  e_hi = (y - q90) / scale
Each offset is the ceil((n + 1)(1 - TAIL))-th smallest score of its cell, so on exchangeable
data each tail misses at most TAIL and the band covers at least 1 - 2 * TAIL = 0.80 in every
cell. Calibrated: q10' = q10 - d_lo * scale, q90' = q90 + d_hi * scale, then clipped at 0 and
kept ordered around q50 (q10' <= q50 <= q90'); both steps can only widen the band, so the
guarantee is kept. A negative offset narrows an over-wide band.

Cells (decided from the prediction and the agent, never from y), one scheme per target:
- "tier-area": closed hours (raw q90 below CLOSED_BDT; mostly zero demand, whose tied zero
  scores would otherwise pin every offset at 0) x tier x area (panel codes) x horizon bucket. A
  cell with fewer than MIN_CELL validation rows uses its pooled offsets (same closed flag and
  bucket).
- "tier-region-area": the same plus the agent's region; a small cell falls back to its
  tier x area cell (any region), then to the pooled offsets.
Hours with exact zero demand are covered by any band that starts at 0, so in a cell where more
than TAIL of the hours are zero the band covers more than 0.80 and no valid offset can lower it.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

TAIL = 0.10
HORIZON_BUCKETS = ((1, 6), (7, 24), (25, 72))
MIN_CELL = 200
CLOSED_BDT = 1.0
POOLED_GROUP = 0  # group code of the pooled offsets (tier codes start at 1)
TIER_AREA = "tier-area"
TIER_REGION_AREA = "tier-region-area"
SCHEMES = (TIER_AREA, TIER_REGION_AREA)


def bucket_index(horizons: np.ndarray) -> np.ndarray:
    out = np.zeros(len(horizons), dtype=np.int64)
    for i, (lo, _) in enumerate(HORIZON_BUCKETS):
        out[horizons >= lo] = i
    return out


def cell_codes(tier: np.ndarray, area: np.ndarray, horizons: np.ndarray, high: np.ndarray
               ) -> np.ndarray:
    """Integer cell per row: closed * 1000 + tier * 100 + area * 10 + bucket. `high` = the
    raw (uncalibrated) q90 in BDT."""
    closed = (high < CLOSED_BDT).astype(np.int64)
    return (closed * 1000 + tier.astype(np.int64) * 100 + area.astype(np.int64) * 10
            + bucket_index(horizons))


def region_cell_codes(tier: np.ndarray, region: np.ndarray, area: np.ndarray,
                      horizons: np.ndarray, high: np.ndarray) -> np.ndarray:
    """closed * 10000 + tier * 1000 + region * 100 + area * 10 + bucket (region 0 = any)."""
    closed = (high < CLOSED_BDT).astype(np.int64)
    return (closed * 10000 + tier.astype(np.int64) * 1000 + region.astype(np.int64) * 100
            + area.astype(np.int64) * 10 + bucket_index(horizons))


def pooled_code(code: int) -> int:
    return (code // 1000) * 1000 + POOLED_GROUP * 10 + code % 10


def region_fallbacks(code: int) -> tuple[int, int, int]:
    """(cell, same cell in any region, pooled) of a tier-region-area code."""
    closed, bucket = code // 10000, code % 10
    any_region = code - (code // 100 % 10) * 100
    return code, any_region, closed * 10000 + bucket


def cell_name(code: int, scheme: str = TIER_AREA) -> str:
    if scheme == TIER_REGION_AREA:
        closed, rest = divmod(int(code), 10000)
        tier, rest = divmod(rest, 1000)
        region, rest = divmod(rest, 100)
        area, bucket = divmod(rest, 10)
        head = "all" if tier == 0 else f"t{tier}-r{region or 'any'}-a{area}"
    else:
        closed, rest = divmod(int(code), 1000)
        group, bucket = divmod(rest, 10)
        head = "all" if group == POOLED_GROUP else f"t{group // 10}-a{group % 10}"
    lo, hi = HORIZON_BUCKETS[bucket]
    return f"{'closed' if closed else 'open'}|{head}|h{lo}-{hi}"


def conformal_quantile(scores: np.ndarray, tail: float = TAIL) -> float:
    """The ceil((n + 1)(1 - tail))-th smallest score (the largest when n is too small)."""
    n = len(scores)
    if n == 0:
        return 0.0
    k = min(math.ceil((n + 1) * (1 - tail)), n)
    return float(np.partition(scores, k - 1)[k - 1])


@dataclass(frozen=True)
class Conformal:
    tail: float
    offsets: dict[str, dict[int, tuple[float, float]]]  # target -> cell code -> (d_lo, d_hi)
    schemes: dict[str, str] = field(default_factory=dict)  # target -> scheme (default tier-area)

    def scheme(self, target: str) -> str:
        return self.schemes.get(target, TIER_AREA)

    def _lookup(self, target: str, codes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        table = self.offsets[target]
        regional = self.scheme(target) == TIER_REGION_AREA
        lo, hi = np.zeros(len(codes)), np.zeros(len(codes))
        for code in np.unique(codes).tolist():
            chain = region_fallbacks(code) if regional else (code, pooled_code(code))
            pair = next((table[c] for c in chain if c in table), (0.0, 0.0))
            m = codes == code
            lo[m], hi[m] = pair
        return lo, hi

    def apply(self, target: str, pred: np.ndarray, scale: np.ndarray, tier: np.ndarray,
              area: np.ndarray, horizons: np.ndarray, region: np.ndarray | None = None
              ) -> np.ndarray:
        """(n, 3) raw BDT [low, mid, high] -> calibrated band, clipped at 0 and ordered."""
        if self.scheme(target) == TIER_REGION_AREA:
            if region is None:
                raise ValueError(f"{target} band cells need the agent's region")
            codes = region_cell_codes(tier, region, area, horizons, pred[:, 2])
        else:
            codes = cell_codes(tier, area, horizons, pred[:, 2])
        d_lo, d_hi = self._lookup(target, codes)
        mid = pred[:, 1]
        low = np.minimum(np.maximum(pred[:, 0] - d_lo * scale, 0.0), mid)
        high = np.maximum(pred[:, 2] + d_hi * scale, mid)
        return np.column_stack([low, mid, high])

    def to_json(self) -> dict[str, Any]:
        return {"method": "cqr-mondrian", "tail": self.tail,
                "cells": "closed (raw q90 < 1 BDT) x tier x [region x] area x horizon bucket",
                "min_cell": MIN_CELL,
                "schemes": dict(sorted(self.schemes.items())),  # absent target = tier-area
                # Full precision: the served offsets are exactly the evaluated ones.
                "offsets": {t: {str(k): [v[0], v[1]] for k, v in sorted(c.items())}
                            for t, c in self.offsets.items()},
                "names": {t: {str(k): cell_name(k, self.scheme(t)) for k in sorted(c)}
                          for t, c in self.offsets.items()}}

    @classmethod
    def from_json(cls, blob: dict[str, Any]) -> "Conformal":
        schemes = {str(t): str(s) for t, s in blob.get("schemes", {}).items()}
        if any(s not in SCHEMES for s in schemes.values()):
            raise ValueError(f"unknown band cell scheme: {schemes}")
        return cls(float(blob["tail"]),
                   {t: {int(k): (float(v[0]), float(v[1])) for k, v in c.items()}
                    for t, c in blob["offsets"].items()}, schemes)


def _offsets(codes: np.ndarray, e_lo: np.ndarray, e_hi: np.ndarray, tail: float,
             out: dict[int, tuple[float, float]], min_rows: int) -> None:
    for code in np.unique(codes).tolist():
        m = codes == code
        if m.sum() >= min_rows:
            out[code] = (conformal_quantile(e_lo[m], tail), conformal_quantile(e_hi[m], tail))


def fit_target(y: np.ndarray, pred: np.ndarray, scale: np.ndarray, tier: np.ndarray,
               area: np.ndarray, horizons: np.ndarray, tail: float = TAIL,
               region: np.ndarray | None = None) -> dict[int, tuple[float, float]]:
    """Offsets per cell (>= MIN_CELL rows) plus the fallbacks. With `region`, the cells are
    tier-region-area (fallbacks: tier-area in any region, then pooled); else tier-area."""
    e_lo = (pred[:, 0] - y) / scale
    e_hi = (y - pred[:, 2]) / scale
    out: dict[int, tuple[float, float]] = {}
    if region is None:
        codes = cell_codes(tier, area, horizons, pred[:, 2])
        _offsets((codes // 1000) * 1000 + POOLED_GROUP * 10 + codes % 10, e_lo, e_hi, tail,
                 out, 0)
        _offsets(codes, e_lo, e_hi, tail, out, MIN_CELL)
        return out
    codes = region_cell_codes(tier, region, area, horizons, pred[:, 2])
    _offsets((codes // 10000) * 10000 + codes % 10, e_lo, e_hi, tail, out, 0)
    _offsets(codes - (codes // 100 % 10) * 100, e_lo, e_hi, tail, out, MIN_CELL)
    known = region > 0  # an unknown region (code 0) uses its any-region cell
    _offsets(codes[known], e_lo[known], e_hi[known], tail, out, MIN_CELL)
    return out
