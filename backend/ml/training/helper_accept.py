"""Train and evaluate the helper acceptance model on SIMULATED helper behaviour.

1. Build the simulated help-request world from the seeded dataset (ml/data_gen/helpers.py) and
   log the asks of every request before the holdout under an exploring policy.
2. Fit a logistic regression on the TRAIN asks; fit a Platt recalibration on the VALIDATION
   asks; report AUC, Brier and reliability on validation and on the blind test asks.
3. Policy simulation on the BLIND test requests, all starting from the same history and with the
   same random answers: distance only, the current rule score, learned order, learned order +
   learned wave size. Acceptance rate, asks until covered, time to cover, fairness.

Everything is learned from and evaluated on simulated behaviour; real data is needed before any
claim. The model only orders and sizes waves inside the rule-feasible helper set.

    python -m ml.training.helper_accept [--seed 42] [--out DIR]
"""

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from app.core.config import DATA_VERSION, get_settings
from app.rules.help_trigger_rules import (
    ASK_PENALTY_KM,
    RESPONSE_WEIGHT_KM,
    learned_wave_size,
    response_rate,
)
from ml.data_gen import helpers as sim
from ml.data_gen.dataset import N_AGENTS, build_dataset
from ml.evaluation.stockout_eval import reliability
from ml.inference.helper_accept import FEATURES, AcceptModel
from ml.registry import HELPER_FILE, HELPER_MANIFEST, HELPER_MODEL, HELPER_SEMVER, sha256_file
from ml.training.splits import FIXED_SPLIT, Split

log = logging.getLogger(__name__)
C_REG = 1.0
WAVE_TARGET = 0.9  # learned wave size: P(at least one yes) to reach
OVER_ASKED_PER_WEEK = 10  # fairness check: asks of one helper in any 7 days above this


def _xy(rows: list[dict[str, float]]) -> tuple[np.ndarray, np.ndarray]:
    return (np.array([[r[f] for f in FEATURES] for r in rows]), np.array([r["y"] for r in rows]))


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def fit(train: list[dict[str, float]], val: list[dict[str, float]], version: str
        ) -> AcceptModel:
    x, y = _xy(train)
    mean, scale = x.mean(axis=0), np.where(x.std(axis=0) > 0, x.std(axis=0), 1.0)
    lr = LogisticRegression(C=C_REG, max_iter=2000).fit((x - mean) / scale, y)
    raw = AcceptModel(version, FEATURES, mean, scale, lr.coef_[0], float(lr.intercept_[0]))
    xv, yv = _xy(val)
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(raw.logit(xv)[:, None], yv)
    return AcceptModel(version, FEATURES, mean, scale, lr.coef_[0], float(lr.intercept_[0]),
                       float(platt.coef_[0, 0]), float(platt.intercept_[0]))


def scores(model: AcceptModel, rows: list[dict[str, float]], raw: bool = False
           ) -> dict[str, Any]:
    x, y = _xy(rows)
    p = 1 / (1 + np.exp(-model.logit(x))) if raw else model.predict(x)
    true = np.array([r["p_true"] for r in rows])
    return {"asks": len(rows), "yes_rate": _r(y.mean()), "mean_p": _r(p.mean()),
            "auc": _r(roc_auc_score(y, p)) if 0 < y.mean() < 1 else None,
            "brier": _r(np.mean((p - y) ** 2)),
            "brier_true_law": _r(np.mean((true - y) ** 2)),  # the best any model could do
            "ece": _r(_ece(p, y)), "reliability": reliability(p, y)}


def _ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean()
                     for b in range(bins) if (idx == b).any()))


# --- ranking policies for the simulation (the app uses the same orders) -----------------------

def rule_score(w: sim.World, req: sim.Request, pool: list[sim.Candidate], s: sim.HelperState
               ) -> list[sim.Candidate]:
    """app/rules/help_trigger_rules.rank_score: distance + ask penalty - yes-rate bonus."""
    def key(c: sim.Candidate) -> tuple[float, float, int]:
        score = (c.distance_km + ASK_PENALTY_KM * s.asks_in_window(c.row, req.t)
                 - RESPONSE_WEIGHT_KM * response_rate(s.accepted.get(c.row, 0),
                                                      s.asked.get(c.row, 0)))
        return score, -c.surplus, c.row
    return sorted(pool, key=key)


def learned(model: AcceptModel) -> sim.Ranker:
    def rank(w: sim.World, req: sim.Request, pool: list[sim.Candidate], s: sim.HelperState
             ) -> list[sim.Candidate]:
        if not pool:
            return pool
        p = model.predict(np.array([sim.features(w, req, c, s) for c in pool]))
        order = sorted(range(len(pool)), key=lambda i: (-p[i], pool[i].distance_km, pool[i].row))
        return [pool[i] for i in order]
    return rank


def sized(model: AcceptModel, target: float) -> sim.WaveSizer:
    def size(w: sim.World, req: sim.Request, pool: list[sim.Candidate], s: sim.HelperState,
             cap: int) -> int:
        p = model.predict(np.array([sim.features(w, req, c, s) for c in pool]))
        return learned_wave_size([float(v) for v in p], cap, target)
    return size


def _gini(x: np.ndarray) -> float:
    if len(x) == 0 or x.sum() == 0:
        return 0.0
    s = np.sort(x)
    n = len(s)
    return float((2 * np.arange(1, n + 1) - n - 1) @ s / (n * s.sum()))


def _max_week(times: list[float]) -> int:
    t = sorted(times)
    best, j = 0, 0
    for i in range(len(t)):
        while t[i] - t[j] >= sim.ASK_WINDOW_H:
            j += 1
        best = max(best, i - j + 1)
    return best


def simulate_policy(w: sim.World, reqs: list[sim.Request], start: sim.HelperState,
                    rank: sim.Ranker, size: sim.WaveSizer) -> dict[str, Any]:
    state = start.copy()
    out = [sim.run_request(w, r, rank, size, state) for r in reqs]
    covered = [o for o in out if o.covered]
    asks = sum(o.asks for o in out)
    per_helper: Counter[int] = Counter()
    times: dict[int, list[float]] = {}
    for r, o in zip(reqs, out, strict=True):
        for row in o.asked_rows:
            per_helper[row] += 1
            times.setdefault(row, []).append(float(r.t))
    weekly = {row: _max_week(t) for row, t in times.items()}
    pools = [len(sim.feasible(w, r, start, set())) for r in reqs]
    counts = np.array(sorted(per_helper.values(), reverse=True), dtype=float)
    top = max(1, int(round(0.1 * len(counts))))
    minutes = [o.minutes for o in covered if o.minutes is not None]
    return {
        "requests": len(reqs), "covered_rate": _r(len(covered) / len(reqs)) if reqs else None,
        "requests_with_no_feasible_helper": sum(n == 0 for n in pools),
        "requests_with_pool_above_wave": sum(n > sim.WAVE_SIZE for n in pools),
        "asks": asks, "asks_per_request": _r(asks / len(reqs)) if reqs else None,
        "acceptance_rate": _r(sum(o.yes for o in out) / asks) if asks else None,
        "asks_until_covered": _r(np.mean([o.asks for o in covered])) if covered else None,
        "minutes_to_cover_mean": _r(np.mean(minutes)) if minutes else None,
        "minutes_to_cover_median": _r(np.median(minutes)) if minutes else None,
        "helpers_asked": len(per_helper),
        "max_asks_one_helper": int(counts[0]) if len(counts) else 0,
        "max_asks_one_helper_7d": max(weekly.values(), default=0),
        "helpers_over_asked": sum(v > OVER_ASKED_PER_WEEK for v in weekly.values()),
        "share_of_asks_top10pct_helpers": _r(counts[:top].sum() / counts.sum())
        if counts.sum() else None,
        "gini_asks": _r(_gini(counts)),
    }


def capped(n: int) -> sim.WaveSizer:
    def size(_w: sim.World, _r: sim.Request, _p: list[sim.Candidate], _s: sim.HelperState,
             cap: int) -> int:
        return min(cap, n)
    return size


SMALL_WAVE = 2  # sensitivity: with small waves the order decides who is asked at all


def policies(model: AcceptModel) -> dict[str, tuple[sim.Ranker, sim.WaveSizer]]:
    return {"distance_only": (sim.by_distance, sim.fixed_waves),
            "rule_score": (rule_score, sim.fixed_waves),
            "learned_order": (learned(model), sim.fixed_waves),
            "rule_score_and_learned_wave_size": (rule_score, sized(model, WAVE_TARGET)),
            "learned_order_and_wave_size": (learned(model), sized(model, WAVE_TARGET)),
            f"sensitivity_wave{SMALL_WAVE}_distance_only": (sim.by_distance, capped(SMALL_WAVE)),
            f"sensitivity_wave{SMALL_WAVE}_rule_score": (rule_score, capped(SMALL_WAVE)),
            f"sensitivity_wave{SMALL_WAVE}_learned_order": (learned(model), capped(SMALL_WAVE))}


def run(artifacts_dir: Path, seed: int, split: Split = FIXED_SPLIT,
        on_step: Callable[[str], None] | None = None) -> dict[str, Any]:
    ds = build_dataset(seed, N_AGENTS)
    w = sim.build_world(ds)
    reqs = sim.requests(w)
    history, state_at_test = sim.history(w, reqs, split.val_end)
    train = [r for r in history if r["t"] < split.train_end]
    val = [r for r in history if split.train_end <= r["t"] < split.val_end]
    test_reqs = [r for r in reqs if r.t >= split.val_end]
    if not train or not val or not test_reqs:
        raise RuntimeError("simulated help history too small to train on")
    if on_step is not None:
        on_step("fit")
    model = fit(train, val, "candidate")
    # Blind asks: the same exploring policy on the test requests (for calibration scores).
    blind_log: list[dict[str, float]] = []
    blind_state = state_at_test.copy()
    explore = sim.exploring(1.5, seed)
    for r in test_reqs:
        sim.run_request(w, r, explore, sim.fixed_waves, blind_state, blind_log)
    metrics = {"train": scores(model, train), "validation": scores(model, val),
               "blind": scores(model, blind_log), "blind_before_platt": scores(model, blind_log,
                                                                               raw=True)}
    if on_step is not None:
        on_step("simulate")
    sims = {name: simulate_policy(w, test_reqs, state_at_test, rank, size)
            for name, (rank, size) in policies(model).items()}
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / HELPER_FILE
    path.write_text(json.dumps(model.to_json(), indent=1), encoding="utf-8")
    digest = sha256_file(path)
    short = hashlib.sha256(digest.encode()).hexdigest()[:8]
    manifest: dict[str, Any] = {
        "model_version": f"helper-{HELPER_SEMVER}-{short}",
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"), "seed": seed,
        "data_version": DATA_VERSION, "files": {HELPER_FILE: digest},
        "helper": {
            "model_name": HELPER_MODEL, "learned_from": "SIMULATED helper behaviour only",
            "features": list(FEATURES), "kind": "logistic regression + Platt (validation)",
            "behaviour_law": "ml/data_gen/helpers.py Behaviour (assumed, not measured)",
            "split": split.as_dict(), "requests": {"all": len(reqs), "test": len(test_reqs)},
            "asks": {"train": len(train), "validation": len(val), "blind": len(blind_log)},
            "coef_standardised": dict(zip(FEATURES, [round(float(c), 4) for c in model.coef],
                                          strict=True)),
            "wave_target": WAVE_TARGET, "metrics": metrics, "policy_simulation": sims,
        },
    }
    (artifacts_dir / HELPER_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("wrote %s (%s)", HELPER_MANIFEST, manifest["model_version"])
    return manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[train-helper] %(message)s")
    parser = argparse.ArgumentParser(description="Train the helper acceptance model (simulated)")
    parser.add_argument("--seed", type=int, default=get_settings().seed)
    parser.add_argument("--out", type=Path, default=None, help="artifacts dir (default: settings)")
    args = parser.parse_args()
    manifest = run(args.out or get_settings().artifacts_dir, args.seed)
    print(json.dumps({k: v for k, v in manifest["helper"].items()
                      if k in ("metrics", "policy_simulation")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
