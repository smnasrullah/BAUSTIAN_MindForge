"""What-if projection: shares the cache's paths, and a positive delta never worsens anything."""

import numpy as np
import pytest

from ml.inference import whatif
from ml.inference.stockout import StockoutConfig, project

H = 72
CFG = StockoutConfig(n_paths=500)


def rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def _quantiles(r: np.random.Generator, scale: float) -> np.ndarray:
    mid = r.uniform(0.5, 1.5, H) * scale
    return np.column_stack([mid * r.uniform(0.2, 0.9, H), mid, mid * r.uniform(1.1, 2.5, H)])


def test_before_reproduces_the_cached_projection() -> None:
    drain, inflow = _quantiles(rng(1), 1000), _quantiles(rng(2), 300)
    before, _ = whatif.run(20_000, 5_000, drain, inflow, CFG, rng())
    cached = project(20_000, drain, inflow, CFG, rng())
    np.testing.assert_array_equal(before.result.cdf, cached.cdf)
    assert before.result.hours == cached.hours
    assert before.result.confidence == cached.confidence


@pytest.mark.parametrize("seed", range(8))
def test_positive_delta_never_worsens(seed: int) -> None:
    r = rng(100 + seed)
    drain, inflow = _quantiles(r, r.uniform(300, 2000)), _quantiles(r, r.uniform(0, 800))
    b0 = float(r.uniform(0, 40_000))
    for delta in (0.0, 1.0, 500.0, 5_000.0, 50_000.0):
        before, after = whatif.run(b0, delta, drain, inflow, CFG, rng(seed))
        assert np.all(after.result.cdf <= before.result.cdf)
        assert after.result.p_now <= before.result.p_now
        hb = np.inf if before.result.hours is None else before.result.hours
        ha = np.inf if after.result.hours is None else after.result.hours
        assert ha >= hb
        assert np.all(after.bands >= before.bands)


def test_bands_start_at_balance_and_floor_at_zero() -> None:
    drain = np.tile([500.0, 1000.0, 1500.0], (H, 1))
    before, after = whatif.run(5_000, 3_000, drain, np.zeros((H, 3)), CFG, rng())
    assert before.bands.shape == (H + 1, 3)
    np.testing.assert_array_equal(before.bands[0], [5_000] * 3)
    np.testing.assert_array_equal(after.bands[0], [8_000] * 3)
    assert before.bands.min() == 0 and np.all(np.diff(before.bands[:, 1]) <= 0)
    assert before.result.by_hour()[0] == 0.0 and len(before.result.by_hour()) == H + 1


def test_empty_float_is_stocked_out_now() -> None:
    before, after = whatif.run(0, 10_000, np.ones((H, 3)) * 100, np.zeros((H, 3)), CFG, rng())
    assert before.result.p_now == 1.0 and before.result.hours == 0.0
    # 10,000 drained at 100/h lasts 100 h, past the 72 h horizon.
    assert after.result.p_now == 0.0 and after.result.hours is None


def test_prepared_paths_give_the_same_answer_as_run() -> None:
    """The API reuses prepare() across slider moves; it must match a fresh run() exactly."""
    drain, inflow = _quantiles(rng(3), 900), _quantiles(rng(4), 250)
    paths = whatif.prepare(15_000, drain, inflow, CFG, rng(7))
    for delta in (0.0, 2_500.0, 30_000.0, -10_000.0):
        before, after = whatif.run(15_000, delta, drain, inflow, CFG, rng(7))
        cached_after = whatif.after(paths, delta, CFG)
        np.testing.assert_array_equal(paths.before.result.cdf, before.result.cdf)
        np.testing.assert_array_equal(cached_after.result.cdf, after.result.cdf)
        np.testing.assert_array_equal(cached_after.bands, after.bands)
        assert cached_after.result.hours == after.result.hours
