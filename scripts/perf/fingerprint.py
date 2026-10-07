"""Fingerprint of every served cache (synthetic data): one SHA-256 per table, ids and
generated/created timestamps left out. Run inside the backend container of the verify project:
  docker compose -p agentpulse-verify exec -T -e PYTHONPATH=/app backend \
      python /app/scripts_perf/fingerprint.py [--recompute] [--old-history]
Without flags: the stored caches. --recompute: force every pipeline stage again in one
transaction, hash, roll back (nothing changes). --old-history: during that recompute, load the
refill-aware history with the row-by-row loader (the code before Phase 1B) on Postgres too.
"""

import hashlib
import json
import re
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.models import (
    Anomaly,
    Forecast,
    ForecastExplanation,
    ImpactResult,
    Recommendation,
    RiskLevel,
    StockoutPrediction,
    SwapSuggestion,
    SystemMeta,
)
from app.rules.risk_rules import build_config
from app.services import (
    anomaly_scan,
    backtest,
    fairness,
    forecast,
    impact,
    rebalance,
    risk,
    risk_history,
)

SKIP = {"id", "generated_at", "created_at", "updated_at"}
ROW_IDS = {"swap_id"}  # rationale link to a swap row: a new auto id on every recompute
SWAP_REF = re.compile(r"swap #\d+")  # the same id inside rule-trace text


def table_hash(session: Session, model: Any) -> tuple[int, str]:
    cols = [c for c in model.__table__.columns if c.name not in SKIP]
    rows = sorted(SWAP_REF.sub("swap #N", json.dumps([str(strip(getattr(r, c.key), ROW_IDS))
                                                      for c in cols]))
                  for r in session.scalars(select(model)))
    return len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


MODELS: dict[str, Any] = {
    "forecasts": Forecast, "explanations": ForecastExplanation, "stockout": StockoutPrediction,
    "risk": RiskLevel, "recommendations": Recommendation, "swaps": SwapSuggestion,
    "anomalies": Anomaly, "impact": ImpactResult}


def strip(value: Any, drop: set[str] = SKIP) -> Any:
    """A JSON value without the keys in `drop` (timestamps, row ids)."""
    if isinstance(value, dict):
        return {k: strip(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [strip(v, drop) for v in value]
    return value


def recompute(session: Session) -> None:
    s = get_settings()
    rcfg, scfg, ccfg = rebalance.configs(s)
    forecast.precompute(session, s.artifacts_dir, force=True)
    risk.precompute(session, build_config(s.risk_thresholds), s.seed, force=True)
    rebalance.precompute(session, rcfg, scfg, ccfg, force=True)
    anomaly_scan.precompute(session, s.artifacts_dir, force=True)
    backtest.precompute(session, s, force=True)
    session.flush()


def main() -> None:
    if "--old-history" in sys.argv:
        risk_history._fill_postgres = risk_history._fill_rows  # type: ignore[assignment]
    out: dict[str, Any] = {}
    with Session(get_engine()) as session:
        session.begin()
        if "--recompute" in sys.argv:
            recompute(session)
        for name, model in MODELS.items():
            out[name] = table_hash(session, model)
        out["holdout_key_current"] = backtest.stale_key(session, get_settings()) is None
        for key in (impact.CACHE_KEY, fairness.CACHE_KEY):
            row = session.get(SystemMeta, key)
            out[key] = hashlib.sha256(json.dumps(strip(row.value), sort_keys=True, default=str)
                                      .encode()).hexdigest()[:16] if row else None
        session.rollback()
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
