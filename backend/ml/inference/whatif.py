"""What-if (F8): the cached quantile paths re-projected with a shifted starting balance.

Both scenarios share one set of seeded demand paths, so the only difference is the balance:
every path's first passage moves later for a positive delta (never earlier). No retraining.
Two variants, matching the risk cache's stockout method: one float alone (prepare / after) or
both floats from joint paths with coupled serving (prepare_joint / after_joint).
"""

from dataclasses import dataclass

import numpy as np

from ml.inference.stockout import StockoutConfig, StockoutResult, from_paths, sample_paths
from ml.inference.stockout_joint import Dependence, run_paths, sample_joint

BAND_PERCENTILES = (10, 50, 90)


@dataclass(frozen=True)
class Scenario:
    balance: float
    result: StockoutResult
    bands: np.ndarray  # (H + 1, 3) balance p10 / p50 / p90 at hour 0..H, floored at cfg.floor_bdt


def balance_bands(b0: float, drain: np.ndarray, inflow: np.ndarray, floor: float) -> np.ndarray:
    """Projected balance percentiles per hour (no refill); a float cannot go below its floor."""
    paths = b0 + np.cumsum(inflow - drain, axis=1)
    bands = np.percentile(paths, BAND_PERCENTILES, axis=0).T
    return np.maximum(np.vstack([np.full((1, 3), b0), bands]), floor)


def _scenario(b0: float, drain: np.ndarray, inflow: np.ndarray, cfg: StockoutConfig) -> Scenario:
    return Scenario(b0, from_paths(b0, drain, inflow, cfg),
                    balance_bands(b0, drain, inflow, cfg.floor_bdt))


def run(b0: float, delta: float, drain_q: np.ndarray, inflow_q: np.ndarray,
        cfg: StockoutConfig, rng: np.random.Generator) -> tuple[Scenario, Scenario]:
    """(before, after) for one float. With the cache's rng seed, `before` equals the cache."""
    drain, inflow = sample_paths(drain_q, inflow_q, cfg, rng)
    return _scenario(b0, drain, inflow, cfg), _scenario(b0 + delta, drain, inflow, cfg)


@dataclass(frozen=True)
class Paths:
    """Sampled demand paths and the no-change scenario: the slider-independent part of run()."""

    drain: np.ndarray
    inflow: np.ndarray
    before: Scenario


def prepare(b0: float, drain_q: np.ndarray, inflow_q: np.ndarray, cfg: StockoutConfig,
            rng: np.random.Generator) -> Paths:
    drain, inflow = sample_paths(drain_q, inflow_q, cfg, rng)
    return Paths(drain, inflow, _scenario(b0, drain, inflow, cfg))


def after(paths: Paths, delta: float, cfg: StockoutConfig) -> Scenario:
    """Same as run()'s second result, reusing prepared paths."""
    return _scenario(paths.before.balance + delta, paths.drain, paths.inflow, cfg)


@dataclass(frozen=True)
class JointPaths:
    """Joint demand paths of both floats (stockout_joint) and the no-change scenario of the
    float the slider moves; the other float keeps its balance."""

    d_out: np.ndarray
    d_in: np.ndarray
    cash0: float
    em0: float
    cash_float: bool
    before: Scenario


def _joint_scenario(cash0: float, em0: float, cash_float: bool, d_out: np.ndarray,
                    d_in: np.ndarray, cfg: StockoutConfig) -> Scenario:
    j = run_paths(cash0, em0, d_out, d_in, cfg)
    res, paths, b0 = (j.cash, j.cash_paths, cash0) if cash_float else (j.emoney,
                                                                       j.emoney_paths, em0)
    bands = np.percentile(paths, BAND_PERCENTILES, axis=0).T
    return Scenario(b0, res, np.maximum(np.vstack([np.full((1, 3), b0), bands]), cfg.floor_bdt))


def prepare_joint(cash0: float, em0: float, cash_float: bool, out_q: np.ndarray,
                  in_q: np.ndarray, cfg: StockoutConfig, dep: Dependence,
                  rng: np.random.Generator) -> JointPaths:
    """With the risk cache's seed and dependence, `before` equals the cached projection."""
    d_out, d_in = sample_joint(out_q, in_q, dep, cfg.n_paths, rng)
    return JointPaths(d_out, d_in, cash0, em0, cash_float,
                      _joint_scenario(cash0, em0, cash_float, d_out, d_in, cfg))


def after_joint(p: JointPaths, delta: float, cfg: StockoutConfig) -> Scenario:
    cash0 = p.cash0 + delta if p.cash_float else p.cash0
    em0 = p.em0 if p.cash_float else p.em0 + delta
    return _joint_scenario(cash0, em0, p.cash_float, p.d_out, p.d_in, cfg)
