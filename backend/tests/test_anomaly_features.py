"""Anomaly window features + peer evidence on hand-made series (exact answers)."""

import numpy as np
import pytest

from ml.explain.anomaly_evidence import evidence, percentile_rank
from ml.features.anomaly import (
    BURST_FEATURES,
    GLOBAL_GROUP,
    HISTORY_H,
    LEDGER_FEATURES,
    LEGACY_FEATURES,
    MIN_PEERS,
    WINDOW_H,
    FeatureSpec,
    Series,
    assign_groups,
    day_ratios,
    hour_shift,
    ledger_refill_count,
    refill_count,
    robust_z,
    window_features,
)

END = WINDOW_H + HISTORY_H
N = 12  # agents; row 0 is the odd one
RAW = FeatureSpec(LEGACY_FEATURES).raw_names
LEDGER_ALL = FeatureSpec(LEDGER_FEATURES + BURST_FEATURES, burst_k=2.0)


def _series() -> Series:
    """Twelve agents trading 1,000 BDT each way every daytime hour; agent 0 turns nocturnal and
    is refilled every day of the window."""
    hours = np.arange(END)
    day = ((hours % 24) >= 9) & ((hours % 24) < 21)
    flow = np.tile(np.where(day, 1_000.0, 0.0), (N, 1))
    out, inn = flow.copy(), flow.copy()
    night = ~day & (hours >= END - WINDOW_H)
    out[0, night] += 5_000
    inn[0, night] += 1_000
    total = np.full((N, END), 100_000.0)
    # Cash follows the ledger (in - out of the previous hour) plus one refill per window day.
    cash = 50_000.0 + np.concatenate([np.zeros((N, 1)), np.cumsum(inn - out, axis=1)[:, :-1]],
                                     axis=1)
    for d in range(7):
        total[0, END - WINDOW_H + 24 * d:] += 20_000  # step up = one refill per day
        cash[0, END - WINDOW_H + 24 * d:] += 20_000
    return Series(agent_ids=np.arange(1, N + 1), codes=[f"A{i}" for i in range(N)],
                  groups=["g"] * N, cash_out=out, cash_in=inn, total=total, cash=cash)


def test_refill_count_ignores_rounding_and_gaps() -> None:
    total = np.array([[100.0, 101.0, 5_000.0, 5_000.0, np.nan, 5_000.0]])
    assert refill_count(total).tolist() == [1]


def test_ledger_refills_ignore_explained_moves_and_gaps() -> None:
    # 100 -> 400 is explained by 300 cash-in; 400 -> 9,000 is not; nan never counts.
    cash = np.array([[100.0, 400.0, 9_000.0, np.nan, 9_000.0]])
    served_in = np.array([[300.0, 0.0, 0.0, 0.0, 0.0]])
    assert ledger_refill_count(cash, served_in, np.zeros_like(cash)).tolist() == [1]


def test_ledger_rule_finds_refills_the_total_rule_misses() -> None:
    """A refill that resets both floats can leave cash + e-money unchanged."""
    s = _series()
    s.total[:] = 100_000.0
    legacy = window_features(s, END, FeatureSpec(LEGACY_FEATURES))
    ledger = window_features(s, END, FeatureSpec(LEDGER_FEATURES))
    assert legacy.refills.tolist() == [0] * N
    assert ledger.refills.tolist() == [7] + [0] * (N - 1)
    assert ledger.names == ("cash_out_growth", "hour_shift", "refills_per_day",
                            "out_in_log_ratio")


def test_ledger_inputs_need_cash_balances() -> None:
    s = _series()
    s.cash = None
    with pytest.raises(ValueError):
        window_features(s, END, FeatureSpec(LEDGER_FEATURES))


def test_burst_measures_compare_each_day_with_the_same_weekday() -> None:
    s = _series()
    w0 = END - WINDOW_H
    s.cash_out[1, w0 + 48:w0 + 120] *= 4  # agent 1: three days at 4x
    s.cash_in[1, w0 + 48:w0 + 120] *= 4
    ratio = day_ratios(s.cash_out + s.cash_in, END)
    assert ratio.shape == (N, 8)
    assert ratio[2:].max() == pytest.approx(1.0) and ratio[2:].min() == pytest.approx(1.0)
    w = window_features(s, END, LEDGER_ALL)
    raw = dict(zip(w.names, w.raw.T, strict=True))
    usual = 24_000.0  # 12 daytime hours x 1,000 BDT each way
    peak = (4 * usual + 1_000) / (usual + 1_000)
    assert raw["burst_peak_ratio"][1] == pytest.approx(peak)
    assert raw["burst_days"][1] == 3 and raw["burst_days"][2:].max() == 0
    assert raw["rate_change"][1] == pytest.approx(peak)
    assert raw["rate_change"][2:].max() == pytest.approx(1.0)
    col = list(LEDGER_ALL.features).index("burst_days_peer_z")
    assert w.x[1, col] > 2 and w.x[2:, col].max() == pytest.approx(0)


def test_feature_spec_rejects_unknown_inputs_and_two_refill_rules() -> None:
    with pytest.raises(ValueError):
        FeatureSpec(("cash_out_peer_z", "made_up"))
    with pytest.raises(ValueError):
        FeatureSpec(("refills_peer_z", "ledger_refills_peer_z"))
    assert FeatureSpec().features == LEGACY_FEATURES and not FeatureSpec().ledger


def test_hour_shift_zero_for_same_shape_and_one_for_disjoint() -> None:
    a = np.zeros((2, 24))
    b = np.zeros((2, 24))
    a[:, 10], b[0, 10], b[1, 2] = 1, 7, 3
    assert hour_shift(a, b) == pytest.approx([0.0, 1.0])
    assert hour_shift(np.zeros((1, 24)), b[:1]).tolist() == [0.0]


def test_robust_z_is_per_group_with_floor() -> None:
    v = np.array([1.0, 1.0, 1.0, 2.0, 10.0, 20.0, 30.0])
    g = np.array(["a", "a", "a", "a", "b", "b", "b"])
    z = robust_z(v, g)
    assert z[3] == pytest.approx(1 / 0.05)  # MAD 0 -> spread floored
    assert z[4:].tolist() == pytest.approx([-10 / (1.4826 * 10), 0.0, 10 / (1.4826 * 10)])


def test_small_groups_fall_back_to_global() -> None:
    keys = ["t1-urban"] * MIN_PEERS + ["t3-rural"] * (MIN_PEERS - 1)
    groups = assign_groups(keys)
    assert set(groups[:MIN_PEERS]) == {"t1-urban"}
    assert set(groups[MIN_PEERS:]) == {GLOBAL_GROUP}


def test_window_features_single_out_the_odd_agent() -> None:
    w = window_features(_series(), END)
    raw = dict(zip(RAW, w.raw.T, strict=True))
    assert raw["refills_per_day"][0] == 1 and raw["refills_per_day"][1:].max() == 0
    assert raw["hour_shift"][0] > 0.3 and raw["hour_shift"][1:].max() == pytest.approx(0)
    assert raw["cash_out_growth"][0] > 1 and raw["out_in_log_ratio"][0] > 0.5
    # Model inputs are peer z-scores; the eleven ordinary agents sit at 0.
    assert (w.x[0] > 2).all() and np.abs(w.x[1:]).max() == pytest.approx(0)
    assert w.refills[0] == 7 and w.cash_out_bdt[0] > w.baseline_cash_out_bdt[0]


def test_window_needs_full_history() -> None:
    with pytest.raises(ValueError):
        window_features(_series(), END - 1)


def test_evidence_lists_peer_distribution_and_reasons() -> None:
    w = window_features(_series(), END)
    score = np.r_[0.8, np.full(N - 1, 0.4)]
    ev = evidence(w, score, np.full(N, 0.6), np.array(["g"] * N), 0)
    assert (ev["peer_group"], ev["peer_count"], ev["threshold"]) == ("g", N, 0.6)
    assert [f["name"] for f in ev["features"]] == list(RAW)
    refills = next(f for f in ev["features"] if f["name"] == "refills_per_day")
    # 11 peers below, itself counted half: 11.5 / 12.
    assert (refills["value"], refills["p50"], refills["percentile"]) == (1, 0, 95.8)
    assert 1 <= len(ev["reasons"]) <= 3
    assert all(r["direction"] == "high" and r["deviation"] >= 2 for r in ev["reasons"])
    assert ev["peer_scores"] == {"p50": 0.4, "p90": 0.4, "max": 0.8}
    assert ev["context"]["refills"] == 7


def test_percentile_rank_counts_ties_half() -> None:
    assert percentile_rank(np.array([1.0, 2.0, 2.0, 3.0]), 2.0) == 50.0
