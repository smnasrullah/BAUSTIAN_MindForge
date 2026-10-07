"""Conformal band calibration (ml/inference/conformal.py) on synthetic data with known truth."""

import numpy as np
import pytest

from ml.inference.conformal import (
    TAIL,
    TIER_REGION_AREA,
    Conformal,
    cell_codes,
    cell_name,
    conformal_quantile,
    fit_target,
    region_cell_codes,
    region_fallbacks,
)
from ml.training.band_cells import group_gap


def _fit(y: np.ndarray, pred: np.ndarray, scale: np.ndarray, groups: tuple[np.ndarray, ...]
         ) -> Conformal:
    return Conformal(TAIL, {"t": fit_target(y, pred, scale, *groups)})


def _world(n: int, band_z: float, seed: int) -> tuple[np.ndarray, ...]:
    """y = scale * (mu + sigma * N(0, 1)); the model's band is +-band_z sigma (true: +-1.28)."""
    rng = np.random.default_rng(seed)
    tier = rng.integers(1, 4, n).astype(float)
    area = rng.integers(0, 3, n).astype(float)
    hs = rng.integers(1, 73, n)
    scale = rng.uniform(100, 5000, n)
    sigma = 0.3 + 0.2 * tier + 0.1 * area  # spread differs per group
    mu = 3.0
    y = scale * (mu + sigma * rng.standard_normal(n))
    pred = np.column_stack([scale * (mu - band_z * sigma), scale * mu,
                            scale * (mu + band_z * sigma)])
    return y, pred, scale, (tier, area, hs), tier


@pytest.mark.parametrize("band_z", [0.6, 2.5])  # too narrow, too wide
def test_calibrated_band_covers_80_percent_in_every_group(band_z: float) -> None:
    y, pred, scale, groups, tier = _world(60_000, band_z, seed=1)
    cal = _fit(y, pred, scale, groups)
    y2, pred2, scale2, groups2, tier2 = _world(60_000, band_z, seed=2)
    out = cal.apply("t", pred2, scale2, *groups2)
    hit = (y2 >= out[:, 0]) & (y2 <= out[:, 2])
    assert abs(hit.mean() - 0.80) < 0.015
    for t in (1, 2, 3):
        assert abs(hit[tier2 == t].mean() - 0.80) < 0.025
    assert np.mean(y2 < out[:, 0]) < TAIL + 0.015
    assert np.mean(y2 > out[:, 2]) < TAIL + 0.015
    before = np.mean((y2 >= pred2[:, 0]) & (y2 <= pred2[:, 2]))
    assert abs(before - 0.80) > 0.1  # the raw band really was off


def test_calibrated_band_is_ordered_and_non_negative() -> None:
    pred = np.array([[0.0, 10.0, 20.0], [5.0, 6.0, 7.0], [1.0, 1.0, 1.0]])
    groups = (np.ones(3), np.zeros(3), np.array([1, 10, 30]))
    codes = cell_codes(*groups, pred[:, 2])
    narrow = Conformal(TAIL, {"t": {int(c): (-50.0, -50.0) for c in codes}})
    wide = Conformal(TAIL, {"t": {int(c): (50.0, 50.0) for c in codes}})
    for cal in (narrow, wide):
        out = cal.apply("t", pred, np.ones(3), *groups)
        assert (out[:, 0] >= 0).all()
        assert (out[:, 0] <= out[:, 1]).all() and (out[:, 1] <= out[:, 2]).all()
        np.testing.assert_array_equal(out[:, 1], pred[:, 1])


def test_unknown_cell_uses_pooled_bucket_offset_and_json_round_trip() -> None:
    y, pred, scale, groups, _ = _world(5_000, 1.0, seed=3)
    cal = _fit(y, pred, scale, groups)
    back = Conformal.from_json(cal.to_json())
    assert back == cal
    pooled = cal.offsets["t"][2]  # open hours, bucket 25-72 h
    out = back.apply("t", np.array([[10.0, 20.0, 30.0]]), np.array([1.0]), np.array([9.0]),
                     np.array([9.0]), np.array([30]))
    assert out[0, 2] == pytest.approx(max(30.0 + pooled[1], 20.0))
    assert cell_name(int(cell_codes(*groups, pred[:, 2])[0])).startswith("open|t")
    assert cell_name(2) == "open|all|h25-72"
    assert cell_name(1002) == "closed|all|h25-72"


def test_closed_hours_get_their_own_cell() -> None:
    """Zero forecasts with zero demand tie every score at 0; in a cell of their own they no
    longer stop the open hours' band from narrowing."""
    rng = np.random.default_rng(5)
    n = 20_000
    open_y = rng.normal(100.0, 10.0, n)
    wide = np.column_stack([np.full(n, 50.0), np.full(n, 100.0), np.full(n, 150.0)])
    closed_pred = np.zeros((n, 3))
    y = np.concatenate([open_y, np.zeros(n)])
    pred = np.vstack([wide, closed_pred])
    groups = (np.ones(2 * n), np.zeros(2 * n), np.full(2 * n, 3))
    cal = _fit(y, pred, np.ones(2 * n), groups)
    out = cal.apply("t", pred, np.ones(2 * n), *groups)
    hit = (y[:n] >= out[:n, 0]) & (y[:n] <= out[:n, 2])
    assert abs(hit.mean() - 0.80) < 0.02  # narrowed from ~100% to 80%
    np.testing.assert_array_equal(out[n:], 0.0)


def test_conformal_quantile_finite_sample_rank() -> None:
    s = np.arange(1.0, 10.0)  # n = 9: rank ceil(10 * 0.9) = 9 -> the maximum
    assert conformal_quantile(s, 0.1) == 9.0
    s = np.arange(1.0, 101.0)  # n = 100: rank ceil(101 * 0.9) = 91
    assert conformal_quantile(s, 0.1) == 91.0
    assert conformal_quantile(np.array([]), 0.1) == 0.0


def test_region_cells_fix_a_region_the_tier_area_cells_cannot_see() -> None:
    """Region 3 is twice as noisy as the others: tier x area cells pool it with calm regions
    and under-cover it; region cells cover every region."""
    rng = np.random.default_rng(7)

    def world(n: int) -> tuple[np.ndarray, ...]:
        tier, area = np.ones(n), np.zeros(n)
        region = rng.integers(1, 4, n)
        hs = np.full(n, 10)
        sigma = np.where(region == 3, 2.0, 1.0)
        y = 10.0 + sigma * rng.standard_normal(n)
        pred = np.column_stack([np.full(n, 9.0), np.full(n, 10.0), np.full(n, 11.0)])
        return y, pred, np.ones(n), tier, area, hs, region

    y, pred, scale, tier, area, hs, region = world(30_000)
    plain = Conformal(TAIL, {"t": fit_target(y, pred, scale, tier, area, hs)})
    regional = Conformal(TAIL, {"t": fit_target(y, pred, scale, tier, area, hs, TAIL, region)},
                         {"t": TIER_REGION_AREA})
    y2, pred2, scale2, tier2, area2, hs2, region2 = world(30_000)
    labels = {"region": region2}
    gap_plain, cov_plain = group_gap(y2, plain.apply("t", pred2, scale2, tier2, area2, hs2),
                                     labels)
    gap_reg, cov_reg = group_gap(y2, regional.apply("t", pred2, scale2, tier2, area2, hs2,
                                                    region2), labels)
    assert cov_plain["region"]["3"] < 0.70 and gap_plain > 0.1
    assert gap_reg < 0.03 and min(cov_reg["region"].values()) > 0.77
    assert Conformal.from_json(regional.to_json()) == regional
    with pytest.raises(ValueError):
        regional.apply("t", pred2, scale2, tier2, area2, hs2)  # region missing


def test_region_cells_fall_back_to_any_region_then_pooled() -> None:
    code = int(region_cell_codes(np.array([2]), np.array([3]), np.array([1]), np.array([30]),
                                 np.array([5.0]))[0])
    assert code == 2312 and region_fallbacks(code) == (2312, 2012, 2)
    assert cell_name(2312, TIER_REGION_AREA) == "open|t2-r3-a1|h25-72"
    assert cell_name(2012, TIER_REGION_AREA) == "open|t2-rany-a1|h25-72"
    cal = Conformal(TAIL, {"t": {2012: (0.0, 5.0), 2: (0.0, 1.0)}}, {"t": TIER_REGION_AREA})
    one = np.array([[1.0, 2.0, 3.0]])
    out = cal.apply("t", one, np.ones(1), np.array([2]), np.array([1]), np.array([30]),
                    np.array([3]))
    assert out[0, 2] == 8.0  # tier-area cell in any region
    out = cal.apply("t", one, np.ones(1), np.array([3]), np.array([1]), np.array([30]),
                    np.array([3]))
    assert out[0, 2] == 4.0  # pooled


def test_old_calibration_files_still_load_as_tier_area() -> None:
    blob = {"tail": 0.1, "offsets": {"cash_in": {"2": [0.5, 0.5]}}}
    cal = Conformal.from_json(blob)
    assert cal.scheme("cash_in") == "tier-area" and cal.schemes == {}
    with pytest.raises(ValueError):
        Conformal.from_json(blob | {"schemes": {"cash_in": "by-moon"}})
