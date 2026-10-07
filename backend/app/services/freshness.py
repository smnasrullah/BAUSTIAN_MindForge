"""Data freshness chip: when forecasts were last computed, by which model, over which data,
and on which clock (live or fixed)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.llm.mode import resolve_mode
from app.models import Forecast
from app.schemas.system import ClockInfo, DataPeriod, Freshness
from app.services.model_registry import active_model
from ml.registry import FORECAST_MODEL


def data_period(session: Session) -> DataPeriod:
    origin = clock.data_now(session)
    win = clock.window_at(origin)
    # Live: logged data ends at the origin (nothing is generated ahead of the clock).
    end = origin if clock.is_live() else win.end
    return DataPeriod(start=win.start, end=end, holdout_start=win.holdout_start, sim_now=origin)


def clock_info(session: Session, last_compute: datetime | None) -> ClockInfo:
    origin = clock.data_now(session)
    return ClockInfo(mode=clock.mode(), timezone="Asia/Dhaka", now=clock.now(), data_hour=origin,
                     last_data_hour=origin - timedelta(hours=1), last_compute_at=last_compute)


def freshness(session: Session, settings: Settings) -> Freshness:
    mv = active_model(session, FORECAST_MODEL)
    last = None if mv is None else session.scalar(
        select(func.max(Forecast.generated_at)).where(Forecast.model_version_id == mv.id))
    last_at = clock.as_utc(last) if last else None
    return Freshness(
        last_forecast_at=last_at,
        model_version=mv.version if mv else None,
        data_period=data_period(session),
        llm_mode=resolve_mode(settings),
        generated_at=datetime.now(UTC),
        clock=clock_info(session, last_at),
    )
