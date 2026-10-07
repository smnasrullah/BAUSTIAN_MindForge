"""ML-4: re-tune the 24 h amber cut of the JOINT stockout method on the validation period only.

Phase "validation": planning rounds inside the validation period (2026-04-07..04-20; every
24 h window ends before the blind test), the served forecaster, both projectors (no refill).
False alerts (FP) = (agent, round, float) cases flagged that did not run dry within 24 h. The
independent method at its amber cut sets the FP budget; the joint cut is the lowest grid cut
whose FP stays within that budget (the most stockouts caught for at most the same false
alerts). Written to --out with the rule, before the blind test is read.

Phase "blind": reads that file and scores both methods on the blind test once. The rule fixed
in advance: switch the default only when the joint method at its cut catches at least as many
stockouts (TP) with no more false alerts (FP) than the independent method at its cut.

Synthetic data, fixed clock, verify stack only. The served q50 booster was trained on targets
that include the validation period, so validation forecasts are somewhat better than they would
be live (stated with the result).

    python -m scripts.stockout_cut --phase validation --out FILE
    python -m scripts.stockout_cut --phase blind --out FILE
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.models import Agent
from app.rules.risk_rules import HEADLINE_HORIZON, build_config
from app.services import holdout_inputs, impact, rebalance
from ml.data_gen.dataset import build_dataset
from ml.evaluation import stockout_eval
from ml.features.panel import load_panel
from ml.inference.forecaster import Forecaster
from ml.training.splits import FIXED_SPLIT
from scripts.ml_benchmark import (
    STOCKOUT_HORIZON_H,
    current_projector,
    joint_projector,
    stockout_rounds,
)

log = logging.getLogger(__name__)
CUT_GRID = tuple(round(0.01 * k, 2) for k in range(1, 50))  # amber stays below red (0.50)


def confusion(c: stockout_eval.Collected, cut: float) -> dict[str, int]:
    p = np.array(c.p["cash"] + c.p["emoney"])
    y = np.array(c.real["cash"] + c.real["emoney"], dtype=bool)
    flag = p >= cut
    return {"tp": int((flag & y).sum()), "fp": int((flag & ~y).sum()),
            "fn": int((~flag & y).sum()), "cases": int(len(y))}


def choose_cut(ind: stockout_eval.Collected, joint: stockout_eval.Collected, ind_cut: float
               ) -> tuple[float | None, dict[str, Any]]:
    budget = confusion(ind, ind_cut)
    grid = [{"cut": c} | confusion(joint, c) for c in CUT_GRID]
    ok = [g for g in grid if g["fp"] <= budget["fp"]]
    chosen = min(ok, key=lambda g: g["cut"]) if ok else None
    return (None if chosen is None else float(chosen["cut"])), {
        "independent_at_cut": {"cut": ind_cut} | budget, "joint_grid": grid,
        "joint_chosen": chosen}


def validation(out: Path) -> dict[str, Any]:
    settings = get_settings()
    split = FIXED_SPLIT
    with Session(get_engine()) as session:
        panel = load_panel(session)
        ds = build_dataset(settings.seed, len(panel.agent_ids))
        by_id = {a.id: a for a in session.scalars(select(Agent))}
    code_index = {a.code: i for i, a in enumerate(ds.agents)}
    rows = np.array([r for r, aid in enumerate(panel.agent_ids.tolist())
                     if by_id[aid].code in code_index], dtype=np.int64)
    agents = [by_id[int(panel.agent_ids[r])] for r in rows]
    idx = [code_index[a.code] for a in agents]
    h0, end = split.train_end, split.val_end
    cfg = impact.impact_config(settings)
    starts = [o for o in holdout_inputs.origins(h0, cfg, end) if o + STOCKOUT_HORIZON_H <= end]
    fc = Forecaster.load(settings.artifacts_dir, settings.forecast_conformal)
    fc.threads = 0
    raw = holdout_inputs.predict(fc, panel, rows, starts, STOCKOUT_HORIZON_H, end)
    fl, span = ds.floats, slice(h0, end)
    forecasts = {o - h0: v for o, v in raw.items()}
    balance = {"cash": fl.cash[idx, span], "emoney": fl.emoney[idx, span]}
    unmet = {"cash": fl.unmet_out[idx, span], "emoney": fl.unmet_in[idx, span]}
    rounds = sorted(forecasts)
    ids = [a.id for a in agents]
    t0 = time.perf_counter()
    ind = stockout_eval.collect(rounds, balance, unmet, forecasts,
                                current_projector(settings.seed, ids), STOCKOUT_HORIZON_H)
    joint = stockout_eval.collect(rounds, balance, unmet, forecasts,
                                  joint_projector(settings.seed, agents, h0,
                                                  settings.artifacts_dir, panel, None, False),
                                  STOCKOUT_HORIZON_H)
    ind_cut = build_config(settings.risk_thresholds).cuts[HEADLINE_HORIZON].amber
    cut, table = choose_cut(ind, joint, ind_cut)
    result = {
        "phase": "validation", "data": "synthetic", "clock": "fixed",
        "model_version": fc.model_version, "period_h": [h0, end], "rounds": len(rounds),
        "horizon_h": STOCKOUT_HORIZON_H,
        "rule": "joint cut = lowest grid cut whose false alerts <= the independent method's at "
                "its amber cut (validation); switch only if on the blind test joint TP >= "
                "independent TP and joint FP <= independent FP",
        "joint_cut": cut, "seconds": round(time.perf_counter() - t0, 1),
        "caveat": "served q50 was trained on targets including the validation period",
    } | table
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def blind(out: Path) -> dict[str, Any]:
    chosen = json.loads(out.read_text(encoding="utf-8"))
    if chosen.get("phase") != "validation" or chosen.get("joint_cut") is None:
        raise SystemExit("run --phase validation first (no joint cut chosen)")
    settings = get_settings()
    ind_cut = float(chosen["independent_at_cut"]["cut"])
    cut = float(chosen["joint_cut"])
    with Session(get_engine()) as session:
        panel = load_panel(session)
        horizon = max(rebalance.configs(settings)[0].horizon_h, STOCKOUT_HORIZON_H)
        h = holdout_inputs.load(session, settings, impact.impact_config(settings), horizon)
    if h is None:
        raise SystemExit("holdout inputs unavailable (is the DB the fixed seeded set?)")
    ids = [a.id for a in h.agents]
    projectors = {"independent_no_refill": current_projector(settings.seed, ids),
                  "joint_no_refill": joint_projector(settings.seed, h.agents, h.h0,
                                                     settings.artifacts_dir, panel, None, False)}
    unmet = {"cash": h.unmet["cash_out"], "emoney": h.unmet["cash_in"]}
    rounds = stockout_rounds(h)
    col = {n: stockout_eval.collect(rounds, h.balance, unmet, h.forecasts, p, STOCKOUT_HORIZON_H)
           for n, p in projectors.items()}
    ind = confusion(col["independent_no_refill"], ind_cut)
    joint = confusion(col["joint_no_refill"], cut)
    joint_old = confusion(col["joint_no_refill"], ind_cut)
    switch = joint["tp"] >= ind["tp"] and joint["fp"] <= ind["fp"]
    result = chosen | {"phase": "blind_scored", "blind": {
        "rounds": len(rounds), "independent_at_cut": {"cut": ind_cut} | ind,
        "joint_at_chosen_cut": {"cut": cut} | joint,
        "joint_at_old_cut": {"cut": ind_cut} | joint_old,
        "switch_default": switch,
        "report_independent": stockout_eval.report(col["independent_no_refill"], ind_cut)["both"],
        "report_joint": stockout_eval.report(col["joint_no_refill"], cut)["both"]}}
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[stockout-cut] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("validation", "blind"), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    res = validation(args.out) if args.phase == "validation" else blind(args.out)
    print(json.dumps({k: v for k, v in res.items() if k != "joint_grid"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
