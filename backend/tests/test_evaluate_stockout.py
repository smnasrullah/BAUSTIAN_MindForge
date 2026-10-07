import numpy as np

from ml.training.evaluate_stockout import evaluate_stockout


def test_alert_metrics_on_a_hand_built_case() -> None:
    # 1 agent, 2 floats, 48 h; cash runs short in hour 10; rounds at hours 0 and 8.
    unmet = np.zeros((2, 1, 48))
    unmet[0, 0, 10] = 5.0
    rounds = np.array([0, 8])
    p = np.full((2, 1, 2), 0.05)
    p[0, 0, 0] = 0.9  # round 0 alerts cash (realised within 24 h); lead time 10 h
    p[1, 0, 1] = 0.9  # round 1 alerts e-money (never short): a false alert
    res = evaluate_stockout({24: p}, rounds, unmet, {24: 0.2}, 48)["24"]
    assert (res["tp"], res["fp"], res["fn"]) == (1, 1, 1)  # round 1 cash is missed
    assert res["precision"] == 0.5 and res["recall"] == 0.5
    assert res["mean_lead_time_h"] == 10.0
    assert res["false_alerts_per_agent_week"] == round(1 / (48 / 168), 4)
    assert res["brier"] > 0


def test_residual_correlation_recovers_a_shared_factor() -> None:
    from scipy.special import ndtr

    from ml.inference.stockout import demand_quantile
    from ml.training.rho_sensitivity import normal_scores, residual_correlation

    rng = np.random.default_rng(0)
    n, h, rho = 4000, 6, 0.6
    z = np.sqrt(rho) * rng.standard_normal((n, 1)) + np.sqrt(1 - rho) * rng.standard_normal((n, h))
    q = np.broadcast_to(np.array([50.0, 100.0, 170.0]), (h, 3))
    y = demand_quantile(q, np.asarray(ndtr(z)))
    out = residual_correlation([normal_scores(y, np.broadcast_to(q, (n, h, 3)))])
    assert abs(out["rho_hat_lag1"] - rho) < 0.05
