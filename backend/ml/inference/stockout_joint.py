"""Joint, coupled stockout projection of both floats (method: docs/METHODS.md §2, "Stockout,
joint").

Cash-out and cash-in demand are sampled TOGETHER from their hourly q10/q50/q90 (the two-piece
linear quantile function of stockout.py) through one Gaussian copula per path:
    z_out[h] = sqrt(rho_out) c_out + sqrt(1 - rho_out) e_out[h]      (same for cash-in)
    corr(c_out, c_in) = cross_path,  corr(e_out[h], e_in[h]) = cross_hour
The four numbers come per agent segment from forecast residuals on the validation period
(ml/training/dependence.py), replacing the old fixed rho 0.6 and independent floats.

Both floats then move hour by hour with the simulator's serving rule (ml/data_gen/simulate.py):
cash-out needs cash, cash-in needs e-money, and what one float pays out the other receives. So a
float that runs dry also stops refilling the other one (coupling). A float is stocked out in the
first hour that turns customers away (> STOCKOUT_MIN_BDT), at the share of that hour it still
served. Variants: no refill (the conservative DECISION input) and refill-aware (the agent's own
refill habit, `Refill`; an additional view only).
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.special import ndtr

from ml.data_gen.simulate import serve
from ml.inference.stockout import StockoutConfig, StockoutResult, demand_quantile
from ml.registry import DEPENDENCE_FILE

STOCKOUT_MIN_BDT = 0.5  # same cut as the realised stockouts of the backtests


@dataclass(frozen=True)
class Dependence:
    rho_out: float = 0.6  # share of each hour's cash-out shock common to the whole path
    rho_in: float = 0.6
    cross_path: float = 0.0  # correlation of the cash-out and cash-in path factors
    cross_hour: float = 0.0  # correlation of the cash-out and cash-in hourly shocks

    def __post_init__(self) -> None:
        for v in (self.rho_out, self.rho_in):
            if not 0.0 <= v < 1.0:
                raise ValueError("rho must be in [0, 1)")
        for v in (self.cross_path, self.cross_hour):
            if not -1.0 < v < 1.0:
                raise ValueError("cross correlation must be in (-1, 1)")


POOLED = "all"
_FIELDS = ("rho_out", "rho_in", "cross_path", "cross_hour")


def load_dependence(artifacts_dir: Path) -> dict[str, Dependence] | None:
    """Segment ('t<tier>-a<area code>') -> Dependence, plus POOLED; None without a table."""
    path = artifacts_dir / DEPENDENCE_FILE
    if not path.is_file():
        return None
    blob = json.loads(path.read_text(encoding="utf-8"))
    out = {s: Dependence(*(float(v[k]) for k in _FIELDS)) for s, v in blob["segments"].items()}
    out[POOLED] = Dependence(*(float(blob["pooled"][k]) for k in _FIELDS))
    return out


def segment(tier: int, area_code: int) -> str:
    return f"t{int(tier)}-a{int(area_code)}"


@dataclass(frozen=True)
class Refill:
    """An agent's usual refills: P(refill at each future hour) and the levels a refill restores
    (median after-refill balance per float), from its own history before the origin."""

    prob: np.ndarray  # (H,)
    cash_level: float
    emoney_level: float


@dataclass(frozen=True)
class Joint:
    cash: StockoutResult
    emoney: StockoutResult
    cash_paths: np.ndarray  # (N, H) balance at the end of each hour
    emoney_paths: np.ndarray


def _pair(rng: np.random.Generator, shape: tuple[int, ...], corr: float
          ) -> tuple[np.ndarray, np.ndarray]:
    a = rng.standard_normal(shape)
    b = corr * a + np.sqrt(1.0 - corr * corr) * rng.standard_normal(shape)
    return a, b


def sample_joint(out_q: np.ndarray, in_q: np.ndarray, dep: Dependence, n: int,
                 rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """(N, H) cash-out and cash-in demand paths. out_q / in_q: (H, 3) hourly BDT quantiles."""
    h = out_q.shape[0]
    c_out, c_in = _pair(rng, (n, 1), dep.cross_path)
    e_out, e_in = _pair(rng, (n, h), dep.cross_hour)
    z_out = np.sqrt(dep.rho_out) * c_out + np.sqrt(1 - dep.rho_out) * e_out
    z_in = np.sqrt(dep.rho_in) * c_in + np.sqrt(1 - dep.rho_in) * e_in
    return (demand_quantile(out_q, np.asarray(ndtr(z_out))),
            demand_quantile(in_q, np.asarray(ndtr(z_in))))


def simulate(cash0: float, em0: float, d_out: np.ndarray, d_in: np.ndarray, floor: float,
             refill: Refill | None, rng: np.random.Generator | None
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(t_cash, t_emoney, cash_paths, emoney_paths): first stockout time per path (inf = none
    within H, 0 = already at or below the floor) and end-of-hour balances. A refill at the top
    of an hour raises a float to its level (never lowers it)."""
    n, horizon = d_out.shape
    cash, em = np.full(n, float(cash0)), np.full(n, float(em0))
    t_cash = np.where(cash <= floor, 0.0, np.inf)
    t_em = np.where(em <= floor, 0.0, np.inf)
    cash_paths, em_paths = np.empty((n, horizon)), np.empty((n, horizon))
    draws = None if refill is None or rng is None else rng.random((n, horizon))
    for h in range(horizon):
        if refill is not None and draws is not None:
            hit = draws[:, h] < refill.prob[h]
            cash = np.where(hit, np.maximum(cash, refill.cash_level), cash)
            em = np.where(hit, np.maximum(em, refill.emoney_level), em)
        s_in, s_out = serve(np.maximum(cash - floor, 0.0), np.maximum(em - floor, 0.0),
                            d_in[:, h], d_out[:, h])
        short_c = (d_out[:, h] - s_out > STOCKOUT_MIN_BDT) & np.isinf(t_cash)
        short_e = (d_in[:, h] - s_in > STOCKOUT_MIN_BDT) & np.isinf(t_em)
        t_cash[short_c] = h + s_out[short_c] / d_out[short_c, h]
        t_em[short_e] = h + s_in[short_e] / d_in[short_e, h]
        cash, em = cash + s_in - s_out, em - s_in + s_out
        cash_paths[:, h], em_paths[:, h] = cash, em
    return t_cash, t_em, cash_paths, em_paths


def from_times(t: np.ndarray, horizon: int, cfg: StockoutConfig) -> StockoutResult:
    """Stockout distribution from first-passage times (same reading as stockout.from_paths)."""
    n = len(t)
    t = np.sort(t)
    cdf = np.searchsorted(t, np.arange(1, horizon + 1), side="right") / n
    p_now = float(np.mean(t <= 0))
    median = float(t[(n + 1) // 2 - 1])
    if not np.isfinite(median):
        return StockoutResult(cdf, None, float(1.0 - cdf[-1]), p_now)
    window = max(cfg.min_window_h, cfg.window_share * median)
    return StockoutResult(cdf, median, float(np.mean(np.abs(t - median) <= window)), p_now)


def project_joint(cash0: float, em0: float, out_q: np.ndarray, in_q: np.ndarray,
                  cfg: StockoutConfig, dep: Dependence, rng: np.random.Generator,
                  refill: Refill | None = None) -> Joint:
    """Both floats from one set of joint demand paths. The refill draws come after the demand
    draws on the same generator, so the no-refill and refill-aware runs of one seed share
    their demand paths exactly."""
    d_out, d_in = sample_joint(out_q, in_q, dep, cfg.n_paths, rng)
    return run_paths(cash0, em0, d_out, d_in, cfg, refill, rng)


def run_paths(cash0: float, em0: float, d_out: np.ndarray, d_in: np.ndarray,
              cfg: StockoutConfig, refill: Refill | None = None,
              rng: np.random.Generator | None = None) -> Joint:
    horizon = d_out.shape[1]
    t_c, t_e, cp, ep = simulate(cash0, em0, d_out, d_in, cfg.floor_bdt, refill, rng)
    return Joint(from_times(t_c, horizon, cfg), from_times(t_e, horizon, cfg), cp, ep)
