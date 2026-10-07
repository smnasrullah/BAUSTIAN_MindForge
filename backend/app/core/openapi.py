"""OpenAPI that matches what the API really answers (found by fuzzing with Schemathesis).

Every failure has one shape (core/errors.py): {"detail": "<code>"} plus "errors" on validation.
FastAPI's default spec showed its own 422 body (detail as a list) and none of the statuses the
middleware and dependencies return, so clients and fuzzers could not trust it.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

ERROR = "ErrorResponse"
_ERROR_SCHEMA: dict[str, Any] = {
    "title": ERROR,
    "type": "object",
    "required": ["detail"],
    "properties": {
        "detail": {"type": "string", "description": "snake_case error code"},
        "errors": {
            "type": "array",
            "description": "validation_error only: field errors (values are never echoed)",
            "items": {
                "type": "object",
                "properties": {"loc": {"type": "array", "items": {"type": "string"}},
                               "msg": {"type": "string"}, "type": {"type": "string"}},
            },
        },
    },
}
_DESCRIPTIONS = {
    "400": "Malformed request", "401": "Not signed in or session expired", "403": "Not allowed",
    "404": "Not found", "409": "Conflict with the current state", "413": "Body too large",
    "422": "Invalid input", "429": "Rate limited (Retry-After)", "500": "Server error",
    "503": "Database unavailable, retry shortly (Retry-After)",
}
_WRITES = {"post", "put", "patch", "delete"}


def _error(code: str) -> dict[str, Any]:
    return {"description": _DESCRIPTIONS[code],
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ERROR}"}}}}


def _statuses(path: str, method: str, op: dict[str, Any]) -> list[str]:
    codes = ["400", "413", "422", "429", "500", "503"]
    secured = bool(op.get("security"))
    if secured or path.startswith("/api/v1/auth/"):
        codes += ["401", "403"]
    if "{" in path or secured:  # path ids, and ids sent in a body or query (agent_id, ...)
        codes.append("404")
    if secured and method in _WRITES:
        codes.append("409")
    return codes


def install_openapi(app: FastAPI) -> None:
    def custom() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version,
                             openapi_version=app.openapi_version, routes=app.routes)
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        schemas[ERROR] = _ERROR_SCHEMA
        for name in ("HTTPValidationError", "ValidationError"):
            schemas.pop(name, None)
        for path, ops in schema.get("paths", {}).items():
            for method, op in ops.items():
                responses = op.setdefault("responses", {})
                for code in _statuses(path, method, op):
                    if code == "422" or code not in responses:
                        responses[code] = _error(code)
        app.openapi_schema = schema
        return schema

    app.openapi = custom  # type: ignore[method-assign]
