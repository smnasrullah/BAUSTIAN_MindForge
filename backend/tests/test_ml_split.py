"""Leakage tests for the train / validation / blind-test split (ml/training/splits.py).

No database: panels and series are built in memory on the fixed timeline.
"""

from datetime import timedelta

import lightgbm as lgb
import numpy as np
import pytest

from ml.data_gen.timeline import HOLDOUT_START, N_HOURS, VAL_START, hour_index
from ml.features.anomaly import WINDOW_H, Series
from ml.features.build import FEATURES, MAX_HORIZON_H, build, grid
from ml.features.panel import N_EVENT_FEATURES, Panel
from ml.training import anomaly as anomaly_train
from ml.training import train
from ml.training.evaluate import holdout_grid
from ml.training.splits import FIXED_SPLIT, LeakageError, Split

N_DAYS = N_HOURS // 24


def _panel(n: int = 4, seed: int = 0) -> Panel:
    rng = np.random.default_rng(seed)
    hours = np.arange(N_HOURS)
    return Panel(
        agent_ids=np.arange(1, n + 1), tier=np.ones(n), area=np.zeros(n),
        district=np.zeros(n, dtype=np.int64), cash_cap=np.full(n, 1e5),
        emoney_cap=np.full(n, 1e5), districts=["d"],
        demand={t: rng.gamma(2.0, 500.0, (n, N_HOURS)) for t in ("cash_out", "cash_in")},
        events=np.zeros((1, N_EVENT_FEATURES, N_HOURS)), rain_mm=np.zeros((1, N_DAYS)),
        temp_c=np.full((1, N_DAYS), 25.0), hour=(hours % 24).astype(float),
        dow=((hours // 24) % 7).astype(float), dom=((hours // 24) % 28 + 1).astype(float))


def test_fixed_split_is_train_then_14_validation_days_then_holdout() -> None:
    assert FIXED_SPLIT.train_end == hour_index(VAL_START)
    assert FIXED_SPLIT.val_end == hour_index(HOLDOUT_START)
    assert FIXED_SPLIT.val_end - FIXED_SPLIT.train_end == 14 * 24
    assert timedelta(days=14) == HOLDOUT_START - VAL_START
    with pytest.raises(ValueError):
        Split(100, 50, N_HOURS)


def test_training_targets_end_before_validation() -> None:
    rows, origins, hs = train.sample_rows(5, FIXED_SPLIT.train_end, seed=3)
    targets = origins + hs - 1
    assert len(rows) > 0 and int(targets.max()) < FIXED_SPLIT.train_end
    FIXED_SPLIT.check_train(targets)
    with pytest.raises(LeakageError):
        FIXED_SPLIT.check_train(np.array([FIXED_SPLIT.val_end]))


def test_selection_grid_lies_inside_validation_only() -> None:
    _, origins, hs = holdout_grid(3, FIXED_SPLIT.train_end, FIXED_SPLIT.val_end)
    targets = origins + hs - 1
    FIXED_SPLIT.check_validation(targets)
    assert int(targets.min()) == FIXED_SPLIT.train_end + 8  # first origin 08:00, horizon 1
    assert int(targets.max()) < FIXED_SPLIT.val_end
    with pytest.raises(LeakageError):
        FIXED_SPLIT.check_validation(np.array([FIXED_SPLIT.val_end + 1]))
    _, o2, h2 = holdout_grid(3, FIXED_SPLIT.val_end, N_HOURS)
    FIXED_SPLIT.check_test(o2 + h2 - 1)


def test_features_use_no_demand_at_or_after_the_origin() -> None:
    panel = _panel()
    t0 = FIXED_SPLIT.train_end + 13
    rows, origins, hs = grid(len(panel.agent_ids), t0, MAX_HORIZON_H)
    before = {t: build(panel, t, rows, origins, hs)[0] for t in panel.demand}
    for y in panel.demand.values():
        y[:, t0:] = 1e9  # any leak of the future would show in the features
    for t, x in before.items():
        np.testing.assert_array_equal(build(panel, t, rows, origins, hs)[0], x)
    assert x.shape[1] == len(FEATURES)


def _series(n: int = 12, seed: int = 1) -> Series:
    rng = np.random.default_rng(seed)
    out = rng.gamma(2.0, 400.0, (n, N_HOURS))
    inn = rng.gamma(2.0, 400.0, (n, N_HOURS))
    total = np.full((n, N_HOURS), 1e5)
    return Series(agent_ids=np.arange(1, n + 1), codes=[f"A{i}" for i in range(n)],
                  groups=["all"] * n, cash_out=out, cash_in=inn, total=total)


def test_anomaly_validation_blocks_end_before_the_holdout() -> None:
    blocks = anomaly_train.cv_blocks(FIXED_SPLIT)
    assert len(blocks) == anomaly_train.CV_FOLDS
    for b0, b1 in blocks:
        assert b1 <= FIXED_SPLIT.val_end
        assert max(anomaly_train.fit_ends(b0)) <= b0
        ends = anomaly_train.inside_ends(b0, b1)
        assert min(ends) - WINDOW_H >= b0 and max(ends) <= b1


def test_contamination_is_chosen_without_the_holdout(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _series()
    first = FIXED_SPLIT.val_end - 14 * 24
    # One labelled anomaly in the last validation block, one in the blind test.
    spans = {"A0": [(first + 24, first + 24 * 8, "volume_burst")],
             "A1": [(FIXED_SPLIT.val_end + 24, FIXED_SPLIT.val_end + 24 * 8, "volume_burst")]}
    seen: list[int] = []
    real = anomaly_train.truth

    def spy(s_: Series, spans_: anomaly_train.Spans, rows: np.ndarray, end_of: np.ndarray
            ) -> tuple[np.ndarray, np.ndarray, list[str | None]]:
        seen.append(int(end_of.max()))
        return real(s_, spans_, rows, end_of)

    monkeypatch.setattr(anomaly_train, "truth", spy)
    chosen, table = anomaly_train.select_contamination(s, 42, spans, FIXED_SPLIT)
    assert seen and max(seen) <= FIXED_SPLIT.val_end
    assert chosen in anomaly_train.CONTAMINATION_GRID
    assert table["positives"] > 0


def test_explained_booster_stays_inside_the_serving_budget() -> None:
    """q50 is explained by TreeSHAP on every live tick: its leaves x rounds are capped;
    the other quantiles may use the whole grid."""
    rng = np.random.default_rng(0)
    x = rng.normal(size=(3000, 3))
    y = x[:, 0] + rng.normal(size=3000)
    data = lgb.Dataset(x, label=y, free_raw_data=False)
    xv, sv, yv = x[:500], np.ones(500), y[:500]
    for q in (0.1, 0.5):
        _, trials = train._select(data, xv, sv, yv, q, seed=1, rounds=300)
        sizes = {t["num_leaves"] * t["rounds"] for t in trials}
        if q == train.EXPLAINED_QUANTILE:
            assert max(sizes) <= train.EXPLAIN_BUDGET_LEAF_ROUNDS
        else:
            assert max(sizes) > train.EXPLAIN_BUDGET_LEAF_ROUNDS
