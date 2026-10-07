"""Stress test: the impact backtest at different stockout incidence (read-only, nothing stored).

Knob: BUFFER_FACTOR k scales the float level of every routine refill (cash_target, em_target)
and the opening balances in the evaluation world, capped at capacity. Demand, forecasts and the
trained models are NOT changed or retrained; only how much float agents hold changes. Run with
CLOCK_MODE=fixed on the isolated verify stack, same seed and agents as the stored backtest.

  python -m scripts.incidence_sensitivity --calibrate 1.0 0.9 0.8 0.7    # baseline only
  python -m scripts.incidence_sensitivity --factors 1.0 0.8 0.6 --out /tmp/incidence.json
"""

import argparse
import json
from dataclasses import replace
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.services import holdout_inputs, impact, rebalance
from app.services.impact_policies import AiPolicy, BaselinePolicy
from app.services.impact_sim import World, run

HORIZON_H = 24


def scaled(w: World, k: float) -> World:
    cash_cap, em_cap = w.cash_cap[:, None], w.em_cap
    return replace(
        w, cash_target=np.minimum(w.cash_target * k, cash_cap), em_target=np.minimum(
            w.em_target * k, em_cap), cash0=np.minimum(w.cash0 * k, w.cash_cap),
        em0=np.minimum(w.em0 * k, em_cap))


def summary(w: World, o: Any, fee_pct: float) -> dict[str, Any]:
    cells = impact.tally(w, o)
    hours = sum(c.stockout_hours for c in cells.values())
    lost_out = sum(c.lost_out for c in cells.values())
    agent_hours = len(w.sites) * w.n_hours
    biz = int(((w.hod >= 8) & (w.hod < 21)).sum()) * len(w.sites)
    return {"stockout_hours": hours, "share_of_agent_hours": round(hours / agent_hours, 5),
            "share_of_business_agent_hours": round(hours / biz, 5),
            "value_lost_bdt": round(sum(c.lost for c in cells.values()), 2),
            "cashout_fee_lost_bdt": round(lost_out * fee_pct / 100, 2),
            "van_trips": sum(len(c.trips) for c in cells.values()),
            "agent_hours": agent_hours}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", nargs="*", type=float, default=[])
    ap.add_argument("--factors", nargs="*", type=float, default=[])
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    settings = get_settings()
    rcfg, scfg, ccfg = rebalance.configs(settings)
    cfg = impact.impact_config(settings)
    with Session(get_engine()) as session:
        h = holdout_inputs.load(session, settings, cfg, max(rcfg.horizon_h, HORIZON_H))
    if h is None:
        raise SystemExit("holdout inputs unavailable (is the DB the fixed seeded set?)")
    result: dict[str, Any] = {"seed": settings.seed, "clock_mode": settings.clock_mode,
                              "agents": len(h.agents), "calibration": {}, "levels": []}
    for k in args.calibrate:
        w = scaled(h.world, k)
        s = summary(w, run(w, BaselinePolicy(w, cfg, ccfg.topup_eta_h)), cfg.cashout_fee_pct)
        result["calibration"][str(k)] = s
        print(f"k={k}: baseline {s['stockout_hours']} h, {s['share_of_agent_hours']:.4%}",
              flush=True)
    for k in args.factors:
        w = scaled(h.world, k)
        base = summary(w, run(w, BaselinePolicy(w, cfg, ccfg.topup_eta_h)), cfg.cashout_fee_pct)
        ai = summary(w, run(w, AiPolicy(w, h.forecasts, cfg, rcfg, scfg, ccfg)),
                     cfg.cashout_fee_pct)
        red = base["stockout_hours"] - ai["stockout_hours"]
        row = {"buffer_factor": k, "baseline": base, "ai": ai,
               "stockout_hours_avoided": red,
               "percent_reduction": round(red / base["stockout_hours"], 4)
               if base["stockout_hours"] else None,
               "value_saved_bdt": round(base["value_lost_bdt"] - ai["value_lost_bdt"], 2),
               "cashout_fee_saved_bdt": round(base["cashout_fee_lost_bdt"]
                                              - ai["cashout_fee_lost_bdt"], 2),
               "van_trips_avoided": base["van_trips"] - ai["van_trips"]}
        result["levels"].append(row)
        print(f"k={k}: base {base['stockout_hours']} h ({base['share_of_agent_hours']:.4%}) "
              f"ai {ai['stockout_hours']} h; reduction {row['percent_reduction']}", flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
