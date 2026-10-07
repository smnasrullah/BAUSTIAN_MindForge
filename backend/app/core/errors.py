"""One error shape for every API failure: {"detail": "<code>"} (+ "errors" on validation).

Clients branch on the snake_case code; field errors never echo the submitted values.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")

# Starlette's own messages (unknown route, wrong method, ...) mapped to codes.
_STARLETTE_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    429: "rate_limited",
}


def error_response(status_code: int, code: str, headers: dict[str, str] | None = None,
                   **extra: object) -> JSONResponse:
    return JSONResponse({"detail": code, **extra}, status_code=status_code, headers=headers)


def _code(exc: StarletteHTTPException) -> str:
    # Our routes raise snake_case codes; Starlette raises the status phrase ("Not Found").
    detail = exc.detail
    if isinstance(detail, str) and detail and detail != HTTPStatus(exc.status_code).phrase:
        return detail
    fallback = "error" if exc.status_code < 500 else "internal_error"
    return _STARLETTE_CODES.get(exc.status_code, fallback)


async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(exc.status_code, _code(exc), headers=exc.headers)


async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg", "")),
               "type": str(e.get("type", ""))} for e in exc.errors()]
    return error_response(422, "validation_error", errors=errors)


async def _data_error(request: Request, exc: DataError) -> JSONResponse:
    """A value the database cannot store or compare (a NUL character in text, an out-of-range
    number) is bad input, not a server fault. Logged without the value."""
    log.warning("rejected value on %s %s: %s", request.method, request.url.path,
                type(exc.orig).__name__)
    return error_response(422, "invalid_value")


async def _db_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    """The database is unreachable or restarting: a temporary 503 (the app shows its reconnect
    banner and retries), not a 500."""
    log.warning("database unavailable on %s %s: %s", request.method, request.url.path,
                type(exc.orig).__name__)
    return error_response(503, "database_unavailable", headers={"Retry-After": "5"})


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "internal_error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(DataError, _data_error)
    app.add_exception_handler(OperationalError, _db_unavailable)
    app.add_exception_handler(Exception, _unhandled)
