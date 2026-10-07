"""Sliding-window rate limit shared by every uvicorn worker (rows in rate_limit_hits).

Used for the security limits (login per IP, demo login, signup, password reset, per-user LLM)
so they stay exact when the API runs several worker processes. The coarse per-IP request cap
stays in-process (core/rate_limit), since it guards every request and needs no DB round trip.
Each check runs in its own short transaction, independent of the request session; on Postgres
a transaction-level advisory lock per bucket makes the count-then-insert atomic.
"""

import random
import time
import zlib
from collections.abc import Hashable

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.models.rate_limit import RateLimitHit

# Rows older than this are swept now and then (buckets that are never checked again).
SWEEP_AFTER_S = 2 * 3600.0
SWEEP_CHANCE = 0.02


class SharedRateLimiter:
    def __init__(self, name: str, window_s: float = 60.0) -> None:
        self.name = name
        self._window_s = window_s

    def _bucket(self, key: Hashable) -> str:
        return f"{self.name}:{key!r}"[:200]

    def allow(self, key: Hashable, per_window: int) -> bool:
        bucket = self._bucket(key)
        now = time.time()
        with get_engine().begin() as conn:
            if conn.dialect.name == "postgresql":
                lock = zlib.crc32(bucket.encode()) - 2**31
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock})
            conn.execute(delete(RateLimitHit).where(RateLimitHit.bucket == bucket,
                                                    RateLimitHit.hit_at <= now - self._window_s))
            used = conn.scalar(select(func.count()).select_from(RateLimitHit)
                               .where(RateLimitHit.bucket == bucket)) or 0
            if used >= per_window:
                return False
            conn.execute(RateLimitHit.__table__.insert().values(bucket=bucket, hit_at=now))
            if random.random() < SWEEP_CHANCE:  # noqa: S311 - housekeeping, not security
                conn.execute(delete(RateLimitHit).where(RateLimitHit.hit_at <= now - SWEEP_AFTER_S))
        return True

    def reset(self) -> None:
        """Tests: forget this limiter's hits (no-op before the schema exists)."""
        try:
            with get_engine().begin() as conn:
                conn.execute(delete(RateLimitHit).where(
                    RateLimitHit.bucket.like(f"{self.name}:%")))
        except SQLAlchemyError:
            pass
