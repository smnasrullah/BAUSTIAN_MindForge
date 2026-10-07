"""Opt-in per-request timing (PERF_HEADERS=true): `Server-Timing: db;desc="N queries";dur=..`.

Used by the verify stack and the -Perf check to count SQL queries per endpoint (N+1 detection).
Off by default, so production responses carry no timing data.
"""

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, event
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass
class _Stats:
    queries: int = 0
    db_s: float = 0.0
    started: list[float] = field(default_factory=list)


_current: ContextVar[_Stats | None] = ContextVar("perf_stats", default=None)


def instrument_engine(engine: Engine) -> None:
    def before(*_args: Any) -> None:
        stats = _current.get()
        if stats is not None:
            stats.started.append(time.perf_counter())

    def after(*_args: Any) -> None:
        stats = _current.get()
        if stats is not None and stats.started:
            stats.queries += 1
            stats.db_s += time.perf_counter() - stats.started.pop()

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)


class ServerTiming:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        stats = _Stats()
        token = _current.set(stats)
        t0 = time.perf_counter()

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                total_ms = (time.perf_counter() - t0) * 1000
                MutableHeaders(scope=message).append(
                    "Server-Timing",
                    f'db;desc="{stats.queries} queries";dur={stats.db_s * 1000:.1f}, '
                    f"app;dur={total_ms:.1f}")
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            _current.reset(token)
