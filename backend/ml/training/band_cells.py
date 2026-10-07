"""Choose the band calibration cells per target on the validation period only (ML-5).

For each target and cell scheme (ml/inference/conformal.py SCHEMES), the offsets are cross-fitted
inside validation: fit on its first week and check on its second, then the other way round. The
check is the open-hour q10-q90 coverage per agent group (tier, region, urban/rural): its largest
distance from 0.80 (the "group gap"), averaged over the two folds. The tier-region-area scheme
is used only when its gap is strictly smaller; the served offsets are then fitted on the whole
validation period. The blind test is never read here.
"""

from typing import Any

import numpy as np

from ml.evaluation.forecast_eval import NOMINAL_COVERAGE
from ml.features.panel import AREA_CODE, REGIONS, TARGETS, Panel
from ml.inference.conformal import (
    CLOSED_BDT,
    SCHEMES,
    TAIL,
    TIER_AREA,
    TIER_REGION_AREA,
    Conformal,
    fit_target,
)
from ml.inference.forecaster import Forecaster
from ml.training.evaluate import holdout_grid
from ml.training.splits import Split

_AREA_NAME = {v: k.value for k, v in AREA_CODE.items()}


def group_labels(panel: Panel, rows: np.ndarray) -> dict[str, np.ndarray]:
    """Agent group per row: tier, region and urban/rural, as names."""
    out = {"tier": np.array([str(int(v)) for v in panel.tier[rows]]),
           "urban_rural": np.array([_AREA_NAME.get(int(v), "?") for v in panel.area[rows]])}
    if panel.region is not None:
        names = ("unknown", *REGIONS)
        out["region"] = np.array([names[int(v)] for v in panel.region[rows]])
    return out


def group_gap(y: np.ndarray, band: np.ndarray, labels: dict[str, np.ndarray]
              ) -> tuple[float, dict[str, dict[str, float]]]:
    """Largest |coverage - 0.80| over the groups, and the coverage of every group."""
    hit = (y >= band[:, 0]) & (y <= band[:, 2])
    worst, cov = 0.0, {}
    for name, lab in labels.items():
        cov[name] = {}
        for value in sorted(set(lab.tolist())):
            c = float(np.mean(hit[lab == value]))
            cov[name][str(value)] = round(c, 4)
            worst = max(worst, abs(c - NOMINAL_COVERAGE))
    return worst, cov


def _region(panel: Panel, rows: np.ndarray, scheme: str) -> np.ndarray | None:
    return panel.region[rows] if scheme == TIER_REGION_AREA and panel.region is not None else None


def cross_fit(target: str, scheme: str, y: np.ndarray, raw: np.ndarray, scale: np.ndarray,
              panel: Panel, rows: np.ndarray, hs: np.ndarray, first: np.ndarray
              ) -> dict[str, Any]:
    """Mean open-hour group gap over the two week-folds of validation."""
    folds = []
    for fit_m in (first, ~first):
        check = ~fit_m
        offs = fit_target(y[fit_m], raw[fit_m], scale[fit_m], panel.tier[rows][fit_m],
                          panel.area[rows][fit_m], hs[fit_m], TAIL,
                          None if (r := _region(panel, rows, scheme)) is None else r[fit_m])
        conf = Conformal(TAIL, {target: offs}, {target: scheme})
        band = conf.apply(target, raw[check], scale[check], panel.tier[rows][check],
                          panel.area[rows][check], hs[check],
                          None if r is None else r[check])
        open_ = raw[check][:, 2] >= CLOSED_BDT
        labels = {k: v[check][open_] for k, v in group_labels(panel, rows).items()}
        gap, cov = group_gap(y[check][open_], band[open_], labels)
        folds.append({"gap": round(gap, 4), "coverage": cov,
                      "open_coverage": round(float(np.mean(
                          (y[check][open_] >= band[open_, 0])
                          & (y[check][open_] <= band[open_, 2]))), 4)})
    return {"mean_gap": round(float(np.mean([f["gap"] for f in folds])), 4), "folds": folds}


def choose(fc: Forecaster, panel: Panel, split: Split) -> tuple[Conformal, dict[str, Any]]:
    """Calibration fitted on the whole validation period with the chosen scheme per target."""
    rows, origins, hs = holdout_grid(len(panel.agent_ids), split.train_end, split.val_end)
    t = origins + hs - 1
    split.check_validation(t)
    first = t < split.train_end + (split.val_end - split.train_end) // 2
    offsets: dict[str, dict[int, tuple[float, float]]] = {}
    schemes: dict[str, str] = {}
    report: dict[str, Any] = {}
    for target in TARGETS:
        y = panel.demand[target][rows, t]
        raw, scale = fc.raw_rows(panel, target, rows, origins, hs)
        tried = {s: cross_fit(target, s, y, raw, scale, panel, rows, hs, first)
                 for s in SCHEMES if s == TIER_AREA or panel.region is not None}
        best = TIER_AREA
        if TIER_REGION_AREA in tried and (tried[TIER_REGION_AREA]["mean_gap"]
                                          < tried[TIER_AREA]["mean_gap"]):
            best = TIER_REGION_AREA
        schemes[target] = best
        offsets[target] = fit_target(y, raw, scale, panel.tier[rows], panel.area[rows], hs,
                                     TAIL, _region(panel, rows, best))
        open_ = raw[:, 2] >= CLOSED_BDT
        zero = {name: {str(v): round(float(np.mean(y[open_][lab[open_] == v] == 0)), 4)
                       for v in sorted(set(lab[open_].tolist()))}
                for name, lab in group_labels(panel, rows).items()}
        report[target] = {"chosen": best, "cross_fit": tried,
                          "open_hour_zero_demand_share": zero}
    return Conformal(TAIL, offsets, schemes), {
        "rule": "tier-region-area only if its mean cross-fitted open-hour group gap (two "
                "validation weeks) is strictly smaller", "targets": report}
