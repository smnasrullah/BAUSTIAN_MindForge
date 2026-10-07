"""Holdout backtests at bootstrap: impact (F11) and fairness (F12) from one set of inputs.

Skipped when model, data, seed, rules and method are unchanged (same key in both caches).
Live clock: the 14 held-out days move with the date, so the key also holds the holdout start and
the backtest reruns once a day, not every hour. It runs in its own background job
(backtest_job.py), never inside the hourly tick.
"""

import json
import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import DATA_VERSION, Settings
from app.models import ModelVersion, SystemMeta
from app.rules.risk_rules import HEADLINE_HORIZON, build_config
from app.services import fairness, forecast, holdout_inputs, impact, rebalance
from app.services.model_registry import active_model
from ml.registry import FORECAST_MODEL

log = logging.getLogger(__name__)
METHOD = "holdout-1"


def _model(session: Session) -> ModelVersion:
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        raise RuntimeError("no active forecast model; run the forecast precompute first")
    return mv


def cache_key(session: Session, settings: Settings, mv: ModelVersion) -> dict[str, Any]:
    rcfg, scfg, ccfg = rebalance.configs(settings)
    raw: dict[str, Any] = {
        "model_version": mv.version, "seed": settings.seed, "data_version": DATA_VERSION,
        "events": forecast.events_fingerprint(session), "method": METHOD,
        "impact": asdict(impact.impact_config(settings)), "rebalance": asdict(rcfg),
        "swap": asdict(scfg), "channel": asdict(ccfg),
        "risk": build_config(settings.risk_thresholds).as_dict(),
        "stockout_method": settings.stockout_method, "conformal": settings.forecast_conformal}
    if clock.is_live():
        state = session.get(SystemMeta, "data_clock")
        raw["holdout_start"] = clock.window(session).holdout_start.isoformat()
        raw["data_window"] = state.value.get("window_start") if state else None  # regenerations
    out: dict[str, Any] = json.loads(json.dumps(raw))  # tuples -> lists, as stored
    return out


def _current(session: Session, key: dict[str, Any]) -> bool:
    metas = [session.get(SystemMeta, k) for k in (impact.CACHE_KEY, fairness.CACHE_KEY)]
    return all(m is not None and m.value.get("key") == key for m in metas)


def stale_key(session: Session, settings: Settings) -> dict[str, Any] | None:
    """The current key when the holdout caches do not match it; None when they are current.
    Cheap (no backtest work): the live backtest job polls it."""
    key = cache_key(session, settings, _model(session))
    return None if _current(session, key) else key


def precompute(session: Session, settings: Settings, force: bool = False) -> int:
    """Returns impact rows written (0 when current or skipped)."""
    mv = _model(session)
    rcfg, scfg, ccfg = rebalance.configs(settings)
    cfg = impact.impact_config(settings)
    risk_cfg = build_config(settings.risk_thresholds)
    key = cache_key(session, settings, mv)
    if not force and _current(session, key):
        log.info("holdout backtests current (%s)", mv.version)
        return 0
    horizon = max(rcfg.horizon_h, fairness.HORIZON_H)
    h = holdout_inputs.load(session, settings, cfg, horizon)
    if h is None:
        return 0
    n = impact.store(session, h, mv, cfg, rcfg, scfg, ccfg, key)
    fairness.store(session, h, mv, risk_cfg.cuts[HEADLINE_HORIZON].amber, settings.seed, key)
    return n
