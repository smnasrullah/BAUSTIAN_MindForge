"""S3: a second anomaly detector for comparison only (Isolation Forest stays the served one).

Robust covariance: per peer group (same groups as the forests), a Minimum Covariance Determinant
fit (scikit-learn MinCovDet, seeded) on the same training windows (ending before the holdout);
score = robust Mahalanobis distance. Both detectors rank the blind test windows; precision at
k = share of injected-anomaly windows among the k highest scores (ambiguous windows left out),
plus recall at the Isolation Forest's own number of flags. Labels never touch fitting.
"""

from typing import Any

import numpy as np
from sklearn.covariance import MinCovDet

from ml.features.anomaly import GLOBAL_GROUP, FeatureSpec, Series
from ml.inference.anomaly import Detector
from ml.training import anomaly as anomaly_train
from ml.training.splits import FIXED_SPLIT, Split

KS = (10, 20, 30, 50, 100)
MIN_ROWS = 50


def fit_mcd(s: Series, seed: int, end_h: int, spec: FeatureSpec | None = None
            ) -> dict[str, MinCovDet]:
    x, rows, _ = anomaly_train.stack(s, anomaly_train.fit_ends(end_h), spec)
    groups = np.array(s.groups)[rows]
    out = {GLOBAL_GROUP: MinCovDet(random_state=seed).fit(x)}
    for g in sorted(set(s.groups) - {GLOBAL_GROUP}):
        m = groups == g
        if m.sum() >= MIN_ROWS:
            out[g] = MinCovDet(random_state=seed).fit(x[m])
    return out


def mcd_score(models: dict[str, MinCovDet], x: np.ndarray, groups: np.ndarray) -> np.ndarray:
    score = np.zeros(len(x))
    for g in np.unique(groups):
        m = groups == g
        score[m] = models.get(str(g), models[GLOBAL_GROUP]).mahalanobis(x[m])
    return score


def _at_k(score: np.ndarray, pos: np.ndarray, keep: np.ndarray, k: int) -> float | None:
    s, p = score[keep], pos[keep]
    if len(s) < k:
        return None
    top = np.argsort(-s, kind="stable")[:k]
    return round(float(p[top].mean()), 4)


def compare(s: Series, spans: anomaly_train.Spans, det: Detector, seed: int,
            split: Split = FIXED_SPLIT) -> dict[str, Any]:
    x, rows, end_of = anomaly_train.stack(s, anomaly_train.inside_ends(split.val_end,
                                                                      split.n_hours), det.spec)
    groups = np.array(s.groups)[rows]
    pos, keep, _ = anomaly_train.truth(s, spans, rows, end_of)
    if_score, thr = det.score(x, groups)
    flags = int(((if_score > thr) & keep).sum())
    mcd = mcd_score(fit_mcd(s, seed, split.val_end, det.spec), x, groups)
    out: dict[str, Any] = {"windows": int(keep.sum()), "positives": int(pos[keep].sum()),
                           "iforest_flags": flags}
    for name, score in (("isolation_forest", if_score), ("robust_covariance", mcd)):
        row: dict[str, Any] = {f"precision_at_{k}": _at_k(score, pos, keep, k) for k in KS}
        top = np.argsort(-np.where(keep, score, -np.inf), kind="stable")[:flags]
        hit = int(pos[top].sum())
        row["recall_at_iforest_flag_count"] = round(hit / max(1, int(pos[keep].sum())), 4)
        row["precision_at_iforest_flag_count"] = round(hit / flags, 4) if flags else None
        out[name] = row
    return out
