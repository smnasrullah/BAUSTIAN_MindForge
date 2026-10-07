"""Train the LightGBM quantile demand forecaster (q10/q50/q90 x cash_out/cash_in).

Direct multi-horizon: one model per target and quantile, horizon 1..72 h is a feature.
Honest evaluation (ml/training/splits.py):
1. fit candidates on TRAIN targets only (before the validation period);
2. choose, per target and quantile, the number of leaves and boosting rounds by pinball loss on
   the VALIDATION period (14 days before the holdout); the served booster is that candidate,
   never refitted on validation, so the validation residuals stay out-of-sample;
3. fit the conformal q10-q90 offsets on the same validation predictions (ml/inference/conformal);
4. score the BLIND TEST (last 14 days) once, after every choice above is fixed.

    python -m ml.training.train [--seed 42] [--rounds 300]   (reads DATABASE_URL)
"""

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import DATA_VERSION, get_settings
from app.core.db import get_engine
from ml.data_gen.timeline import HOLDOUT_START, VAL_START
from ml.features.build import CATEGORICAL, FEATURES, MAX_HORIZON_H, MIN_HISTORY_H, build
from ml.features.panel import TARGETS, Panel, load_panel
from ml.inference.conformal import TAIL, Conformal
from ml.inference.forecaster import Forecaster
from ml.registry import (
    CONFORMAL_FILE,
    FORECAST_MODEL,
    FORECAST_SEMVER,
    MANIFEST,
    QUANTILES,
    forecast_file,
    read_manifest,
    sha256_file,
)
from ml.training import band_cells, dependence
from ml.training.evaluate import evaluate, holdout_grid, pinball
from ml.training.splits import FIXED_SPLIT, Split

log = logging.getLogger(__name__)
ORIGINS_PER_DAY = 2
HORIZONS_PER_ORIGIN = 12
ROUNDS = 300
CANDIDATE_LEAVES = (31, 63)
# Serving budget: the q50 booster is the one TreeSHAP explains on every live tick (60 s budget,
# docs/DECISIONS.md ML2). Its leaves x rounds may not exceed the 1.0 model's (31 x 300); q50 is
# still chosen by validation pinball inside that cap. q10 / q90 have no cap.
EXPLAINED_QUANTILE = 0.5
EXPLAIN_BUDGET_LEAF_ROUNDS = 31 * 300
TRAIN_THREADS = 4


def lgb_params(q: float, seed: int, num_leaves: int = 31) -> dict[str, Any]:
    return {
        "objective": "quantile", "alpha": q, "learning_rate": 0.05, "num_leaves": num_leaves,
        "min_data_in_leaf": 100, "feature_fraction": 0.9, "lambda_l2": 1.0,
        "deterministic": True, "force_row_wise": True, "num_threads": 4, "seed": seed,
        "verbose": -1,
    }


def checkpoints(rounds: int) -> tuple[int, ...]:
    """Boosting rounds tried on validation: half, 1x, 1.5x and 2x the nominal rounds."""
    return tuple(sorted({max(1, rounds // 2), rounds, rounds + rounds // 2, 2 * rounds}))


def sample_rows(n_agents: int, end_h: int, seed: int
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Random (agent, origin, horizon) triples whose target hour is before `end_h`."""
    rng = np.random.default_rng(seed)
    days = np.arange(MIN_HISTORY_H // 24, end_h // 24)
    n_orig = n_agents * len(days) * ORIGINS_PER_DAY
    agents = np.repeat(np.arange(n_agents), len(days) * ORIGINS_PER_DAY)
    t0 = np.tile(np.repeat(days, ORIGINS_PER_DAY), n_agents) * 24 + rng.integers(0, 24, n_orig)
    rows = np.repeat(agents, HORIZONS_PER_ORIGIN)
    origins = np.repeat(t0, HORIZONS_PER_ORIGIN)
    hs = rng.integers(1, MAX_HORIZON_H + 1, n_orig * HORIZONS_PER_ORIGIN)
    keep = origins + hs - 1 < end_h
    return rows[keep], origins[keep], hs[keep]


@dataclass
class Choice:
    num_leaves: int
    rounds: int
    val_pinball: float
    model: str


def _select(data: lgb.Dataset, xv: np.ndarray, sv: np.ndarray, yv: np.ndarray, q: float,
            seed: int, rounds: int, leaves: tuple[int, ...] = CANDIDATE_LEAVES
            ) -> tuple[Choice, list[dict[str, Any]]]:
    """Best (leaves, rounds) for one quantile by validation pinball; the trial table."""
    best: Choice | None = None
    trials: list[dict[str, Any]] = []
    for n_leaves in leaves:
        cps = checkpoints(rounds)
        if q == EXPLAINED_QUANTILE:
            cps = tuple(cp for cp in cps if n_leaves * cp <= EXPLAIN_BUDGET_LEAF_ROUNDS)
        if not cps:
            continue
        booster = lgb.train(lgb_params(q, seed, n_leaves), data, num_boost_round=max(cps))
        for cp in cps:
            pv = np.maximum(booster.predict(xv, num_iteration=cp, num_threads=4), 0.0) * sv
            loss = pinball(yv, pv, q)
            trials.append({"num_leaves": n_leaves, "rounds": cp, "val_pinball": round(loss, 4)})
            if best is None or loss < best.val_pinball - 1e-9:
                best = Choice(n_leaves, cp, loss, booster.model_to_string(num_iteration=cp))
    assert best is not None
    return best, trials


def fit(panel: Panel, seed: int, rounds: int, split: Split,
        on_step: Callable[[str], None] | None = None,
        leaves: tuple[int, ...] = CANDIDATE_LEAVES
        ) -> tuple[dict[str, list[str]], dict[str, Any], int]:
    """Selected booster strings per target (QUANTILES order), the selection report, rows."""
    n = len(panel.agent_ids)
    rows, origins, hs = sample_rows(n, split.train_end, seed)
    split.check_train(origins + hs - 1)
    vrows, vorig, vhs = holdout_grid(n, split.train_end, split.val_end)
    split.check_validation(vorig + vhs - 1)
    models: dict[str, list[str]] = {}
    report: dict[str, Any] = {}
    for target in TARGETS:
        x, scale = build(panel, target, rows, origins, hs)
        z = panel.demand[target][rows, origins + hs - 1] / scale
        data = lgb.Dataset(x, label=z, feature_name=list(FEATURES),
                           categorical_feature=list(CATEGORICAL), free_raw_data=False)
        xv, sv = build(panel, target, vrows, vorig, vhs)
        yv = panel.demand[target][vrows, vorig + vhs - 1]
        models[target], report[target] = [], {}
        for q in QUANTILES:
            choice, trials = _select(data, xv, sv, yv, q, seed, rounds, leaves)
            models[target].append(choice.model)
            report[target][str(q)] = {"num_leaves": choice.num_leaves, "rounds": choice.rounds,
                                      "val_pinball": round(choice.val_pinball, 4),
                                      "trials": trials}
            log.info("selected %s q=%.1f: leaves %d, rounds %d (val pinball %.1f) on %d rows",
                     target, q, choice.num_leaves, choice.rounds, choice.val_pinball, len(z))
            if on_step is not None:
                on_step(f"fit:{target}:q{q}")
    return models, report, len(rows)


def calibrate(fc: Forecaster, panel: Panel, split: Split) -> tuple[Conformal, dict[str, Any]]:
    """Conformal offsets from the validation predictions of the selected boosters; the cell
    scheme per target is chosen on validation too (ml/training/band_cells.py)."""
    return band_cells.choose(fc, panel, split)


def _write(artifacts_dir: Path, models: dict[str, list[str]], conformal: Conformal
           ) -> dict[str, str]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for target, strings in models.items():
        name = forecast_file(target)
        joblib.dump({str(q): s for q, s in zip(QUANTILES, strings, strict=True)},
                    artifacts_dir / name, compress=3)
        files[name] = sha256_file(artifacts_dir / name)
    (artifacts_dir / CONFORMAL_FILE).write_text(json.dumps(conformal.to_json(), indent=1),
                                                encoding="utf-8")
    files[CONFORMAL_FILE] = sha256_file(artifacts_dir / CONFORMAL_FILE)
    return files


def run(artifacts_dir: Path, seed: int, rounds: int = ROUNDS,
        on_step: Callable[[str], None] | None = None, split: Split = FIXED_SPLIT,
        leaves: tuple[int, ...] = CANDIDATE_LEAVES) -> dict[str, Any]:
    """`on_step` (admin retrain progress) hears "panel", "fit:<target>:q<q>", "evaluate".
    `leaves`: candidate leaf counts (tests pass one to stay fast)."""
    with Session(get_engine()) as session:
        panel = load_panel(session)
    if on_step is not None:
        on_step("panel")
    models, selection, n_rows = fit(panel, seed, rounds, split, on_step, leaves)
    if on_step is not None:
        on_step("evaluate")
    return finish(artifacts_dir, panel, models, selection, n_rows, seed, rounds, split)


def finish(artifacts_dir: Path, panel: Panel, models: dict[str, list[str]],
           selection: dict[str, Any], n_rows: int, seed: int, rounds: int, split: Split
           ) -> dict[str, Any]:
    """Calibrate on validation, score validation and the blind test, write the artifacts."""
    boosters = {t: [lgb.Booster(model_str=s) for s in models[t]] for t in TARGETS}
    raw = Forecaster(FORECAST_MODEL, "candidate", boosters, threads=TRAIN_THREADS)
    conformal, cells = calibrate(raw, panel, split)
    validation = evaluate(raw, panel, split.train_end, split.val_end)
    # The blind test, scored once with every choice fixed (served = calibrated bands).
    calibrated = Forecaster(FORECAST_MODEL, "candidate", boosters, conformal, TRAIN_THREADS)
    metrics = evaluate(calibrated, panel, split.val_end, split.n_hours)
    files = _write(artifacts_dir, models, conformal)
    digest = hashlib.sha256("".join(files[k] for k in sorted(files)).encode()).hexdigest()
    manifest: dict[str, Any] = {
        "model_version": f"lgbq-{FORECAST_SEMVER}-{digest[:8]}",
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed,
        "data_version": DATA_VERSION,
        "files": files,
        "forecast": {
            "model_name": FORECAST_MODEL, "targets": list(TARGETS), "quantiles": list(QUANTILES),
            "max_horizon_h": MAX_HORIZON_H, "features": list(FEATURES), "rounds": rounds,
            "params": lgb_params(0.5, seed) | {"alpha": "per quantile",
                                               "num_leaves": "selected per quantile"},
            "train_rows": n_rows, "train_targets_before": VAL_START.isoformat(),
            "validation": {"start": VAL_START.isoformat(), "end": HOLDOUT_START.isoformat(),
                           "used_for": ["num_leaves", "rounds", "conformal offsets"]},
            "split": split.as_dict(),
            "selection": selection,
            "conformal": {"file": CONFORMAL_FILE, "tail": TAIL, "nominal_coverage": 1 - 2 * TAIL,
                          "cells": cells},
            "validation_metrics": validation,
            "holdout_metrics": metrics,
        },
    }
    (artifacts_dir / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Joint stockout copula from the served (calibrated) forecaster's validation residuals.
    dependence.attach(artifacts_dir, panel, split, seed)
    manifest = read_manifest(artifacts_dir) or manifest
    log.info("wrote %s (%s)", MANIFEST, manifest["model_version"])
    return manifest


def recalibrate(artifacts_dir: Path, seed: int, split: Split = FIXED_SPLIT) -> dict[str, Any]:
    """Keep the selected boosters of an existing candidate; redo calibration, scoring, files."""
    old = read_manifest(artifacts_dir)
    if old is None:
        raise RuntimeError("no manifest to recalibrate")
    models = {t: [joblib.load(artifacts_dir / forecast_file(t))[str(q)] for q in QUANTILES]
              for t in TARGETS}
    with Session(get_engine()) as session:
        panel = load_panel(session)
    f = old["forecast"]
    return finish(artifacts_dir, panel, models, f["selection"], int(f["train_rows"]), seed,
                  int(f["rounds"]), split)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[train] %(message)s")
    parser = argparse.ArgumentParser(description="Train the quantile demand forecaster")
    parser.add_argument("--seed", type=int, default=get_settings().seed)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--out", type=Path, default=None, help="artifacts dir (default: settings)")
    parser.add_argument("--recalibrate", action="store_true",
                        help="keep the boosters in --out; redo calibration and scoring")
    args = parser.parse_args()
    out = args.out or get_settings().artifacts_dir
    manifest = (recalibrate(out, args.seed) if args.recalibrate
                else run(out, args.seed, args.rounds))
    print(json.dumps(manifest["forecast"]["holdout_metrics"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
