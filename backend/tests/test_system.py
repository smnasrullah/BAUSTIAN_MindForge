from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import BACKEND_DIR, get_settings


def _migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = get_settings().database_url
    command.upgrade(cfg, "head")


def test_health(client: TestClient) -> None:
    for path in ("/api/v1/health", "/api/v1/system/health"):
        res = client.get(path)
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_status_not_ready_before_bootstrap(client: TestClient) -> None:
    body = client.get("/api/v1/system/status").json()
    assert body["ready"] is False
    assert body["bootstrap_state"] == "starting"
    assert body["db"] is True
    assert body["migration_current"] is None
    assert body["migration_head"] == "0026"
    assert body["artifacts_ok"] is False
    assert body["llm_mode"] in {"replay", "template"}
    assert body["demo_mode"] is True
    assert body["dev_mailer"] is True


def test_status_ready_after_migrate_and_state(client: TestClient, env: Path) -> None:
    _migrate()
    (env / "state").write_text("ready\n", encoding="utf-8")
    body = client.get("/api/v1/system/status").json()
    assert body["migration_current"] == "0026"
    assert body["bootstrap_state"] == "ready"
    assert body["ready"] is True


def test_status_reports_failed_state(client: TestClient, env: Path) -> None:
    (env / "state").write_text("failed", encoding="utf-8")
    body = client.get("/api/v1/system/status").json()
    assert body["bootstrap_state"] == "failed"
    assert body["ready"] is False
