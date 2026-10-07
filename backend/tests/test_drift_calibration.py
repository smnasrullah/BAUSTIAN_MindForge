"""S5: calibration drift and the advisory retrain suggestion; S3 comparison detector."""

import numpy as np
from sklearn.covariance import MinCovDet

from app.models.enums import FloatType
from app.schemas.admin_ops import DriftFloat
from app.services.drift import _coverage_status, _float_report, suggestion
from ml.features.anomaly import GLOBAL_GROUP
from ml.training.anomaly_compare import mcd_score


def test_calibration_status_reads_the_coverage_gap() -> None:
    assert _coverage_status(None, 0.8) == "no_data"
    assert _coverage_status(0.78, 0.86) == "stable"
    assert _coverage_status(0.70, 0.86) == "watch"
    assert _coverage_status(0.55, 0.86) == "drift"
    rep = _float_report(FloatType.cash, {1: [10.0, 20.0]},
                        {"cash_out": {"coverage_q10_q90": 0.86}}, [True, False, False, False])
    assert rep.coverage == 0.25 and rep.reference_coverage == 0.86
    assert rep.calibration_status == "drift"


def test_retrain_is_only_suggested_with_reasons() -> None:
    def f(ft: FloatType, status: str, cal: str) -> DriftFloat:
        return DriftFloat(float_type=ft, buckets=[], by_horizon=[], hours_compared=1,
                          status=status, calibration_status=cal)  # type: ignore[arg-type]

    calm = suggestion([f(FloatType.cash, "watch", "stable")])
    assert not calm.suggested and calm.reasons == []
    hot = suggestion([f(FloatType.cash, "stable", "drift"), f(FloatType.emoney, "drift", "watch")])
    assert hot.suggested and hot.reasons == ["cash.calibration_drift", "emoney.error_drift"]


def test_robust_covariance_scores_an_outlier_highest() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(500, 4))
    model = {GLOBAL_GROUP: MinCovDet(random_state=0).fit(x)}
    probe = np.vstack([np.zeros(4), np.full(4, 6.0)])
    score = mcd_score(model, probe, np.array(["t9-x", "t9-x"]))  # unknown group -> global
    assert score[1] > score[0] * 10
