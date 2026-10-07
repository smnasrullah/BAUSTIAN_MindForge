import pytest

from app.rules.van_routing.cost import EPS
from app.rules.van_routing.models import VanConfig
from app.services import van_geometry
from ml.van import backtest


@pytest.mark.slow
def test_policies_on_held_out_days() -> None:
    """Policies A-D on the held-out synthetic days (oracle needs; routing quality only)."""
    cfg = VanConfig()
    r = backtest.run(42, cfg, van_geometry.load().legs)
    assert r["label"] == "synthetic data" and r["instances"] > 0 and r["stops"] > 0
    p = r["policies"]
    a, b, c, d = (p[k] for k in ("A_separate_trips", "B_nearest_neighbour", "C_hard_deadline",
                                 "D_full_model"))
    # The full model never costs more in total than one trip per agent, and saves van cost.
    assert d["total_bdt"] <= a["total_bdt"] + EPS
    assert d["van_bdt"] < a["van_bdt"] and d["trips"] < a["trips"]
    # Its BDT objective is at least as good as the simple heuristics on the same inputs.
    assert d["total_bdt"] <= b["total_bdt"] + EPS
    assert d["total_bdt"] <= c["total_bdt"] + EPS
    assert d["solve_ms_max"] < cfg.time_limit_s * 1000
    for pol in p.values():
        assert 0 <= pol["deadline_hit_rate"] <= pol["service_rate"] <= 1
