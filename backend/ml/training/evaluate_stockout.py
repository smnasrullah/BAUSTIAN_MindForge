"""Alert quality of the stockout probability on the blind test (last 14 days), per horizon.

Every planning round projects each agent's two floats once over 72 h (one Monte Carlo run); the
6 / 24 / 72 h probabilities are read off the same cdf, so the run is ~3x cheaper than one run
per horizon. A case is (agent, float, round). Ground truth = the logged history turned
customers away (> STOCKOUT_MIN_BDT in an hour) within H hours of the round. Prediction = the
probability reaches the amber cut of that horizon (settings.risk_thresholds). Reported per H:
precision, recall, F1, false alerts per agent-week (FP / agent-weeks), mean lead time (hours
between the first alert covering a stockout episode and its first short hour) and the Brier
score. The logged history includes the agents' own refills and no AI action, so a no-refill
projection over-predicts there; precision is the honest counterpart of the recall.

    python -m ml.training.evaluate_stockout [--method joint|independent] [--paths N]
        [--level amber|red] [--out FILE]
"""

import argparse
import json
import sys
import time
from collections.abc import Mapping
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.rules.risk_rules import HORIZONS, build_config
from app.services import holdout_inputs, impact, risk
from ml.evaluation.stockout_eval import FLOATS, STOCKOUT_MIN_BDT
from ml.inference.stockout import StockoutConfig, project
from ml.inference.stockout_joint import load_dependence, run_paths, sample_joint

WEEK_H = 168
MAX_H = max(HORIZONS)
N_PATHS = 500


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def episode_starts(hit: np.ndarray) -> list[tuple[int, int]]:
    """(row, hour) of the first short hour of every stockout episode. hit: (A, T) bool."""
    prev = np.concatenate([np.zeros((hit.shape[0], 1), dtype=bool), hit[:, :-1]], axis=1)
    rows, hours = np.nonzero(hit & ~prev)
    return list(zip(rows.tolist(), hours.tolist(), strict=True))


def realised(unmet: np.ndarray, rounds: np.ndarray, horizon: int) -> np.ndarray:
    """(R, A) bool: any short hour in [round, round + horizon). Rounds that overrun are False."""
    c = np.concatenate([np.zeros((unmet.shape[0], 1)),
                        np.cumsum(unmet > STOCKOUT_MIN_BDT, axis=1)], axis=1)
    end = np.minimum(rounds + horizon, unmet.shape[1])
    return (c[:, end] - c[:, rounds] > 0).T


def score_horizon(p: np.ndarray, y: np.ndarray, flag: np.ndarray, rounds: np.ndarray,
                  unmet: np.ndarray, horizon: int, agent_weeks: float) -> dict[str, Any]:
    """p / y / flag: (R, A, F); NaN p = round without a full horizon (excluded)."""
    ok = ~np.isnan(p)
    pv, yv, fv = p[ok], y[ok], flag[ok]
    tp, fp = int((fv & yv).sum()), int((fv & ~yv).sum())
    fn, n = int((~fv & yv).sum()), int(ok.sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    leads, events = [], 0
    for fi in range(p.shape[2]):
        for a, s in episode_starts(unmet[fi] > STOCKOUT_MIN_BDT):
            if s < rounds[0] or s >= rounds[-1] + horizon:
                continue
            events += 1
            cover = (rounds <= s) & (s < rounds + horizon) & ok[:, a, fi] & flag[:, a, fi]
            if cover.any():
                leads.append(s - int(rounds[cover][0]))
    return {
        "cases": n, "stockout_cases": int(yv.sum()), "tp": tp, "fp": fp, "fn": fn,
        "precision": _r(prec), "recall": _r(rec), "f1": _r(f1),
        "false_alerts_per_agent_week": _r(fp / agent_weeks),
        "episodes": events, "episodes_alerted": len(leads),
        "episode_recall": _r(len(leads) / events) if events else None,
        "mean_lead_time_h": _r(np.mean(leads)) if leads else None,
        "median_lead_time_h": _r(np.median(leads)) if leads else None,
        "brier": _r(np.mean((pv - yv) ** 2)) if n else None,
        "mean_p": _r(pv.mean()) if n else None,
        "realised_rate": _r(yv.mean()) if n else None,
    }


def evaluate_stockout(prob: Mapping[int, np.ndarray], rounds: np.ndarray, unmet: np.ndarray,
                      cuts: Mapping[int, float], n_hours: int) -> dict[str, Any]:
    """prob: horizon -> (R, A, F) P(stockout within H); unmet: (F, A, T); rounds: (R,) hours."""
    agent_weeks = unmet.shape[1] * n_hours / WEEK_H
    out: dict[str, Any] = {}
    for h, p in prob.items():
        y = np.stack([realised(unmet[fi], rounds, h) for fi in range(unmet.shape[0])], axis=2)
        out[str(h)] = {"cut": cuts[h]} | score_horizon(
            p, y, p >= cuts[h], rounds, unmet, h, agent_weeks)
    return out


def _cdfs(method: str, seed: int, n_paths: int, agents: list[Any], deps: list[Any],
          a: int, o: int, balance: tuple[float, float], out_q: np.ndarray, in_q: np.ndarray
          ) -> list[np.ndarray]:
    """[cash cdf, e-money cdf], each (L,) P(stockout by the end of hour h)."""
    cfg = StockoutConfig(n_paths=n_paths)
    if method == "joint":
        rng = np.random.default_rng([seed, agents[a].id, risk.JOINT_STREAM, o])
        d_out, d_in = sample_joint(out_q, in_q, deps[a], cfg.n_paths, rng)
        j = run_paths(balance[0], balance[1], d_out, d_in, cfg)
        return [j.cash.cdf, j.emoney.cdf]
    res = []
    for fi, (b0, drain, inflow) in enumerate(((balance[0], out_q, in_q),
                                              (balance[1], in_q, out_q))):
        rng = np.random.default_rng([seed, agents[a].id, fi, o])
        res.append(project(b0, drain, inflow, cfg, rng).cdf)
    return res


def collect_probs(h: holdout_inputs.Holdout, method: str, seed: int, n_paths: int,
                  deps: list[Any]) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    rounds = np.array(sorted(h.forecasts), dtype=np.int64)
    n_agents = len(h.agents)
    prob = {hz: np.full((len(rounds), n_agents, len(FLOATS)), np.nan) for hz in HORIZONS}
    for ri, o in enumerate(rounds.tolist()):
        fc = h.forecasts[o]
        out_all, in_all = fc["cash_out"], fc["cash_in"]
        span = out_all.shape[1]
        for a in range(n_agents):
            cdfs = _cdfs(method, seed, n_paths, h.agents, deps, a, o,
                         (float(h.balance["cash"][a, o]), float(h.balance["emoney"][a, o])),
                         out_all[a], in_all[a])
            for hz in HORIZONS:
                if hz <= span and o + hz <= h.world.n_hours:
                    for fi, cdf in enumerate(cdfs):
                        prob[hz][ri, a, fi] = cdf[hz - 1]
    return rounds, prob


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=("joint", "independent"), default=None)
    ap.add_argument("--paths", type=int, default=N_PATHS)
    ap.add_argument("--level", choices=("amber", "red"), default="amber")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    settings = get_settings()
    method = args.method or ("joint" if settings.stockout_method != "independent"
                             else "independent")
    with Session(get_engine()) as session:
        h = holdout_inputs.load(session, settings, impact.impact_config(settings), MAX_H)
    if h is None:
        raise SystemExit("holdout inputs unavailable (is the DB the fixed seeded set?)")
    table = load_dependence(settings.artifacts_dir) if method == "joint" else None
    if method == "joint" and table is None:
        method = "independent"
    deps = [risk.dependence_for(table, a) for a in h.agents] if table is not None else []
    cfg = build_config(settings.risk_thresholds)
    cuts = {hz: getattr(cfg.cuts[hz], args.level) for hz in HORIZONS}
    t0 = time.perf_counter()
    rounds, prob = collect_probs(h, method, settings.seed, args.paths, deps)
    unmet = np.stack([h.unmet["cash_out"], h.unmet["cash_in"]])
    res = {"method": method, "n_paths": args.paths, "level": args.level, "rounds": len(rounds),
           "agents": len(h.agents), "seconds": round(time.perf_counter() - t0, 1),
           "by_horizon_h": evaluate_stockout(prob, rounds, unmet, cuts, h.world.n_hours)}
    print(f"stockout alerts ({method}, {args.paths} paths, {args.level} cut, "
          f"{res['rounds']} rounds x {res['agents']} agents, {res['seconds']} s)")
    print(f"{'H':>4} {'cut':>5} {'prec':>6} {'recall':>6} {'F1':>6} {'FP/ag/wk':>9} "
          f"{'lead h':>7} {'brier':>6} {'realised':>8}")
    for hz, m in res["by_horizon_h"].items():
        print(f"{hz:>4} {m['cut']:>5} {_fmt(m['precision'])} {_fmt(m['recall'])} "
              f"{_fmt(m['f1'])} {_fmt(m['false_alerts_per_agent_week'], 9)} "
              f"{_fmt(m['mean_lead_time_h'], 7)} {_fmt(m['brier'])} "
              f"{_fmt(m['realised_rate'], 8)}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
    return 0


def _fmt(x: float | None, w: int = 6) -> str:
    return f"{'n/a':>{w}}" if x is None else f"{x:>{w}.3f}"


if __name__ == "__main__":
    sys.exit(main())
