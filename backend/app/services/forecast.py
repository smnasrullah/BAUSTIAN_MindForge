"""Forecast cache: precomputed for every agent at the data clock's origin, read by the API.

Fixed clock: once at bootstrap (origin SIM_NOW). Live clock: again on every hourly tick
(services/data_clock.py). The same pass writes the TreeSHAP explanations
(services/explanation.py) from the same panel.
"""

import hashlib
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.models import Event, Forecast, SystemMeta, Transaction
from app.models.enums import FLOAT_DEMAND
from app.schemas.forecast import AgentForecast, FloatForecast, ForecastPoint
from app.services import explanation
from app.services.model_registry import active_model, register_forecast_model
from ml.data_gen import live_load
from ml.data_gen.live import Engine
from ml.features.build import MAX_HORIZON_H, MIN_HISTORY_H
from ml.features.panel import WeatherFill, load_panel
from ml.inference.forecaster import Forecaster
from ml.registry import FORECAST_MODEL

log = logging.getLogger(__name__)
CACHE_KEY = "forecast_cache"
EXPLAIN_METHOD = "treeshap-q50-24h-1"


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def sim_now(session: Session) -> datetime:
    """The forecast origin (app/core/clock.py data_now)."""
    return clock.data_now(session)


def weather_outlook(session: Session) -> WeatherFill:
    """Live clock: weather for days without a stored row (after today) from the deterministic
    synthetic weather, as the fixed timeline's stored future weather was. Never written."""
    engine = Engine(live_load.world_for(session, get_settings().seed))

    def fill(district: str, day: date) -> tuple[float, float]:
        rain, temp, _severe = engine.weather(day)[district]
        return rain, temp

    return fill


def events_fingerprint(session: Session) -> str:
    """Changes whenever an event row is added, edited or deleted (admin events CRUD)."""
    rows = session.execute(select(Event.id, Event.type, Event.starts_at, Event.ends_at,
                                  Event.district, Event.intensity).order_by(Event.id)).all()
    text = "|".join(f"{i},{t},{_utc(s).isoformat()},{_utc(e).isoformat()},{d},{float(x)}"
                    for i, t, s, e, d, x in rows)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _cache_key(session: Session, version: str, now: datetime) -> dict[str, Any]:
    count, max_id = session.execute(
        select(func.count(), func.max(Transaction.id)).select_from(Transaction)).one()
    return {"model_version": version, "sim_now": now.isoformat(), "txn": [count, max_id],
            "events": events_fingerprint(session), "explain": EXPLAIN_METHOD,
            "conformal": get_settings().forecast_conformal}


def precompute(session: Session, artifacts_dir: Path, force: bool = False) -> int:
    """Register the model, then (re)write the cache unless it is current. Returns rows written."""
    mv = register_forecast_model(session, artifacts_dir)
    now = sim_now(session)
    key = _cache_key(session, mv.version, now)
    meta = session.get(SystemMeta, CACHE_KEY)
    if not force and meta is not None and meta.value == key:
        log.info("forecast cache current (%s)", mv.version)
        return 0
    win = clock.window_at(now)
    origin = win.hour_index(now)
    # Live ticks read only the history the features look at (4 weeks + a day of margin).
    since = origin - MIN_HISTORY_H - 24 if clock.is_live() else 0
    panel = load_panel(session, end=origin, window=win, since=since,
                       weather_fill=weather_outlook(session) if clock.is_live() else None)
    forecaster = Forecaster.load(artifacts_dir, get_settings().forecast_conformal)
    preds = forecaster.predict_origin(panel, origin, MAX_HORIZON_H)
    generated_at = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for i, agent_id in enumerate(panel.agent_ids.tolist()):
        for float_type, demand in FLOAT_DEMAND.items():
            p = preds[demand.value][i]
            for h in range(MAX_HORIZON_H):
                rows.append({
                    "model_version_id": mv.id, "agent_id": agent_id, "float_type": float_type,
                    "ts": now + timedelta(hours=h), "horizon_h": h + 1,
                    "q_low": round(float(p[h, 0]), 2), "q_mid": round(float(p[h, 1]), 2),
                    "q_high": round(float(p[h, 2]), 2), "generated_at": generated_at,
                })
    session.execute(delete(Forecast))
    if rows:
        session.execute(insert(Forecast), rows)
    # Live ticks have a time budget: TreeSHAP on all cores (fixed mode keeps one thread).
    threads = 0 if clock.is_live() else 1
    explanation.write_cache(session, mv, forecaster, panel, origin, now, generated_at, threads)
    session.merge(SystemMeta(key=CACHE_KEY, value=key))
    log.info("forecast cache: %d rows at %s (%s)", len(rows), now.isoformat(), mv.version)
    return len(rows)


def agent_forecast(session: Session, agent_id: int, horizon: int) -> AgentForecast | None:
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        return None
    found = session.scalars(
        select(Forecast)
        .where(Forecast.agent_id == agent_id, Forecast.model_version_id == mv.id,
               Forecast.horizon_h <= horizon)
        .order_by(Forecast.float_type, Forecast.horizon_h)
    ).all()
    if not found:
        return None
    floats = [
        FloatForecast(float_type=ft, demand_type=demand, points=[
            ForecastPoint(ts=_utc(r.ts), horizon_h=r.horizon_h, low=float(r.q_low),
                          expected=float(r.q_mid), high=float(r.q_high))
            for r in found if r.float_type == ft])
        for ft, demand in FLOAT_DEMAND.items()
    ]
    first = found[0]
    return AgentForecast(
        agent_id=agent_id,
        as_of=_utc(first.ts) - timedelta(hours=first.horizon_h - 1),
        horizon_hours=horizon,
        model_version=mv.version,
        generated_at=_utc(max(r.generated_at for r in found)),
        floats=floats,
    )
