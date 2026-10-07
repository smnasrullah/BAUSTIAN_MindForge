"""HTTP hardening: one error shape, bounded inputs, per-client rate limits, CORS allowlist,
body-size cap and security headers on API responses."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError, OperationalError

from app.core.config import get_settings
from app.core.params import MAX_ID
from app.main import create_app
from tests.auth_helpers import ADMIN, AGENT_MIRPUR, bearer, password_for

API = "/api/v1"


def _app_with(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_unknown_route_and_method_use_codes(client: TestClient) -> None:
    res = client.get(f"{API}/nope")
    assert (res.status_code, res.json()) == (404, {"detail": "not_found"})
    res = client.delete(f"{API}/system/health")
    assert (res.status_code, res.json()) == (405, {"detail": "method_not_allowed"})


def test_validation_errors_are_uniform_and_echo_no_values(client: TestClient,
                                                          seeded: Path) -> None:
    secret = "hunter2-should-never-come-back"
    res = client.post(f"{API}/auth/login", json={"email": 42, "password": secret, "x": 1})
    assert res.status_code == 422
    body = res.json()
    assert body["detail"] == "validation_error"
    assert body["errors"] and {"loc", "msg", "type"} == set(body["errors"][0])
    assert secret not in res.text


def test_route_codes_pass_through(client: TestClient, seeded: Path) -> None:
    res = client.post(f"{API}/auth/login",
                      json={"email": ADMIN, "password": "wrong-password-here"})
    assert res.status_code == 401 and res.json() == {"detail": "invalid_credentials"}


@pytest.mark.parametrize("path", [
    f"/agents/{MAX_ID + 1}", "/agents/99999999999999999999999", "/agents/0",
    "/agents/risk?page=10001", "/notifications?page=99999999999999999999",
    f"/anomalies/{MAX_ID + 1}",
])
def test_oversized_numbers_are_422_not_500(client: TestClient, seeded: Path, path: str) -> None:
    res = client.get(API + path, headers=bearer(client, ADMIN))
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == "validation_error"


def test_oversized_text_is_rejected(client: TestClient, seeded: Path) -> None:
    h = bearer(client, AGENT_MIRPUR)
    res = client.post(f"{API}/copilot/chat", headers=h, json={"message": "x" * 2001})
    assert res.status_code == 422
    res = client.get(f"{API}/search", params={"q": "x" * 81}, headers=h)
    assert res.status_code == 422
    res = client.post(f"{API}/auth/refresh", headers={"Cookie": "ap_refresh=" + "x" * 600})
    assert res.status_code == 422


def test_body_size_cap(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    c = _app_with(monkeypatch, MAX_BODY_BYTES="1000")
    res = c.post(f"{API}/auth/login", content=b"{" + b" " * 2000 + b"}",
                 headers={"Content-Type": "application/json"})
    assert (res.status_code, res.json()) == (413, {"detail": "payload_too_large"})


def test_unhandled_error_is_json_500_without_internals(env: Path) -> None:
    app = create_app()

    @app.get("/api/v1/boom")
    def boom() -> None:
        raise RuntimeError("db password is hunter2")

    res = TestClient(app, raise_server_exceptions=False).get("/api/v1/boom")
    assert (res.status_code, res.json()) == (500, {"detail": "internal_error"})
    assert "hunter2" not in res.text


def test_value_the_database_rejects_is_422_not_500(env: Path) -> None:
    """Found by fuzzing: a NUL character in a filter reached Postgres and became a 500."""
    app = create_app()

    @app.get("/api/v1/nul")
    def nul() -> None:
        raise DataError("SELECT 1", {}, ValueError("text cannot contain NUL"))

    res = TestClient(app, raise_server_exceptions=False).get("/api/v1/nul")
    assert (res.status_code, res.json()) == (422, {"detail": "invalid_value"})


def test_database_down_is_503_with_retry_after(env: Path) -> None:
    app = create_app()

    @app.get("/api/v1/dbdown")
    def dbdown() -> None:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("db restarting"))

    res = TestClient(app, raise_server_exceptions=False).get("/api/v1/dbdown")
    assert (res.status_code, res.json()) == (503, {"detail": "database_unavailable"})
    assert res.headers["retry-after"] == "5"


def test_api_rate_limit_per_client(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    c = _app_with(monkeypatch, API_RATE_PER_MIN="5")
    codes = [c.get(f"{API}/system/health").status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    res = c.get(f"{API}/system/health")
    assert res.json() == {"detail": "rate_limited"} and res.headers["retry-after"] == "60"
    # Another client (nginx sets X-Real-IP) has its own budget.
    assert c.get(f"{API}/system/health", headers={"X-Real-IP": "10.9.9.9"}).status_code == 200


def test_login_rate_limit_spans_emails(monkeypatch: pytest.MonkeyPatch, seeded: Path) -> None:
    c = _app_with(monkeypatch, LOGIN_RATE_PER_MIN="3")
    codes = [c.post(f"{API}/auth/login", json={"email": f"user{i}@example.com",
                                               "password": "wrong-password"}).status_code
             for i in range(4)]
    assert codes == [401, 401, 401, 429]
    ok = c.post(f"{API}/auth/login", headers={"X-Real-IP": "10.1.2.3"},
                json={"email": AGENT_MIRPUR, "password": password_for(AGENT_MIRPUR)})
    assert ok.status_code == 200


def test_login_rate_limit_is_shared_by_workers(monkeypatch: pytest.MonkeyPatch,
                                               seeded: Path) -> None:
    """Two app instances stand in for two uvicorn workers: one budget per IP, not one each."""
    a = _app_with(monkeypatch, LOGIN_RATE_PER_MIN="3", WEB_CONCURRENCY="2")
    b = TestClient(create_app())
    bad = {"email": "nobody@example.com", "password": "wrong-password"}
    codes = [c.post(f"{API}/auth/login", json=bad).status_code for c in (a, b, a, b)]
    assert codes == [401, 401, 401, 429]


def test_request_cap_is_split_across_workers(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    c = _app_with(monkeypatch, API_RATE_PER_MIN="6", WEB_CONCURRENCY="2")
    codes = [c.get(f"{API}/system/health").status_code for _ in range(4)]
    assert codes == [200] * 3 + [429]


def test_security_headers_on_api(client: TestClient) -> None:
    res = client.get(f"{API}/system/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["cache-control"] == "no-store"


PREFLIGHT = {"Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "authorization,content-type"}


def test_no_cors_by_default(client: TestClient) -> None:
    evil = {"Origin": "https://evil.example"}
    res = client.options(f"{API}/auth/login", headers={**evil, **PREFLIGHT})
    assert "access-control-allow-origin" not in res.headers
    res = client.get(f"{API}/system/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_cors_allowlist(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    c = _app_with(monkeypatch, CORS_ORIGINS='["https://ops.example"]')
    ok = c.options(f"{API}/auth/login", headers={"Origin": "https://ops.example", **PREFLIGHT})
    assert ok.headers["access-control-allow-origin"] == "https://ops.example"
    assert ok.headers["access-control-allow-credentials"] == "true"
    bad = c.options(f"{API}/auth/login", headers={"Origin": "https://evil.example", **PREFLIGHT})
    assert "access-control-allow-origin" not in bad.headers


def test_openapi_documents_the_real_error_shape_and_statuses(client: TestClient) -> None:
    """Fuzzing found the spec promising FastAPI's 422 body and none of 401/403/404/409/429."""
    spec = client.get("/openapi.json").json()
    text = str(spec)
    assert "HTTPValidationError" not in text
    error_ref = "#/components/schemas/ErrorResponse"
    risk = spec["paths"]["/api/v1/agents/{agent_id}/risk"]["get"]["responses"]
    for code in ("401", "403", "404", "422", "429"):
        assert risk[code]["content"]["application/json"]["schema"]["$ref"] == error_ref, code
    health = spec["paths"]["/api/v1/health"]["get"]["responses"]
    assert "401" not in health and "422" in health
