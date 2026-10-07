"""Synthetic dataset summary and the SYNTHETIC_ASSUMPTIONS.md document for /admin/data."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, Settings
from app.models import (
    Agent,
    Distributor,
    Event,
    FloatSnapshot,
    SystemMeta,
    Transaction,
    User,
    WeatherDaily,
)
from app.schemas.admin_ops import AssumptionsDoc, DataCount, DataSummary
from app.services.freshness import data_period

ASSUMPTIONS_FILE = "SYNTHETIC_ASSUMPTIONS.md"
# Docker: docs/ is copied next to the app (/app/docs); local checkout: the repo's docs/.
DOC_DIRS = (BACKEND_DIR / "docs", BACKEND_DIR.parent / "docs")

COUNTED = (("distributors", Distributor), ("agents", Agent), ("users", User),
           ("events", Event), ("weather_daily", WeatherDaily))

# count(*) over the two ~900k-row tables cost ~70 ms per call. They only grow by insert, so the
# counts are reused while max(id) (a primary-key lookup) of both tables is unchanged.
_big_counts: dict[tuple[object, object], tuple[int, int, int]] = {}


def _big_table_counts(session: Session) -> tuple[int, int, int]:
    """(float_snapshots, transactions, holdout transactions) row counts."""
    key = (session.scalar(select(func.max(FloatSnapshot.id))),
           session.scalar(select(func.max(Transaction.id))))
    if key not in _big_counts:
        _big_counts.clear()
        _big_counts[key] = (
            session.scalar(select(func.count()).select_from(FloatSnapshot)) or 0,
            session.scalar(select(func.count()).select_from(Transaction)) or 0,
            session.scalar(select(func.count()).select_from(Transaction).where(
                Transaction.is_holdout.is_(True))) or 0)
    return _big_counts[key]


def _meta(session: Session, key: str) -> object:
    row = session.get(SystemMeta, key)
    return row.value if row else None


def summary(session: Session, settings: Settings) -> DataSummary:
    counts = [DataCount(table=name, rows=session.scalar(
        select(func.count()).select_from(model)) or 0) for name, model in COUNTED]
    snapshots, txns, holdout = _big_table_counts(session)
    counts[3:3] = [DataCount(table="float_snapshots", rows=snapshots),
                   DataCount(table="transactions", rows=txns)]
    counts.append(DataCount(table="transactions_holdout", rows=holdout))
    seed, version, labels = (_meta(session, k) for k in ("seed", "data_version",
                                                         "synthetic_labels"))
    anomalies = labels.get("anomalies", []) if isinstance(labels, dict) else []
    agents = {a["agent_code"] for a in anomalies if isinstance(a, dict) and "agent_code" in a}
    return DataSummary(
        seed=seed if isinstance(seed, int) else None, configured_seed=settings.seed,
        data_version=version if isinstance(version, str) else None,
        period=data_period(session),
        counts=counts, labelled_anomalous_agents=len(agents),
        generated_at=datetime.now(UTC))


def assumptions_path() -> Path | None:
    for d in DOC_DIRS:
        path = d / ASSUMPTIONS_FILE
        if path.is_file():
            return path
    return None


def assumptions() -> AssumptionsDoc | None:
    path = assumptions_path()
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    first = next((ln for ln in text.splitlines() if ln.startswith("# ")), "# Synthetic data")
    return AssumptionsDoc(title=first[2:].strip(), markdown=text)
