"""Train the per-peer-group Isolation Forests (F9) and score them against injected anomalies.

Unsupervised: labels (system_meta.synthetic_labels) are used only to choose the model inputs,
the burst-day threshold and the contamination on validation folds, and to score the blind test.
Honest evaluation (ml/training/splits.py):
1. rolling-origin validation BEFORE the holdout: CV_FOLDS blocks of CV_BLOCK_DAYS, one every
   CV_STEP_DAYS back from the holdout start, so every window that ends inside the folds is scored
   exactly once; for each block the forests are fitted on windows that end before the block and
   score the windows that lie wholly inside it. Every candidate (input set x burst threshold x
   share) is scored the same way; the best pooled F1 wins (ties: the earlier, simpler candidate,
   then the smaller share; no positive in any block: DEFAULT);
2. the served forests are fitted on every window that ends before the holdout, with that choice;
3. the blind test (windows wholly inside the last 14 days) is scored once.

    python -m ml.training.anomaly [--seed 42]   (reads DATABASE_URL)
"""

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.core.config import DATA_VERSION, get_settings
from app.core.db import get_engine
from app.models.system_meta import SystemMeta
from ml.data_gen.timeline import HOLDOUT_START
from ml.features.anomaly import (
    BURST_FEATURES,
    DEFAULT_BURST_K,
    GLOBAL_GROUP,
    HISTORY_H,
    LEDGER_FEATURES,
    LEGACY_FEATURES,
    MIN_PEERS,
    STRIDE_H,
    WINDOW_H,
    FeatureSpec,
    Series,
    load_series,
    window_features,
)
from ml.features.panel import hour_of
from ml.inference.anomaly import Detector
from ml.registry import ANOMALY_FILE, ANOMALY_MANIFEST, ANOMALY_MODEL, ANOMALY_SEMVER, sha256_file
from ml.training.splits import FIXED_SPLIT, Split

log = logging.getLogger(__name__)
N_TREES = 200
# Share of windows each forest flags: chosen on the validation folds from this grid.
CONTAMINATION_GRID = (0.001, 0.0015, 0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03)
DEFAULT_CONTAMINATION = 0.005  # used only when the folds hold no positive window
CV_FOLDS = 8
CV_BLOCK_DAYS = 14
CV_STEP_DAYS = 8  # 14-day blocks every 8 days: the scored window ends never repeat
# A window counts as a true anomaly when >= 3 of its 7 days overlap an injected one; windows
# with a smaller, non-zero overlap are ambiguous and left out of precision/recall.
EVAL_MIN_OVERLAP_H = 72
FIRST_END = WINDOW_H + HISTORY_H
# Candidate model inputs, simplest first. Refills always use the ledger rule (ML-6); the old
# inputs (LEGACY_FEATURES) are scored on the same folds for reference only, never chosen.
CANDIDATE_SETS: tuple[tuple[str, ...], ...] = (
    LEDGER_FEATURES,
    LEDGER_FEATURES + ("burst_peak_peer_z",),
    LEDGER_FEATURES + ("rate_change_peer_z",),
    LEDGER_FEATURES + ("burst_peak_peer_z", "rate_change_peer_z"),
    LEDGER_FEATURES + ("burst_days_peer_z",),
    LEDGER_FEATURES + ("burst_peak_peer_z", "burst_days_peer_z"),
    LEDGER_FEATURES + BURST_FEATURES,
)
BURST_K_GRID = (1.5, 2.0, 2.5, 3.0)  # "burst day" = at least k x the usual same weekday
REFERENCE = FeatureSpec(LEGACY_FEATURES)

Spans = dict[str, list[tuple[int, int, str]]]
Stacked = tuple[np.ndarray, np.ndarray, np.ndarray]


def candidates() -> list[FeatureSpec]:
    out: list[FeatureSpec] = []
    for features in CANDIDATE_SETS:
        ks = BURST_K_GRID if "burst_days_peer_z" in features else (DEFAULT_BURST_K,)
        out += [FeatureSpec(features, k) for k in ks]
    return out


def stack(s: Series, ends: range, spec: FeatureSpec | None = None) -> Stacked:
    """Features for every agent x window end: (rows, F), agent row index, window end."""
    xs = [window_features(s, e, spec).x for e in ends]
    n = len(s.agent_ids)
    return (np.vstack(xs), np.tile(np.arange(n), len(xs)),
            np.repeat(np.array(list(ends), dtype=np.int64), n))


class Stacks:
    """Rows of every window end up to `last`, computed once per input superset and sliced."""

    def __init__(self, s: Series, last: int) -> None:
        self.s, self.last = s, last
        self._full: dict[tuple[tuple[str, ...], float], tuple[FeatureSpec, Stacked]] = {}

    def get(self, spec: FeatureSpec, ends: range) -> Stacked:
        base = (FeatureSpec(LEDGER_FEATURES + BURST_FEATURES, spec.burst_k) if spec.ledger
                else FeatureSpec(LEGACY_FEATURES))
        key = (base.features, base.burst_k)
        if key not in self._full:
            self._full[key] = (base, stack(self.s, fit_ends(self.last), base))
        _, (x, rows, end_of) = self._full[key]
        m = np.isin(end_of, np.array(list(ends), dtype=np.int64))
        cols = [base.features.index(f) for f in spec.features]
        return x[m][:, cols], rows[m], end_of[m]


def fit_ends(end_h: int) -> range:
    """Window ends of the fitting set: every window that closes at or before `end_h`."""
    return range(FIRST_END, end_h + 1, STRIDE_H)


def inside_ends(start_h: int, end_h: int) -> range:
    """Window ends of windows lying wholly inside [start_h, end_h)."""
    return range(start_h + WINDOW_H, end_h + 1, STRIDE_H)


def fit_rows(x: np.ndarray, groups: np.ndarray, all_groups: set[str], seed: int,
             contamination: float, spec: FeatureSpec
             ) -> tuple[Detector, dict[str, int], dict[str, np.ndarray]]:
    """Forests per peer group on the given rows; also each group's training scores (higher =
    more anomalous), for re-thresholding at another share."""
    models: dict[str, IsolationForest] = {}
    sizes: dict[str, int] = {}
    train_scores: dict[str, np.ndarray] = {}
    for g in sorted(all_groups | {GLOBAL_GROUP}):
        m = np.ones(len(x), dtype=bool) if g == GLOBAL_GROUP else groups == g
        models[g] = IsolationForest(n_estimators=N_TREES, contamination=contamination,
                                    random_state=seed).fit(x[m])
        sizes[g] = int(m.sum())
        train_scores[g] = -models[g].score_samples(x[m])
    return Detector("candidate", models, spec), sizes, train_scores


def fit(s: Series, seed: int, end_h: int, contamination: float, spec: FeatureSpec | None = None
        ) -> tuple[Detector, dict[str, int], dict[str, np.ndarray]]:
    """Forests per peer group on windows ending at or before `end_h`."""
    spec = spec or FeatureSpec()
    x, rows, _ = stack(s, fit_ends(end_h), spec)
    return fit_rows(x, np.array(s.groups)[rows], set(s.groups), seed, contamination, spec)


def label_spans(labels: list[dict[str, str]]) -> Spans:
    out: Spans = {}
    for lab in labels:
        span = (hour_of(datetime.fromisoformat(lab["window_start"])),
                hour_of(datetime.fromisoformat(lab["window_end"])), lab["kind"])
        out.setdefault(lab["agent_code"], []).append(span)
    return out


def _overlap(spans: list[tuple[int, int, str]], end: int) -> tuple[int, str | None]:
    best, kind = 0, None
    for a, b, k in spans:
        o = max(0, min(b, end) - max(a, end - WINDOW_H))
        if o > best:
            best, kind = o, k
    return best, kind


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def truth(s: Series, spans: Spans, rows: np.ndarray, end_of: np.ndarray
          ) -> tuple[np.ndarray, np.ndarray, list[str | None]]:
    """(positive, kept = positive or clean, kind) per scored window."""
    found = [_overlap(spans.get(s.codes[r], []), int(e)) for r, e in zip(rows, end_of, strict=True)]
    pos = np.array([o >= EVAL_MIN_OVERLAP_H for o, _ in found], dtype=bool)
    keep = pos | np.array([o == 0 for o, _ in found], dtype=bool)
    return pos, keep, [k for _, k in found]


def counts(flag: np.ndarray, pos: np.ndarray, keep: np.ndarray) -> tuple[int, int, int]:
    """(tp, fp, fn); ambiguous windows count for nothing."""
    return (int((flag & pos).sum()), int((flag & keep & ~pos).sum()), int((~flag & pos).sum()))


def f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def evaluate(det: Detector, s: Series, spans: Spans, ends: range) -> dict[str, Any]:
    """Window- and agent-level precision/recall of the flags against the injected labels."""
    x, rows, end_of = stack(s, ends, det.spec)
    score, thr = det.score(x, np.array(s.groups)[rows])
    flag = score > thr
    pos, keep, kinds = truth(s, spans, rows, end_of)
    tp, fp, fn = counts(flag, pos, keep)
    true_agents = {int(r) for r in rows[pos]}
    flagged_agents = {int(r) for r in rows[flag & keep]}
    hit = len(true_agents & flagged_agents)
    return {
        "windows": int(keep.sum()), "excluded_ambiguous": int((~keep).sum()),
        "positives": int(pos.sum()), "flagged": int((flag & keep).sum()),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
        "recall_by_kind": _by_kind(flag, pos, kinds),
        "agents_true": len(true_agents), "agents_flagged": len(flagged_agents),
        "agent_precision": _ratio(hit, len(flagged_agents)),
        "agent_recall": _ratio(hit, len(true_agents)),
    }


def _by_kind(flag: np.ndarray, pos: np.ndarray, kinds: list[str | None]) -> dict[str, Any]:
    by_kind: dict[str, list[int]] = {}
    for i in np.flatnonzero(pos):
        k = by_kind.setdefault(str(kinds[i]), [0, 0])
        k[0] += 1
        k[1] += int(flag[i])
    return {k: _ratio(v[1], v[0]) for k, v in sorted(by_kind.items())}


def cv_blocks(split: Split) -> list[tuple[int, int]]:
    """Validation blocks (start_h, end_h), the last ending at the holdout start, oldest first; a
    block is kept only when its fitting windows exist."""
    block, step = CV_BLOCK_DAYS * 24, CV_STEP_DAYS * 24
    out = [(split.val_end - k * step - block, split.val_end - k * step) for k in range(CV_FOLDS)]
    return sorted(b for b in out if b[0] >= FIRST_END + STRIDE_H)


def fold_table(st: Stacks, seed: int, spans: Spans, split: Split, spec: FeatureSpec
               ) -> tuple[dict[float, list[int]], dict[float, dict[str, list[int]]]]:
    """Pooled (tp, fp, fn) per grid share over the validation blocks, and per anomaly style
    (positives, caught). Labels of the holdout are never read here."""
    totals = {c: [0, 0, 0] for c in CONTAMINATION_GRID}
    kinds_tot: dict[float, dict[str, list[int]]] = {c: {} for c in CONTAMINATION_GRID}
    groups_all = np.array(st.s.groups)
    for b0, b1 in cv_blocks(split):
        if b1 > split.val_end:
            raise AssertionError("validation block reaches into the blind test")
        xf, rf, _ = st.get(spec, fit_ends(b0))
        det, _, train_scores = fit_rows(xf, groups_all[rf], set(st.s.groups), seed,
                                        CONTAMINATION_GRID[0], spec)
        x, rows, end_of = st.get(spec, inside_ends(b0, b1))
        groups = groups_all[rows]
        score, _ = det.score(x, groups)
        pos, keep, kinds = truth(st.s, spans, rows, end_of)
        for c in CONTAMINATION_GRID:
            thr = np.zeros(len(x))
            for g in np.unique(groups):
                key = str(g) if str(g) in train_scores else GLOBAL_GROUP
                thr[groups == g] = np.percentile(train_scores[key], 100 * (1 - c))
            flag = score > thr
            for j, v in enumerate(counts(flag, pos, keep)):
                totals[c][j] += v
            for i in np.flatnonzero(pos):
                k = kinds_tot[c].setdefault(str(kinds[i]), [0, 0])
                k[0] += 1
                k[1] += int(flag[i])
    return totals, kinds_tot


def _row(c: float, t: list[int]) -> dict[str, Any]:
    return {"contamination": c, "tp": t[0], "fp": t[1], "fn": t[2],
            "precision": _ratio(t[0], t[0] + t[1]), "recall": _ratio(t[0], t[0] + t[2]),
            "f1": round(f1(*t), 4)}


def select_contamination(s: Series, seed: int, spans: Spans, split: Split,
                         spec: FeatureSpec | None = None, st: Stacks | None = None
                         ) -> tuple[float, dict[str, Any]]:
    """Grid share with the best pooled F1 over the validation blocks for one input set."""
    spec = spec or FeatureSpec()
    totals, kinds = fold_table(st or Stacks(s, split.val_end), seed, spans, split, spec)
    positives = sum(totals[CONTAMINATION_GRID[0]][0::2])
    if positives == 0:
        chosen = DEFAULT_CONTAMINATION
    else:
        chosen = max(CONTAMINATION_GRID, key=lambda c: (round(f1(*totals[c]), 6), -c))
    return chosen, {"blocks": [{"start_h": a, "end_h": b} for a, b in cv_blocks(split)],
                    "criterion": "max pooled F1 over validation blocks, ties -> smaller share",
                    "positives": positives,
                    "grid": [_row(c, t) for c, t in totals.items()], "chosen": chosen,
                    "recall_by_kind": {k: _ratio(v[1], v[0]) for k, v in sorted(
                        kinds.get(chosen, {}).items())}}


def _spec_json(spec: FeatureSpec) -> dict[str, Any]:
    return {"features": list(spec.features), "burst_k": spec.burst_k}


def select(s: Series, seed: int, spans: Spans, split: Split
           ) -> tuple[FeatureSpec, float, dict[str, Any]]:
    """Input set, burst threshold and share with the best pooled validation F1 (ties: the
    earlier candidate, then the smaller share). The legacy inputs are scored for reference."""
    st = Stacks(s, split.val_end)
    table: list[dict[str, Any]] = []
    best: tuple[float, FeatureSpec, float, dict[str, Any]] | None = None
    for spec in candidates():
        c, sel = select_contamination(s, seed, spans, split, spec, st)
        row = next(r for r in sel["grid"] if r["contamination"] == c)
        table.append(_spec_json(spec) | {"chosen_row": row,
                                         "recall_by_kind": sel["recall_by_kind"]})
        log.info("validation %s k=%.1f: c=%.4f F1 %.4f", ",".join(spec.features), spec.burst_k,
                 c, row["f1"])
        if best is None or row["f1"] > best[0]:
            best = (row["f1"], spec, c, sel)
    if best is None:
        raise AssertionError("no anomaly candidate")
    ref_c, ref = select_contamination(s, seed, spans, split, REFERENCE, st)
    _, spec, chosen, sel = best
    return spec, chosen, {
        "blocks": sel["blocks"], "positives": sel["positives"],
        "criterion": "max pooled F1 over validation blocks over inputs x burst_k x share; ties "
                     "-> simpler inputs, then smaller share",
        "grid": sel["grid"], "chosen": chosen, "chosen_inputs": _spec_json(spec),
        "recall_by_kind": sel["recall_by_kind"], "candidates": table,
        "reference_legacy_inputs": {
            "chosen_row": next(r for r in ref["grid"] if r["contamination"] == ref_c),
            "recall_by_kind": ref["recall_by_kind"]},
    }


def _labels(session: Session) -> list[dict[str, str]]:
    row = session.get(SystemMeta, "synthetic_labels")
    value = row.value if row else None
    return list(value.get("anomalies", [])) if isinstance(value, dict) else []


def run(artifacts_dir: Path, seed: int, split: Split = FIXED_SPLIT) -> dict[str, Any]:
    with Session(get_engine()) as session:
        s = load_series(session)
        spans = label_spans(_labels(session))
    spec, contamination, selection = select(s, seed, spans, split)
    log.info("chosen on validation: %s burst_k %.1f contamination %.4f (%d positive windows)",
             ",".join(spec.features), spec.burst_k, contamination, selection["positives"])
    det, sizes, _ = fit(s, seed, split.val_end, contamination, spec)
    metrics = {
        # Blind test: scored once, after every choice was fixed on validation.
        "holdout": evaluate(det, s, spans, inside_ends(split.val_end, split.n_hours)),
        "train_period": evaluate(det, s, spans, fit_ends(split.val_end)),
        "validation_cv": {k: v for k, v in selection.items() if k not in ("grid", "candidates")}
        | {"chosen_row": next((r for r in selection["grid"]
                               if r["contamination"] == contamination), None)},
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"features": list(spec.features), "burst_k": spec.burst_k,
                 "models": det.models}, artifacts_dir / ANOMALY_FILE, compress=3)
    digest = sha256_file(artifacts_dir / ANOMALY_FILE)
    short = hashlib.sha256(digest.encode()).hexdigest()[:8]
    manifest: dict[str, Any] = {
        "model_version": f"iforest-{ANOMALY_SEMVER}-{short}",
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed, "data_version": DATA_VERSION,
        "files": {ANOMALY_FILE: digest},
        "anomaly": {
            "model_name": ANOMALY_MODEL, "features": list(spec.features),
            "burst_k": spec.burst_k, "refill_rule": "ledger" if spec.ledger else "total_float",
            "window_h": WINDOW_H, "history_h": HISTORY_H, "stride_h": STRIDE_H,
            "n_estimators": N_TREES,
            "contamination": contamination, "contamination_selection": selection,
            "min_peers": MIN_PEERS, "group_windows": sizes,
            "train_windows_end_before": HOLDOUT_START.isoformat(),
            "eval_min_overlap_h": EVAL_MIN_OVERLAP_H, "metrics": metrics,
        },
    }
    (artifacts_dir / ANOMALY_MANIFEST).write_text(json.dumps(manifest, indent=2),
                                                  encoding="utf-8")
    log.info("wrote %s (%s)", ANOMALY_MANIFEST, manifest["model_version"])
    return manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[train-anomaly] %(message)s")
    parser = argparse.ArgumentParser(description="Train the agent anomaly detector")
    parser.add_argument("--seed", type=int, default=get_settings().seed)
    parser.add_argument("--out", type=Path, default=None, help="artifacts dir (default: settings)")
    args = parser.parse_args()
    manifest = run(args.out or get_settings().artifacts_dir, args.seed)
    print(json.dumps(manifest["anomaly"]["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
