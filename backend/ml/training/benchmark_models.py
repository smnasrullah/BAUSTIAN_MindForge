"""Model benchmark on one feature matrix: LightGBM vs XGBoost vs Random Forest (cash_out).

Identical rows, features (ml/features/build.py) and target (hourly cash_out demand / scale) for
all three. Fitted on a random subset of TRAIN rows only; scored on a subset of the VALIDATION
period (the blind test is not touched). Fixed hyper-parameters, no tuning, so the table compares
model families at equal effort, not tuned champions. Sized to run in under 3 minutes.

- LightGBM: native quantile objective, one booster per quantile (the served design).
- XGBoost: objective reg:quantileerror, one booster per quantile. Optional: xgboost is not in
  requirements.txt (fixed stack); without it the row is skipped. One-off:
  `docker compose run --rm backend sh -c "pip install xgboost && python -m ml.training.benchmark_models"`.
- Random Forest: ONE forest; quantiles are the empirical q10/q50/q90 of the per-tree
  predictions (an approximation of a quantile forest, not Meinshausen's leaf-sample version).

Latency = median of 7 runs predicting 1,000 rows (all three quantiles), ONE CPU thread,
features already built. Artifact size = the serialised models, joblib compress=3 like the repo.

    python -m ml.training.benchmark_models [--train-rows N] [--eval-rows N] [--rounds N]
        [--seed 42] [--out FILE.md]
"""

import argparse
import io
import sys
import time
from collections.abc import Callable
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy.orm import Session

from app.core.db import get_engine
from ml.features.build import CATEGORICAL, FEATURES, build
from ml.features.panel import load_panel
from ml.registry import QUANTILES
from ml.training.evaluate import holdout_grid, pinball
from ml.training.splits import FIXED_SPLIT
from ml.training.train import lgb_params, sample_rows

TARGET = "cash_out"
LATENCY_ROWS = 1000
LATENCY_RUNS = 7

Predict = Callable[[np.ndarray], np.ndarray]  # (n, F) -> (n, 3) scaled q10 / q50 / q90


def _lightgbm(x: np.ndarray, z: np.ndarray, rounds: int, seed: int
              ) -> tuple[Predict, Any]:
    data = lgb.Dataset(x, label=z, feature_name=list(FEATURES),
                       categorical_feature=list(CATEGORICAL), free_raw_data=False)
    boosters = [lgb.train(lgb_params(q, seed) | {"num_threads": 1}, data, num_boost_round=rounds)
                for q in QUANTILES]

    def predict(xx: np.ndarray) -> np.ndarray:
        return np.stack([b.predict(xx, num_threads=1) for b in boosters], axis=1)
    return predict, [b.model_to_string() for b in boosters]


def _xgboost(x: np.ndarray, z: np.ndarray, rounds: int, seed: int
             ) -> tuple[Predict, Any] | None:
    try:
        import xgboost as xgb
    except ImportError:
        return None
    models = [xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=q,
                               n_estimators=rounds, learning_rate=0.05, max_depth=6,
                               min_child_weight=100, tree_method="hist", n_jobs=1,
                               random_state=seed).fit(x, z) for q in QUANTILES]

    def predict(xx: np.ndarray) -> np.ndarray:
        return np.stack([m.predict(xx) for m in models], axis=1)
    return predict, [bytes(m.get_booster().save_raw("ubj")) for m in models]


def _forest(x: np.ndarray, z: np.ndarray, seed: int) -> tuple[Predict, Any]:
    rf = RandomForestRegressor(n_estimators=60, max_depth=14, min_samples_leaf=50,
                               max_features=0.5, n_jobs=4, random_state=seed).fit(x, z)

    def predict(xx: np.ndarray) -> np.ndarray:
        per_tree = np.stack([t.predict(xx) for t in rf.estimators_], axis=1)
        return np.quantile(per_tree, QUANTILES, axis=1).T
    return predict, rf


def size_mb(obj: Any) -> float:
    buf = io.BytesIO()
    joblib.dump(obj, buf, compress=3)
    return buf.getbuffer().nbytes / 1e6


def latency_ms(predict: Predict, x: np.ndarray) -> float:
    xs = x[:LATENCY_ROWS]
    predict(xs)  # warm-up
    runs = []
    for _ in range(LATENCY_RUNS):
        t0 = time.perf_counter()
        predict(xs)
        runs.append((time.perf_counter() - t0) * 1000)
    return float(np.median(runs))


def score(pred: np.ndarray, y: np.ndarray) -> dict[str, float]:
    pred = np.sort(np.maximum(pred, 0.0), axis=1)  # no quantile crossing, no negative demand
    return {
        "mae": float(np.mean(np.abs(y - pred[:, 1]))),
        "rmse": float(np.sqrt(np.mean((y - pred[:, 1]) ** 2))),
        "coverage": 100.0 * float(np.mean((y >= pred[:, 0]) & (y <= pred[:, 2]))),
        "pinball": float(np.mean([pinball(y, pred[:, i], q) for i, q in enumerate(QUANTILES)])),
    }


def table(results: dict[str, dict[str, float] | None]) -> str:
    head = ("| Model | MAE (BDT) | RMSE (BDT) | q10-q90 coverage (%) | Mean pinball | "
            "Latency / 1,000 preds (ms) | Artifact (MB) | Train (s) |\n"
            "|---|---:|---:|---:|---:|---:|---:|---:|")
    lines = [head]
    for name, r in results.items():
        if r is None:
            lines.append(f"| {name} | skipped (xgboost not installed) | | | | | | |")
            continue
        lines.append(f"| {name} | {r['mae']:.1f} | {r['rmse']:.1f} | {r['coverage']:.1f} | "
                     f"{r['pinball']:.2f} | {r['latency_ms']:.1f} | {r['size_mb']:.2f} | "
                     f"{r['train_s']:.1f} |")
    return "\n".join(lines)


def why_lightgbm(results: dict[str, dict[str, float] | None]) -> str:
    done = {k: v for k, v in results.items() if v is not None}
    rank = {m: sorted(done, key=lambda k: done[k][m]).index("LightGBM") + 1
            for m in ("mae", "pinball", "latency_ms", "size_mb")}
    lgbm = done["LightGBM"]
    measured = (f"Measured here (rank among {len(done)}, 1 = best): MAE #{rank['mae']}, "
                f"pinball #{rank['pinball']}, latency #{rank['latency_ms']} "
                f"({lgbm['latency_ms']:.1f} ms), artifact #{rank['size_mb']} "
                f"({lgbm['size_mb']:.2f} MB).")
    return "\n".join([
        "### Why LightGBM for CPU serving on MFS infrastructure", "", measured, "",
        "- Quantile loss is native, so q10/q50/q90 are trained directly; the forest has to "
        "derive quantiles from tree votes (slower, coarser tails).",
        "- Small artifacts and a single-thread predict that is fast enough for an agent-by-agent "
        "refresh on a modest CPU-only VM; no GPU or accelerator is assumed or needed.",
        "- Native categorical features (district, tier, area) without one-hot expansion.",
        "- Already the served model: TreeSHAP explanations, conformal calibration and the ML "
        "gate test are built on it, and it needs no extra dependency (XGBoost is not in the "
        "stack).",
        "- Deterministic training with a fixed seed, so judges reproduce the numbers offline.",
        "", "Caveat: untuned equal-effort comparison on a subsample of synthetic data; read the "
        "ranks above, not a claim of a margin."])


def run(train_rows: int, eval_rows: int, rounds: int, seed: int) -> str:
    with Session(get_engine()) as session:
        panel = load_panel(session)
    n, split = len(panel.agent_ids), FIXED_SPLIT
    rng = np.random.default_rng(seed)
    r, o, h = sample_rows(n, split.train_end, seed)
    pick = rng.choice(len(r), size=min(train_rows, len(r)), replace=False)
    r, o, h = r[pick], o[pick], h[pick]
    split.check_train(o + h - 1)
    x, scale = build(panel, TARGET, r, o, h)
    z = panel.demand[TARGET][r, o + h - 1] / scale
    vr, vo, vh = holdout_grid(n, split.train_end, split.val_end)
    split.check_validation(vo + vh - 1)
    pick = rng.choice(len(vr), size=min(eval_rows, len(vr)), replace=False)
    vr, vo, vh = vr[pick], vo[pick], vh[pick]
    xv, sv = build(panel, TARGET, vr, vo, vh)
    yv = panel.demand[TARGET][vr, vo + vh - 1]

    builders: dict[str, Callable[[], tuple[Predict, Any] | None]] = {
        "LightGBM": lambda: _lightgbm(x, z, rounds, seed),
        "XGBoost": lambda: _xgboost(x, z, rounds, seed),
        "Random Forest": lambda: _forest(x, z, seed),
    }
    results: dict[str, dict[str, float] | None] = {}
    for name, build_model in builders.items():
        t0 = time.perf_counter()
        built = build_model()
        if built is None:
            results[name] = None
            continue
        predict, artifact = built
        train_s = time.perf_counter() - t0
        res = score(predict(xv) * sv[:, None], yv)
        res |= {"latency_ms": latency_ms(predict, xv), "size_mb": size_mb(artifact),
                "train_s": train_s}
        results[name] = res
    header = (f"Benchmark: {TARGET}, {len(z):,} train rows, {len(yv):,} validation rows, "
              f"{rounds} rounds, seed {seed}, synthetic data.\n")
    return header + "\n" + table(results) + "\n\n" + why_lightgbm(results) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-rows", type=int, default=150_000)
    ap.add_argument("--eval-rows", type=int, default=40_000)
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    md = run(args.train_rows, args.eval_rows, args.rounds, args.seed)
    print(md)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
