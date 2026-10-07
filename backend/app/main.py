import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1.auth import demo_router
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import install_error_handlers
from app.core.middleware import RequestGuard
from app.core.openapi import install_openapi
from app.core.perf import ServerTiming, instrument_engine
from app.services import backtest_job, data_scheduler, help_scheduler

log = logging.getLogger("app")


def _app_logging() -> None:
    """INFO from app.* (scheduler ticks, trigger decisions) on stderr next to uvicorn's lines."""
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s  [%(name)s] %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.app_env != "test":  # tests drive the trigger and the data clock explicitly
        _app_logging()
        help_scheduler.start(settings.help_trigger_interval_s)
        data_scheduler.start(settings.data_tick_interval_s)  # live clock only
        backtest_job.start()  # live clock only: the daily holdout backtest, outside the tick
    yield
    data_scheduler.stop()
    backtest_job.stop()
    help_scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=_lifespan)
    app.include_router(api_router)
    if settings.demo_mode:  # POST /api/v1/auth/demo-login exists only in demo mode
        app.include_router(demo_router, prefix="/api/v1")
        log.warning("DEMO_MODE=true: one-click POST /api/v1/auth/demo-login is enabled. "
                    "Set DEMO_MODE=false for any public hosting.")
    install_error_handlers(app)
    install_openapi(app)
    app.add_middleware(RequestGuard, per_min=settings.api_rate_per_min,
                       login_per_min=settings.login_rate_per_min,
                       max_body=settings.max_body_bytes, workers=settings.web_concurrency)
    if settings.cors_origins:  # outermost, so preflights and 429s carry the CORS headers
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_credentials=True,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"], max_age=600)
    if settings.perf_headers:  # verify stack / -Perf only: SQL query count per response
        instrument_engine(get_engine())
        app.add_middleware(ServerTiming)
    return app


app = create_app()
