"""Request guards for /api: per-client rate limits, body-size cap, response security headers."""

import math

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.core.rate_limit import RateLimiter, client_ip
from app.core.shared_limit import SharedRateLimiter

LOGIN_PATH = "/api/v1/auth/login"
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


class RequestGuard:
    """Per client IP (nginx sets X-Real-IP): the coarse request cap is in-process, split evenly
    across `workers` processes; the login cap is shared by all workers (core/shared_limit).

    Bodies are capped by Content-Length here and by nginx `client_max_body_size` for all.
    """

    def __init__(self, app: ASGIApp, *, per_min: int, login_per_min: int, max_body: int,
                 workers: int = 1) -> None:
        self.app = app
        self.per_min = max(1, math.ceil(per_min / max(1, workers)))
        self.login_per_min = login_per_min
        self.max_body = max_body
        self.limiter = RateLimiter()
        self.login_limiter = SharedRateLimiter("login_ip")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        rejected = self._reject(conn)
        if rejected is None and scope["method"] == "POST" and scope["path"] == LOGIN_PATH:
            allowed = await run_in_threadpool(self.login_limiter.allow, client_ip(conn),
                                              self.login_per_min)
            if not allowed:
                rejected = _rate_limited()
        if rejected is not None:
            await rejected(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _reject(self, conn: HTTPConnection) -> JSONResponse | None:
        length = conn.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_body):
            return error_response(413, "payload_too_large")
        if not self.limiter.allow(("all", client_ip(conn)), self.per_min):
            return _rate_limited()
        return None


def _rate_limited() -> JSONResponse:
    return error_response(429, "rate_limited", headers={"Retry-After": "60"})
