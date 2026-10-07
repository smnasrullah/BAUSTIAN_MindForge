"""Copula dependence of forecast errors per agent segment, for the joint stockout simulation
(ml/inference/stockout_joint.py). Validation period only.

At every validation origin (08:00 and 20:00) and each of the next PATH_H hours, the realised
demand is mapped through the forecaster's own quantile function (probability integral transform,
the inverse of stockout.demand_quantile; a zero that the quantile function reaches is a random
draw below that point) and then to a normal score z. Per segment (tier x area):
- rho (per target): intraclass correlation of z inside a path (one-way ANOVA estimator), i.e.
  the share of an hour's shock common to the whole path;
- cross_hour: correlation of the cash-out and cash-in within-path deviations, same hour;
- cross_path: correlation of the two path effects (between-path covariance, ANOVA corrected).
Hours whose median forecast is below MIN_MID_BDT (closed hours) carry no information and are
skipped. Segments with fewer than MIN_PATHS usable paths use the pooled estimate.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import ndtri
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from ml.features.panel import Panel, load_panel
from ml.inference.forecaster import Forecaster
from ml.inference.stockout import LEVELS
from ml.inference.stockout_joint import Dependence, segment
from ml.registry import (
    DEPENDENCE_FILE,
    FORECAST_SEMVER,
    MANIFEST,
    read_manifest,
    sha256_file,
)
from ml.training.evaluate import holdout_grid
from ml.training.splits import FIXED_SPLIT, Split

PATH_H = 24
MIN_MID_BDT = 1.0
MIN_VALID_H = 6  # a path needs this many usable hours
MIN_PATHS = 100
CLIP_RHO = 0.95
CLIP_CROSS = 0.95
U_EPS = 1e-3


def pit(y: np.ndarray, q: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Probability level of y under the piecewise-linear quantile function of q (n, 3)."""
    lo, mid, hi = q[:, 0], q[:, 1], q[:, 2]
    span = LEVELS[1] - LEVELS[0]
    d_lo = np.maximum(mid - lo, 1e-9)
    d_hi = np.maximum(hi - mid, 1e-9)
    u = np.where(y < mid, LEVELS[1] - (mid - y) * span / d_lo,
                 LEVELS[1] + (y - mid) * span / d_hi)
    # P(demand = 0) = the level where the (linear-tailed) quantile function reaches 0.
    u0 = np.clip(LEVELS[1] - mid * span / d_lo, 0.0, 1.0)
    zero = (y <= 0) & (u0 > 0)
    u = np.where(zero, rng.random(len(y)) * u0, u)
    return np.clip(u, U_EPS, 1 - U_EPS)


def _anova(z: np.ndarray, ok: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Path means, deviations (0 where not ok), within variance, between variance."""
    n = ok.sum(axis=1)
    m = np.where(ok, z, 0.0).sum(axis=1) / n
    dev = np.where(ok, z - m[:, None], 0.0)
    s2w = float((dev ** 2).sum() / (n - 1).sum())
    s2b = float(np.var(m, ddof=1) - s2w * np.mean(1.0 / n))
    return m, dev, s2w, max(s2b, 0.0)


def estimate(z_out: np.ndarray, z_in: np.ndarray, ok: np.ndarray) -> tuple[Dependence, int]:
    """Dependence from (P, H) normal scores; ok marks hours usable for BOTH targets."""
    keep = ok.sum(axis=1) >= MIN_VALID_H
    z_out, z_in, ok = z_out[keep], z_in[keep], ok[keep]
    if len(z_out) < 3:
        return Dependence(), int(len(z_out))
    n = ok.sum(axis=1)
    m_o, d_o, w_o, b_o = _anova(z_out, ok)
    m_i, d_i, w_i, b_i = _anova(z_in, ok)
    rho_o = min(b_o / (b_o + w_o), CLIP_RHO) if b_o + w_o > 0 else 0.0
    rho_i = min(b_i / (b_i + w_i), CLIP_RHO) if b_i + w_i > 0 else 0.0
    cov_w = float((d_o * d_i).sum() / (n - 1).sum())
    cross_h = cov_w / np.sqrt(w_o * w_i) if w_o > 0 and w_i > 0 else 0.0
    cov_b = float(np.cov(m_o, m_i)[0, 1] - cov_w * np.mean(1.0 / n))
    cross_p = cov_b / np.sqrt(b_o * b_i) if b_o > 1e-6 and b_i > 1e-6 else 0.0
    return (Dependence(float(rho_o), float(rho_i), _clip(cross_p), _clip(cross_h)),
            int(len(z_out)))


def _clip(v: float) -> float:
    return float(np.clip(v, -CLIP_CROSS, CLIP_CROSS))


def segment_of(tier: np.ndarray, area: np.ndarray) -> np.ndarray:
    return np.array([segment(int(t), int(a)) for t, a in zip(tier, area, strict=True)])


def fit(fc: Forecaster, panel: Panel, split: Split, seed: int) -> dict[str, Any]:
    """{"segments": {segment: Dependence fields + n_paths}, "pooled": {...}} on validation."""
    n_agents = len(panel.agent_ids)
    rows, origins, hs = holdout_grid(n_agents, split.train_end, split.val_end)
    keep = hs <= PATH_H
    rows, origins, hs = rows[keep], origins[keep], hs[keep]
    split.check_validation(origins + hs - 1)
    rng = np.random.default_rng([seed, 7])
    z: dict[str, np.ndarray] = {}
    ok = np.ones(len(rows), dtype=bool)
    for target in ("cash_out", "cash_in"):
        q = fc.predict_rows(panel, target, rows, origins, hs)
        y = panel.demand[target][rows, origins + hs - 1]
        z[target] = ndtri(pit(y, q, rng))
        ok &= q[:, 1] >= MIN_MID_BDT
    # Paths: one (agent, origin), hours 1..PATH_H in order (holdout_grid is origin-major,
    # agent-major inside, horizon fastest).
    path_id = origins * n_agents + rows
    order = np.lexsort((hs, path_id))
    uniq, start = np.unique(path_id[order], return_index=True)
    full = np.diff(np.append(start, len(order))) == PATH_H
    idx = np.stack([order[s:s + PATH_H] for s, f in zip(start, full, strict=True) if f])
    seg = segment_of(panel.tier[rows[idx[:, 0]]], panel.area[rows[idx[:, 0]]])
    zo, zi, okp = z["cash_out"][idx], z["cash_in"][idx], ok[idx]
    pooled, n_pooled = estimate(zo, zi, okp)
    out: dict[str, Any] = {"path_h": PATH_H, "method": "gaussian copula, ANOVA ICC per segment",
                           "pooled": asdict(pooled) | {"n_paths": n_pooled}, "segments": {}}
    for s in sorted(set(seg.tolist())):
        m = seg == s
        dep, n_paths = estimate(zo[m], zi[m], okp[m])
        if n_paths < MIN_PATHS:
            dep = pooled
        out["segments"][s] = asdict(dep) | {"n_paths": n_paths}
    return out


def attach(artifacts_dir: Path, panel: Panel, split: Split, seed: int) -> dict[str, Any]:
    """Fit on the artifacts' served forecaster, write the table, list it in the manifest and
    re-derive the model version (sha of every listed file)."""
    fc = Forecaster.load(artifacts_dir)
    fc.threads = 4
    table = fit(fc, panel, split, seed)
    (artifacts_dir / DEPENDENCE_FILE).write_text(json.dumps(table, indent=1), encoding="utf-8")
    manifest = read_manifest(artifacts_dir)
    if manifest is None:
        raise RuntimeError("no forecast manifest to attach the dependence table to")
    files = dict(manifest["files"])
    files[DEPENDENCE_FILE] = sha256_file(artifacts_dir / DEPENDENCE_FILE)
    digest = hashlib.sha256("".join(files[k] for k in sorted(files)).encode()).hexdigest()
    manifest["files"] = files
    manifest["model_version"] = f"lgbq-{FORECAST_SEMVER}-{digest[:8]}"
    manifest["forecast"]["stockout_dependence"] = {"file": DEPENDENCE_FILE, "path_h": PATH_H,
                                                   "pooled": table["pooled"]}
    (artifacts_dir / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach the stockout dependence table")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=get_settings().seed)
    args = parser.parse_args()
    with Session(get_engine()) as session:
        panel = load_panel(session)
    table = attach(args.artifacts, panel, FIXED_SPLIT, args.seed)
    print(json.dumps(table, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
