"""Joint, coupled and refill-aware stockout projection (ml/inference/stockout_joint.py,
ml/inference/refill.py, ml/training/dependence.py). Pure numpy, no database."""

import numpy as np
import pytest
from scipy.special import ndtri

from ml.inference import refill, whatif
from ml.inference.stockout import StockoutConfig, project
from ml.inference.stockout_joint import (
    Dependence,
    Refill,
    run_paths,
    sample_joint,
    simulate,
)
from ml.training.dependence import estimate, pit

H = 24
FLAT = np.tile([600.0, 1000.0, 1400.0], (H, 1))  # q10 / q50 / q90, far from zero


def _scores(dep: Dependence, n: int = 20_000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    d_out, d_in = sample_joint(FLAT, FLAT, dep, n, np.random.default_rng(seed))
    rng = np.random.default_rng(1)
    q = np.tile(FLAT, (n, 1))  # row-major: path i, hour h -> FLAT[h]
    z = [ndtri(pit(d.ravel(), q, rng)).reshape(n, H) for d in (d_out, d_in)]
    return z[0], z[1]


def test_joint_sampling_has_the_requested_correlations() -> None:
    dep = Dependence(rho_out=0.5, rho_in=0.3, cross_path=0.6, cross_hour=0.4)
    z_out, z_in = _scores(dep)
    within_out = np.corrcoef(z_out[:, 3], z_out[:, 17])[0, 1]
    within_in = np.corrcoef(z_in[:, 3], z_in[:, 17])[0, 1]
    same_hour = np.corrcoef(z_out[:, 5], z_in[:, 5])[0, 1]
    expected = (np.sqrt(0.5 * 0.3) * 0.6 + np.sqrt(0.5 * 0.7) * 0.4)
    assert within_out == pytest.approx(0.5, abs=0.03)
    assert within_in == pytest.approx(0.3, abs=0.03)
    assert same_hour == pytest.approx(expected, abs=0.03)


def test_estimate_recovers_a_known_dependence() -> None:
    dep = Dependence(rho_out=0.45, rho_in=0.25, cross_path=0.5, cross_hour=0.3)
    z_out, z_in = _scores(dep, n=8_000, seed=4)
    ok = np.ones(z_out.shape, dtype=bool)
    ok[:, :3] = False  # closed hours are skipped, not counted as zeros
    got, n = estimate(z_out, z_in, ok)
    assert n == 8_000
    assert got.rho_out == pytest.approx(0.45, abs=0.04)
    assert got.rho_in == pytest.approx(0.25, abs=0.04)
    assert got.cross_path == pytest.approx(0.5, abs=0.07)
    assert got.cross_hour == pytest.approx(0.3, abs=0.04)


def test_pit_inverts_the_quantile_function_and_randomises_zeros() -> None:
    q = np.array([[0.0, 100.0, 300.0], [0.0, 100.0, 300.0], [50.0, 100.0, 300.0]])
    u = pit(np.array([100.0, 300.0, 50.0]), q, np.random.default_rng(0))
    np.testing.assert_allclose(u, [0.5, 0.9, 0.1])
    zeros = pit(np.zeros(4000), np.tile([0.0, 100.0, 300.0], (4000, 1)),
                np.random.default_rng(1))
    assert zeros.max() <= 0.1 + 1e-9 and zeros.mean() == pytest.approx(0.05, abs=0.005)


def test_first_stockout_is_the_hour_that_turns_customers_away() -> None:
    d_out = np.full((1, 4), 60.0)
    d_in = np.zeros((1, 4))
    t_cash, t_em, cash, em = simulate(100.0, 1.0, d_out, d_in, 0.0, None, None)
    assert t_cash[0] == pytest.approx(1 + 40 / 60)  # 40 of the second hour's 60 served
    assert np.isinf(t_em[0])
    np.testing.assert_allclose(cash[0], [40.0, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(em[0], [61.0, 101.0, 101.0, 101.0])  # only served cash-out moves
    t_cash0, _, _, _ = simulate(0.0, 1.0, d_out, d_in, 0.0, None, None)
    assert t_cash0[0] == 0.0  # already at the floor


def test_coupling_a_dry_float_stops_feeding_the_other() -> None:
    """Independent floats assume every cash-out tops up e-money; coupled, a dry cash float
    serves (and so passes on) only what it holds."""
    d_out = np.full((1, 6), 80.0)
    d_in = np.full((1, 6), 50.0)
    _, _, _, em = simulate(0.0, 100.0, d_out, d_in, 0.0, None, None)
    independent_em_end = 100.0 + 6 * (80.0 - 50.0)
    assert em[0, -1] == pytest.approx(100.0)
    assert em[0, -1] < independent_em_end


def test_refill_aware_is_never_earlier_and_zero_refill_changes_nothing() -> None:
    cfg = StockoutConfig(n_paths=500)
    out_q = np.tile([300.0, 500.0, 700.0], (H, 1))
    in_q = np.tile([50.0, 100.0, 150.0], (H, 1))
    d_out, d_in = sample_joint(out_q, in_q, Dependence(), cfg.n_paths, np.random.default_rng(2))
    base = run_paths(3000.0, 4000.0, d_out, d_in, cfg)
    none = run_paths(3000.0, 4000.0, d_out, d_in, cfg,
                     Refill(np.zeros(H), 20_000.0, 20_000.0), np.random.default_rng(3))
    np.testing.assert_array_equal(base.cash.cdf, none.cash.cdf)
    prob = np.zeros(H)
    prob[5] = 1.0
    sure = run_paths(3000.0, 4000.0, d_out, d_in, cfg, Refill(prob, 20_000.0, 20_000.0),
                     np.random.default_rng(3))
    assert (sure.cash.cdf <= base.cash.cdf + 1e-12).all()
    assert sure.cash.prob_within(H) < base.cash.prob_within(H)


def test_habits_read_weekly_refills_from_history_only() -> None:
    days, horizon = 50, 72
    t_total = days * 24 + horizon
    dow = (np.arange(t_total) // 24) % 7
    hod = np.arange(t_total) % 24
    served_out = np.full((1, t_total), 10.0)
    served_in = np.zeros((1, t_total))
    cash = np.full((1, t_total), 1000.0)
    em = np.full((1, t_total), 2000.0)
    n_refills = 0
    t0 = days * 24 - 1
    for t in range(1, t_total):  # the ledger moves the floats; the total stays the same
        cash[0, t], em[0, t] = cash[0, t - 1] - 10, em[0, t - 1] + 10
        if dow[t] == 2 and hod[t] == 9:  # refill every weekday 2 at 09:00 back to the targets
            cash[0, t], em[0, t] = 5000.0, 6000.0
            n_refills += t <= t0
    cash[0, t0 + 1:] = 1e9  # the future must not matter
    mask = refill.refill_mask(cash[:, :t0 + 1], served_in[:, :t0 + 1], served_out[:, :t0 + 1])
    assert mask.sum() == n_refills
    got = refill.habits(cash, em, served_in, served_out, dow, hod, t0, horizon)[0]
    assert got.prob[0] == 0.0
    for k in range(1, horizon):
        t = t0 + k
        assert got.prob[k] == (1.0 if (dow[t] == 2 and hod[t] == 9) else 0.0)
    assert got.cash_level == 5000.0 and got.emoney_level == 6000.0


def test_joint_what_if_before_equals_the_cached_projection() -> None:
    cfg = StockoutConfig(n_paths=400)
    out_q = np.tile([300.0, 500.0, 700.0], (72, 1))
    in_q = np.tile([100.0, 200.0, 300.0], (72, 1))
    dep = Dependence(0.4, 0.3, 0.2, 0.1)
    rng = np.random.default_rng([42, 7, 2])
    d_out, d_in = sample_joint(out_q, in_q, dep, cfg.n_paths, rng)
    cached = run_paths(5000.0, 6000.0, d_out, d_in, cfg)
    p = whatif.prepare_joint(5000.0, 6000.0, True, out_q, in_q, cfg, dep,
                             np.random.default_rng([42, 7, 2]))
    np.testing.assert_array_equal(p.before.result.cdf, cached.cash.cdf)
    more = whatif.after_joint(p, 10_000.0, cfg)
    assert (more.result.cdf <= p.before.result.cdf + 1e-12).all()
    assert more.bands.shape == (73, 3) and more.bands[0, 0] == 15_000.0


def test_old_single_float_method_still_available() -> None:
    cfg = StockoutConfig(n_paths=200)
    res = project(1000.0, np.tile([300.0, 500.0, 700.0], (H, 1)), np.zeros((H, 3)), cfg,
                  np.random.default_rng(0))
    assert res.prob_within(H) == 1.0 and res.hours is not None and res.hours < 3
