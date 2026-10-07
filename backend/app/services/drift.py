"""Forecast-error drift monitor.

Compares the cached forecast (origin SIM_NOW, 1..72 h ahead) with the demand the synthetic data
logged for those hours, as MAE of q50 per horizon bucket, against the holdout MAE stored with the
active model (manifest `mae_by_horizon_h`). ratio = live MAE / reference MAE.
stable < WATCH_RATIO <= watch < DRIFT_RATIO <= drift. One origin is a small sample, so the
thresholds are loose; the point is to catch a model that no longer fits the data it serves.

Live clock: there is no data after the current origin, so the report scores a backcast instead:
the same model run at origin - 72 h on the history before it, against the demand logged since.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.models import Forecast, Transaction
from app.models.enums import FLOAT_DEMAND, FloatType
from app.schemas.admin_ops import (
    DriftBucket,
    DriftFloat,
    DriftPoint,
    DriftReport,
    DriftStatus,
    RetrainSuggestion,
)
from app.services.forecast import sim_now
from app.services.model_registry import active_model
from ml.features.build import MAX_HORIZON_H, MIN_HISTORY_H
from ml.features.panel import load_panel
from ml.inference.forecaster import Forecaster
from ml.registry import FORECAST_MODEL

Pred = tuple[int, FloatType, datetime, int, float, float, float]  # agent, float, ts, h, lo/mid/hi

WATCH_RATIO = 1.2
DRIFT_RATIO = 1.5
# Calibration drift: |coverage - reference coverage| of the q10-q90 band. Loose, like the MAE
# ratio: one origin is a small, hour-correlated sample.
WATCH_COVERAGE_GAP = 0.10
DRIFT_COVERAGE_GAP = 0.20
BUCKETS: tuple[tuple[str, int, int], ...] = (("1-6", 1, 6), ("7-24", 7, 24), ("25-72", 25, 72))
_RANK: dict[DriftStatus, int] = {"no_data": 0, "stable": 1, "watch": 2, "drift": 3}

_cache: dict[tuple[str, str], DriftReport] = {}


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _status(ratio: float | None) -> DriftStatus:
    if ratio is None:
        return "no_data"
    return "stable" if ratio < WATCH_RATIO else "watch" if ratio < DRIFT_RATIO else "drift"


def _worst(statuses: list[DriftStatus]) -> DriftStatus:
    return max(statuses, key=lambda s: _RANK[s], default="no_data")


def _reference(metrics: dict[str, Any], demand: str, bucket: str) -> float | None:
    value = metrics.get(demand, {}).get("mae_by_horizon_h", {}).get(bucket, {}).get("mae")
    return float(value) if isinstance(value, int | float) else None


def _coverage_status(cov: float | None, ref: float | None) -> DriftStatus:
    if cov is None or ref is None:
        return "no_data"
    gap = abs(cov - ref)
    return "stable" if gap < WATCH_COVERAGE_GAP else "watch" if gap < DRIFT_COVERAGE_GAP \
        else "drift"


def suggestion(floats: list[DriftFloat]) -> RetrainSuggestion:
    """Advisory retrain suggestion: any float whose error or calibration reads 'drift'."""
    reasons = [f"{f.float_type.value}.{kind}_drift" for f in floats
               for kind, status in (("error", f.status), ("calibration", f.calibration_status))
               if status == "drift"]
    return RetrainSuggestion(suggested=bool(reasons), reasons=reasons)


def _float_report(ft: FloatType, errors: dict[int, list[float]], metrics: dict[str, Any],
                  inside: list[bool] | None = None) -> DriftFloat:
    demand = FLOAT_DEMAND[ft].value
    buckets: list[DriftBucket] = []
    for name, lo, hi in BUCKETS:
        errs = [e for h in range(lo, hi + 1) for e in errors.get(h, [])]
        mae = sum(errs) / len(errs) if errs else None
        ref = _reference(metrics, demand, name)
        ratio = round(mae / ref, 3) if mae is not None and ref else None
        buckets.append(DriftBucket(horizon=name, mae=round(mae, 1) if mae is not None else None,
                                   reference_mae=ref, ratio=ratio, status=_status(ratio)))
    points = [DriftPoint(horizon_h=h, mae=round(sum(v) / len(v), 1))
              for h, v in sorted(errors.items()) if v]
    cov = round(sum(inside) / len(inside), 4) if inside else None
    ref_raw = metrics.get(demand, {}).get("coverage_q10_q90")
    ref = float(ref_raw) if isinstance(ref_raw, int | float) else None
    return DriftFloat(float_type=ft, buckets=buckets, by_horizon=points,
                      hours_compared=sum(len(v) for v in errors.values()),
                      status=_worst([b.status for b in buckets]), coverage=cov,
                      reference_coverage=ref, calibration_status=_coverage_status(cov, ref))


def _backcast(session: Session, origin: datetime) -> list[Pred]:
    """Live clock: the active model's q50 at `origin` from the history before it only."""
    win = clock.window_at(origin)
    t0 = win.hour_index(origin)
    panel = load_panel(session, end=t0, window=win, since=t0 - MIN_HISTORY_H - 24)
    settings = get_settings()
    fc = Forecaster.load(settings.artifacts_dir, settings.forecast_conformal)
    preds = fc.predict_origin(panel, t0, MAX_HORIZON_H)
    out: list[Pred] = []
    for i, agent_id in enumerate(panel.agent_ids.tolist()):
        for ft, demand in FLOAT_DEMAND.items():
            for h in range(MAX_HORIZON_H):
                lo, mid, hi = (float(v) for v in preds[demand.value][i][h])
                out.append((agent_id, ft, origin + timedelta(hours=h), h + 1, lo, mid, hi))
    return out


def report(session: Session) -> DriftReport:
    mv = active_model(session, FORECAST_MODEL)
    now = datetime.now(UTC)
    if mv is None:
        return DriftReport(model_version=None, origin=None, watch_ratio=WATCH_RATIO,
                           drift_ratio=DRIFT_RATIO, floats=[], status="no_data", generated_at=now)
    last = session.scalar(select(func.max(Forecast.generated_at))
                          .where(Forecast.model_version_id == mv.id))
    live = clock.is_live()
    origin = sim_now(session) - timedelta(hours=MAX_HORIZON_H) if live else sim_now(session)
    key = (mv.version, origin.isoformat() if live else str(last))
    if key in _cache:
        return _cache[key].model_copy(update={"generated_at": now})
    end = origin + timedelta(hours=73)
    actual: dict[tuple[int, str, datetime], float] = defaultdict(float)
    for agent_id, ts, kind, amount in session.execute(
            select(Transaction.agent_id, Transaction.ts, Transaction.txn_type,
                   Transaction.amount_bdt)
            .where(Transaction.ts >= origin, Transaction.ts < end)).tuples():
        actual[(agent_id, kind.value, _utc(ts))] += float(amount)
    errors: dict[FloatType, dict[int, list[float]]] = {ft: defaultdict(list) for ft in FloatType}
    inside: dict[FloatType, list[bool]] = {ft: [] for ft in FloatType}
    # No logged demand after the origin (data without ground truth): nothing to compare.
    query = select(Forecast.agent_id, Forecast.float_type, Forecast.ts, Forecast.horizon_h,
                   Forecast.q_low, Forecast.q_mid, Forecast.q_high).where(
        Forecast.model_version_id == mv.id)
    rows: list[Pred] = []
    if actual:
        rows = _backcast(session, origin) if live else [
            (a, f, t, h, float(lo), float(q), float(hi))
            for a, f, t, h, lo, q, hi in session.execute(query).tuples()]
    for agent_id, ft, ts, h, lo, q_mid, hi in rows:
        t = _utc(ts)
        if t >= end:
            continue
        got = actual.get((agent_id, FLOAT_DEMAND[ft].value, t), 0.0)
        errors[ft][h].append(abs(float(q_mid) - got))
        inside[ft].append(lo <= got <= hi)
    floats = [_float_report(ft, errors[ft], mv.metrics or {}, inside[ft]) for ft in FloatType
              if errors[ft]]
    out = DriftReport(model_version=mv.version, origin=origin, watch_ratio=WATCH_RATIO,
                      drift_ratio=DRIFT_RATIO, floats=floats,
                      status=_worst([f.status for f in floats]), generated_at=now,
                      retrain=suggestion(floats))
    _cache.clear()
    _cache[key] = out
    return out
