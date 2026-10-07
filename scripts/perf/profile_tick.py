"""Profile one live data tick, stage by stage, without changing the database.

Run inside the backend container of the verify project (synthetic data):
  docker compose -p agentpulse-verify exec -T backend python /app/scripts_perf/profile_tick.py
Each stage is forced (cache keys ignored) inside its own transaction that is rolled back, so the
served caches are untouched. Sub-steps of the risk stage are timed by wrapping its helpers.
Prints one JSON object: seconds per stage and per risk sub-step.
"""

import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.rules.risk_rules import build_config
from app.services import anomaly_scan, backtest, forecast, rebalance, risk

subs: dict[str, float] = defaultdict(float)


def wrap(module: Any, name: str, label: str) -> None:
    fn: Callable[..., Any] = getattr(module, name)

    def timed(*args: Any, **kwargs: Any) -> Any:
        t = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            subs[label] += time.perf_counter() - t

    setattr(module, name, timed)


wrap(risk, "load_quantiles", "risk.load_quantiles")
wrap(risk, "load_balances", "risk.load_balances")
wrap(risk, "load_history", "risk.load_history")
wrap(risk.refill, "habits", "risk.refill_habits")
wrap(risk, "project_agent", "risk.project_agents")
wrap(risk, "run_paths", "risk.run_paths(base+refill)")
wrap(risk, "sample_joint", "risk.sample_joint")
wrap(risk.notify, "risk_changed", "risk.notify")


def stage(name: str, fn: Callable[[Session], Any], out: dict[str, float]) -> None:
    with Session(get_engine()) as s:
        t = time.perf_counter()
        s.begin()
        try:
            fn(s)
            s.flush()
        finally:
            out[name] = round(time.perf_counter() - t, 2)
            s.rollback()


def main() -> None:
    settings = get_settings()
    rcfg, scfg, ccfg = rebalance.configs(settings)
    out: dict[str, float] = {}
    stage("forecast", lambda s: forecast.precompute(s, settings.artifacts_dir, force=True), out)
    stage("risk", lambda s: risk.precompute(s, build_config(settings.risk_thresholds),
                                            settings.seed, force=True), out)
    stage("rebalance", lambda s: rebalance.precompute(s, rcfg, scfg, ccfg, force=True), out)
    stage("anomalies", lambda s: anomaly_scan.precompute(s, settings.artifacts_dir, force=True),
          out)
    if "--backtest" in sys.argv:
        stage("backtest", lambda s: backtest.precompute(s, settings, force=True), out)
    print(json.dumps({"stages_s": out, "risk_sub_s": {k: round(v, 2) for k, v in subs.items()}},
                     indent=1))


if __name__ == "__main__":
    main()
