"""Van V3 evaluation (synthetic data): policies A-D over >= 5 seeds with 95% t-intervals, the
paired D vs C and D vs A contrasts, sensitivity on one seed, and the road-cache reference run on
the database seed. Every seed uses estimate distances (agent coordinates differ per seed; the
road cache only holds the database seed's agents). Written to ml/van/van_v3_eval.json and served
by GET /api/v1/impact/van-comparison. The verdicts are computed, never written by hand.

    python -m ml.van.evaluate --out ml/van/van_v3_eval.json
"""

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from app.rules.van_routing.models import VanConfig
from ml.data_gen.dataset import build_dataset
from ml.van import backtest, sensitivity
from ml.van.baselines import POLICIES

SEEDS = (42, 43, 44, 45, 46)
METRICS = ("total_bdt", "van_bdt", "km", "trips", "stockout_h", "lost_value_bdt",
           "deadline_hit_rate", "service_rate", "solve_ms_mean", "solve_ms_max")
RULES_VERSION = "van-rules-2"


def stat(xs: list[float]) -> dict[str, float]:
    """Mean with a 95% t-interval over seeds (a point when there is one value)."""
    mean = float(np.mean(xs))
    if len(xs) < 2:
        return {"mean": round(mean, 4), "lo": round(mean, 4), "hi": round(mean, 4)}
    half = float(stats.t.ppf(0.975, len(xs) - 1) * np.std(xs, ddof=1) / math.sqrt(len(xs)))
    return {"mean": round(mean, 4), "lo": round(mean - half, 4), "hi": round(mean + half, 4)}


def contrast(runs: list[dict[str, Any]], first: str, second: str) -> dict[str, Any]:
    diff = [r["policies"][first]["total_bdt"] - r["policies"][second]["total_bdt"] for r in runs]
    s = stat(diff)
    verdict = ("lower" if s["hi"] < 0 else "higher" if s["lo"] > 0 else "no_clear_difference")
    return {"first": first, "second": second, "diff_total_bdt": s,
            "seeds_first_lower": sum(1 for d in diff if d < 0), "seeds": len(diff),
            "verdict": verdict}


def policies(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in POLICIES:
        per = [r["policies"][name] for r in runs]
        areas = sorted({a for p in per for a in p["service_rate_by_area"]})
        reasons = sorted({k for p in per for k in p["drop_reasons"]})
        out.append({
            "name": name, "metrics": {m: stat([float(p[m]) for p in per]) for m in METRICS},
            "service_rate_by_area": {a: round(float(np.mean(
                [p["service_rate_by_area"].get(a, 1.0) for p in per])), 4) for a in areas},
            "drop_reasons": {k: round(float(np.mean([p["drop_reasons"].get(k, 0) for p in per])),
                                      2) for k in reasons}})
    return out


def evaluate(seeds: tuple[int, ...], sens_seed: int, ref_seed: int,
             cfg: VanConfig) -> dict[str, Any]:
    from app.services import van_geometry

    runs: list[dict[str, Any]] = []
    sens: list[dict[str, Any]] = []
    for seed in seeds:
        ds = build_dataset(seed)
        runs.append(backtest.run(seed, cfg, {}, ds))
        if seed == sens_seed:
            sens = sensitivity.run(seed, cfg, ds)
        print(f"seed {seed}: {runs[-1]['instances']} instances, {runs[-1]['stops']} stops",
              flush=True)
    ref = backtest.run(ref_seed, cfg, van_geometry.load().legs)
    return {
        "label": "synthetic data", "model_version": RULES_VERSION,
        "generated_at": datetime.now(UTC).isoformat(), "distance_source": "estimate",
        "seeds": list(seeds), "instances": sum(r["instances"] for r in runs),
        "stops": sum(r["stops"] for r in runs), "policies": policies(runs),
        "d_vs_c": contrast(runs, "D_full_model", "C_hard_deadline"),
        "d_vs_a": contrast(runs, "D_full_model", "A_separate_trips"),
        "sensitivity": sens, "sensitivity_seed": sens_seed,
        "reference": {"seed": ref_seed, "distance_source": ref["distance_source"],
                      "instances": ref["instances"], "stops": ref["stops"],
                      "total_bdt": {k: v["total_bdt"] for k, v in ref["policies"].items()}},
        "notes": ["oracle needs: routing quality only, no forecast error",
                  "estimate distances for every seed; reference = database seed on road cache",
                  "policy A has no fleet limit (one van per agent, all at once)"],
        "per_seed": [{"seed": r["seed"], "instances": r["instances"], "stops": r["stops"],
                      "policies": r["policies"]} for r in runs],
        "config": runs[0]["config"] if runs else {}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    ap.add_argument("--sensitivity-seed", type=int, default=SEEDS[0])
    ap.add_argument("--reference-seed", type=int, default=SEEDS[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    seeds = tuple(int(s) for s in args.seeds.split(","))
    result = evaluate(seeds, args.sensitivity_seed, args.reference_seed, VanConfig())
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("d_vs_c", "d_vs_a", "reference")}, indent=1))


if __name__ == "__main__":
    main()
