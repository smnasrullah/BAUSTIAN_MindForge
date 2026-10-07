import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, get_args

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, Settings
from app.llm.mode import resolve_mode
from app.models.system_meta import SystemMeta
from app.schemas.system import BootstrapState, SystemStatus

STATUS_META_KEYS = ("seed", "data_version")


def bootstrap_state(settings: Settings) -> BootstrapState:
    try:
        raw = settings.bootstrap_state_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "starting"
    for state in get_args(BootstrapState):
        if raw == state:
            return state
    return "starting"


@lru_cache(maxsize=1)
def _migration_head() -> str | None:
    """Parsed once per process: the migration scripts ship in the image and never change at
    runtime, and parsing all of them cost ~18 ms on every (polled) status call."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _read_db(engine: Engine) -> tuple[bool, str | None, dict[str, Any]]:
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
            meta: dict[str, Any] = {}
            # Migration 0001 creates system_meta; checking the revision avoids a catalog query.
            if current is not None:
                with Session(bind=conn) as session:
                    # Only the keys the status needs: system_meta also holds large caches.
                    rows = session.scalars(select(SystemMeta).where(
                        SystemMeta.key.in_(STATUS_META_KEYS))).all()
                    meta = {row.key: row.value for row in rows}
            return True, current, meta
    except SQLAlchemyError:
        return False, None, {}


def _model_version(settings: Settings) -> str | None:
    manifest = settings.artifacts_dir / "manifest.json"
    try:
        return _manifest_version(manifest, manifest.stat().st_mtime_ns)
    except OSError:
        return None


@lru_cache(maxsize=4)
def _manifest_version(manifest: Path, _mtime_ns: int) -> str | None:
    """Re-read only when the file changes (keyed on its modification time)."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("model_version") if isinstance(data, dict) else None
    return str(version) if version is not None else None


def build_status(settings: Settings, engine: Engine) -> SystemStatus:
    db_ok, current, meta = _read_db(engine)
    head = _migration_head()
    state = bootstrap_state(settings)
    model_version = _model_version(settings)
    seed = meta.get("seed")
    data_version = meta.get("data_version")
    return SystemStatus(
        ready=db_ok and current is not None and current == head and state == "ready",
        bootstrap_state=state,
        db=db_ok,
        migration_current=current,
        migration_head=head,
        seed=seed if isinstance(seed, int) else None,
        data_version=data_version if isinstance(data_version, str) else None,
        artifacts_ok=model_version is not None,
        model_version=model_version,
        llm_mode=resolve_mode(settings),
        demo_mode=settings.demo_mode,
        dev_mailer=settings.mailer == "dev_log",
        generated_at=datetime.now(UTC),
    )
