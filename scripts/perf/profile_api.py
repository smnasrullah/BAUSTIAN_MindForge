"""cProfile the hot read paths in-process (verify backend container, real DB):
  docker cp scripts/perf/profile_api.py agentpulse-verify-backend-1:/tmp/ &&
  docker exec -w /app -e PYTHONPATH=/app -e APP_ENV=test agentpulse-verify-backend-1 python /tmp/profile_api.py [path-filter] [callers-of]
Prints the top functions by cumulative and by own time.
"""

import asyncio
import cProfile
import io
import pstats
import sys
from contextlib import asynccontextmanager
from typing import Any

import fastapi.dependencies.utils as dep_utils
import fastapi.routing as routing
import httpx


async def _inline(func: Any, *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


@asynccontextmanager
async def _inline_cm(cm: Any) -> Any:
    with cm as value:
        yield value


# Run sync handlers and dependencies on the profiled thread instead of the threadpool.
routing.run_in_threadpool = _inline
dep_utils.run_in_threadpool = _inline
dep_utils.contextmanager_in_threadpool = _inline_cm

from app.main import app  # noqa: E402

PATHS = [
    ("agent", "/api/v1/agents/1/summary"), ("agent", "/api/v1/agents/1/forecast?horizon_hours=72"),
    ("agent", "/api/v1/agents/1/stockout"), ("agent", "/api/v1/agents/1/recommendation"),
    ("agent", "/api/v1/system/status"), ("distributor", "/api/v1/agents/risk?horizon=24"),
    ("distributor", "/api/v1/map/agents"), ("distributor", "/api/v1/distributor/briefing?lang=en"),
    ("admin", "/api/v1/admin/overview"),
]



async def main() -> cProfile.Profile:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        tok = {}
        for r in ("agent", "distributor", "admin"):
            res = await c.post("/api/v1/auth/demo-login", json={"role": r})
            tok[r] = res.json()["access_token"]
        only = sys.argv[1] if len(sys.argv) > 1 else ""
        paths = [p for p in PATHS if only in p[1]]
        for role, p in paths:  # warm-up
            await c.get(p, headers={"Authorization": f"Bearer {tok[role]}"})
        prof = cProfile.Profile()
        prof.enable()
        for _ in range(20):
            for role, p in paths:
                await c.get(p, headers={"Authorization": f"Bearer {tok[role]}"})
        prof.disable()
        return prof


if __name__ == "__main__":
    prof = asyncio.run(main())
    for key in ("cumulative", "tottime"):
        s = io.StringIO()
        pstats.Stats(prof, stream=s).sort_stats(key).print_stats(28)
        print("\n".join(line[:170] for line in s.getvalue().splitlines()[6:40]))
    if len(sys.argv) > 2:
        pstats.Stats(prof).print_callers(sys.argv[2])
