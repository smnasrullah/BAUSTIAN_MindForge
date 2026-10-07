"""Helper acceptance model (learned from SIMULATED behaviour) and its rule-bounded use."""

import json
import uuid
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.models.enums import UserRole
from app.rules.help_trigger_rules import learned_wave_size
from app.services.help_trigger import Ask, Pool
from ml.data_gen import helpers as sim
from ml.inference import helper_accept
from ml.inference.helper_accept import FEATURES, AcceptModel, at_least_one_yes, feature_row
from ml.registry import HELPER_FILE, HELPER_MANIFEST, sha256_file
from ml.training import helper_accept as train_helper

TRUE_W = np.array([-0.5, 0.3, -1.0, -0.4, 0.6, -0.1, 1.5, 0.2])
TRUE_B = -0.4


def _rows(n: int, seed: int) -> list[dict[str, float]]:
    """Feature rows with labels drawn from a known logistic law."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        x = feature_row(rng.uniform(0, 5), int(rng.integers(8, 21)), int(rng.poisson(1.5)),
                        rng.uniform(1, 6) * 10_000, 10_000, int(rng.integers(1, 4)),
                        int(rng.poisson(4)), 0)
        x[6] = rng.uniform(0.1, 0.9)  # reliability
        p = 1 / (1 + np.exp(-(np.dot(TRUE_W, x) + TRUE_B)))
        out.append({**dict(zip(FEATURES, x, strict=True)), "y": float(rng.random() < p),
                    "p_true": float(p)})
    return out


def test_acceptance_model_is_calibrated_on_a_known_law() -> None:
    model = train_helper.fit(_rows(20_000, 1), _rows(5_000, 2), "t")
    blind = train_helper.scores(model, _rows(10_000, 3))
    assert blind["ece"] < 0.03
    assert blind["brier"] - blind["brier_true_law"] < 0.005  # close to the best possible
    assert abs(blind["mean_p"] - blind["yes_rate"]) < 0.02
    assert blind["auc"] > 0.65


def test_learned_wave_size_stays_inside_the_rule_cap() -> None:
    assert learned_wave_size([0.95, 0.5], cap=5, target=0.9) == 1
    assert learned_wave_size([0.5, 0.5, 0.5, 0.5], cap=5, target=0.9) == 4  # 1 - 0.5^4 >= 0.9
    assert learned_wave_size([0.1] * 10, cap=5, target=0.9) == 5  # never above the cap
    assert learned_wave_size([0.1, 0.1], cap=5, target=0.9) == 2  # never more than offered
    assert learned_wave_size([], cap=5, target=0.9) == 0
    assert at_least_one_yes([0.5, 0.5]) == pytest.approx(0.75)


def _world() -> sim.World:
    n, t = 6, 48
    lat = np.array([23.80, 23.801, 23.805, 23.82, 23.80, 23.95])
    lng = np.array([90.40, 90.401, 90.405, 90.40, 90.43, 90.40])
    dist = np.array(["D1"] * 5 + ["D2"])
    km = sim._km(lat, lng)
    km[dist[:, None] != dist[None, :]] = np.inf
    cash = np.full((n, t), 80_000.0)
    cash[0] = 1_000.0  # the requester
    return sim.World(seed=1, lat=lat, lng=lng, distributor=dist, tier=np.array([1, 2, 3, 2, 1, 2]),
                     cash=cash, emoney=cash.copy(), cash_cap=np.full(n, 100_000.0),
                     emoney_cap=np.full(n, 100_000.0), propensity=np.zeros(n),
                     opted_out=np.array([False, False, False, True, False, False]), km=km,
                     behaviour=sim.Behaviour())


def test_learned_order_only_reorders_the_rule_feasible_set() -> None:
    w = _world()
    req = sim.Request(0, 10, 0, "cash", 20_000.0)
    state = sim.HelperState()
    pool = sim.feasible(w, req, state, set())
    rows = {c.row for c in pool}
    assert rows == {1, 2, 4}  # opted out (3), other distributor (5) and the requester excluded
    model = AcceptModel("t", FEATURES, np.zeros(len(FEATURES)), np.ones(len(FEATURES)),
                        np.array([-1.0, 0, 0, 0, 0, 0, 0, 0]), 0.0)
    ranked = train_helper.learned(model)(w, req, pool, state)
    assert {c.row for c in ranked} == rows
    assert [c.row for c in ranked] == [c.row for c in sorted(pool, key=lambda c: c.distance_km)]
    state.record(1, 9.5, False)  # asked 30 min ago: the recent-ask rule leaves it out
    assert {c.row for c in sim.feasible(w, req, state, set())} == {2, 4}


def test_ask_window_and_weekly_maximum() -> None:
    s = sim.HelperState()
    for t in (0.0, 10.0, 170.0):
        s.record(7, t, True)
    assert s.asks_in_window(7, 180.0) == 1  # asks older than 7 days drop out
    assert train_helper._max_week([0.0, 10.0, 20.0, 200.0]) == 3


def test_load_rejects_a_tampered_artifact(tmp_path: Path) -> None:
    model = train_helper.fit(_rows(2_000, 4), _rows(500, 5), "t")
    (tmp_path / HELPER_FILE).write_text(json.dumps(model.to_json()), encoding="utf-8")
    manifest = {"model_version": "helper-test", "files": {
        HELPER_FILE: sha256_file(tmp_path / HELPER_FILE)}}
    (tmp_path / HELPER_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    loaded = helper_accept.load(tmp_path)
    assert loaded is not None and loaded.version == "helper-test"
    x = np.array([feature_row(1.0, 12, 0, 50_000, 10_000, 2, 3, 2)])
    np.testing.assert_allclose(loaded.predict(x), model.predict(x))
    (tmp_path / HELPER_FILE).write_text(json.dumps(model.to_json()) + " ", encoding="utf-8")
    assert helper_accept.load(tmp_path) is None


def test_pool_wave_uses_learned_size_only_when_switched_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asks = [Ask(uuid.uuid4(), f"A{i}", UserRole.agent, 1.0) for i in range(5)]
    pool = Pool([], asks, [0.95, 0.5, 0.5, 0.5, 0.5])
    monkeypatch.setenv("HELP_WAVE_SIZING", "false")
    get_settings.cache_clear()
    assert pool.wave(5) == asks
    monkeypatch.setenv("HELP_WAVE_SIZING", "true")
    get_settings.cache_clear()
    assert pool.wave(5) == asks[:1]  # 0.95 >= 0.9 already
    assert Pool([], asks, None).wave(3) == asks[:3]  # no model numbers: the rule cap
    get_settings.cache_clear()
