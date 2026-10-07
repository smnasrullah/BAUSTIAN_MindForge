"""Opportunity sizing illustration (not a forecast). Plain Python, no dependencies.

  python scripts/perf/opportunity_sizing.py            # prints the markdown tables
  python scripts/perf/opportunity_sizing.py --upay 50000   # adds a row for a hypothetical count

Inputs per incidence level come from backend/data/evidence/incidence_sensitivity.json (measured
on the 300-agent synthetic backtest, stress test of the buffer knob; NOT real-world incidence).
  stockout hours per year   = agents x 8,760 x incidence (share of agent-hours)
  BDT per stockout hour     = baseline value turned away / baseline stockout hours (measured)
  worth of a 1% cut         = 0.01 x stockout hours per year x BDT per stockout hour
  worth of measured cut     = stockout hours per year x (value saved / baseline stockout hours)
Values are customer transaction value (BDT turned away), plus the cash-out fee at the config
rate. They are not agent or provider revenue; the split is unknown, to be validated.
"""

import argparse
import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[2] / "backend/data/evidence/incidence_sensitivity.json"
HOURS_PER_YEAR = 8_760
UPAY_AGENTS: int | None = None  # not in our sources; set here or pass --upay
# (label, count, year, source name). Registered and active definitions differ.
PUBLIC = (
    ("Registered agent outlets, 2024", 1_828_870, "IMF FAS via FRED"),
    ("Registered agent outlets, 2023", 1_724_515, "IMF FAS via FRED"),
    ("Active MFS agents, Aug 2025 (about)", 1_440_000, "Daily Sun / Bangladesh Bank"),
    ("Agents, Jan 2023 (about)", 1_570_000, "Financial Express"),
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upay", type=int, default=UPAY_AGENTS)
    args = ap.parse_args()
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    pops = [("Per 10,000 agents", 10_000, "-")] + list(PUBLIC)
    if args.upay:
        pops.append(("upay agents (input)", args.upay, "UPAY_AGENTS input"))
    for lv in data["levels"]:
        b, a = lv["baseline"], lv["ai"]
        inc, h = b["share_of_agent_hours"], b["stockout_hours"]
        per_h = b["value_lost_bdt"] / h
        fee_h = b["cashout_fee_lost_bdt"] / h
        saved_h = lv["value_saved_bdt"] / h
        print(f"\n### Incidence {inc:.2%} of agent-hours (buffer factor {lv['buffer_factor']}),"
              f" measured cut {lv['percent_reduction']:.0%}")
        print(f"BDT turned away per stockout hour {per_h:,.0f}; cash-out fee {fee_h:,.0f}\n")
        print("| Population | Agents | Stockout h / year | 1% cut: txn value BDT m / year |"
              " 1% cut: fee BDT m / year | Measured cut: txn value BDT m / year |")
        print("|---|---|---|---|---|---|")
        for label, n, _src in pops:
            hy = n * HOURS_PER_YEAR * inc
            print(f"| {label} | {n:,} | {hy:,.0f} | {0.01 * hy * per_h / 1e6:,.1f} |"
                  f" {0.01 * hy * fee_h / 1e6:,.2f} | {hy * saved_h / 1e6:,.1f} |")


if __name__ == "__main__":
    main()
