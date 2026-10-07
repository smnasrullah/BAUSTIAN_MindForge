# Incidence sensitivity (stress test, synthetic data)

**These rates are NOT real-world incidence.** They are three buffer settings of one synthetic world,
chosen so that the baseline policy shows about 0.3%, 1% and 3% of agent-hours in stockout. Real
incidence at upay or any MFS provider is unknown, to be validated (see PROBLEM_EVIDENCE.md §5).

## Method
- Knob: `BUFFER_FACTOR` k in [backend/scripts/incidence_sensitivity.py](../backend/scripts/incidence_sensitivity.py) (`scaled()`). It multiplies every routine-refill float target (`World.cash_target`, `World.em_target`) and the opening balances (`cash0`, `em0`) in the evaluation world, capped at capacity. It is a buffer/refill-level knob only.
- Demand, forecasts, and the trained models are unchanged. **No model is retrained.** The forecaster still sees the same logged history, so it is valid; only how much float agents hold changes. This is a stress test of the policy comparison, not a re-calibration of the generator.
- Same seed (42), same 300 agents, same 14 held-out days (2026-04-21..05-04), `CLOCK_MODE=fixed`, same policies and defaults as the stored impact backtest (alert at 20% of capacity, van 1,500 BDT/trip, cash-out fee 1.85%). Run on the isolated `agentpulse-verify` stack with its fixed-clock volume (`agentpulse-verify_fixed1`); nothing was stored in any database.
- Calibration (baseline only, measured): k = 1.0 → 0.319%; 0.8 → 0.379%; 0.65 → 0.566%; 0.5 → 0.818%; 0.45 → 1.034%; 0.4 → 1.296%; 0.35 → 1.784%; 0.28 → 2.985%; 0.25 → 3.788%.
- Share of agent-hours = stockout hours / (300 agents x 336 hours = 100,800). Business-hours share (08-21 only, 300 x 14 x 13 = 54,600 agent-hours) is higher: 0.59%, 1.91%, 5.51%.

## Results (measured)

| Level | k | Baseline stockout h | Baseline share of agent-hours | AI stockout h | AI share | Hours avoided | Reduction | Value saved (BDT) | Cash-out fee saved (BDT) | Van trips baseline / AI | Van trips avoided |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Base | 1.00 | 322 | 0.319% | 75 | 0.074% | 247 | 76.7% | 2,054,730 | 32,541 | 786 / 1,078 | -292 (AI uses more) |
| About 1% | 0.45 | 1,042 | 1.034% | 219 | 0.217% | 823 | 79.0% | 5,586,275 | 94,672 | 4,787 / 1,962 | 2,825 |
| About 3% | 0.28 | 3,009 | 2.985% | 697 | 0.691% | 2,312 | 76.8% | 13,315,319 | 236,144 | 10,265 / 2,339 | 7,926 |

Full numbers, seeds, git state and date: [backend/data/evidence/incidence_sensitivity.json](../backend/data/evidence/incidence_sensitivity.json).

Note: this in-memory rerun gives 75 AI stockout hours and 1,078 AI van trips at base. docs/METHODS.md §3 shows 76 and 1,065 (older run); docs/ML_UPGRADE_RESULTS.md:41 shows 1,078 AI trips for the current model. Baseline 322 h / 786 trips matches exactly. The 1-hour difference vs METHODS §3 was not investigated.

## What changes meaning with incidence
- **The percentage reduction (about 77-79%) is stable** across the three levels in this synthetic world. It is a property of the policy comparison, not of how often stockouts happen.
- **Absolute claims scale with incidence:** stockout hours avoided, BDT saved and cash-out fee saved grow roughly in proportion to baseline incidence (247 → 823 → 2,312 hours). The headline "2.05 M BDT saved" is meaningful only at the base incidence (about 0.3%); at 3x or 10x the incidence it is 3x or 6x larger.
- **"Van trips avoided" flips sign.** At the base incidence the AI uses more van trips than the 20% rule (+292). When baseline incidence is higher, the rule alerts far more often and the AI needs fewer trips (-2,825 and -7,926). The claim "fewer van trips" holds only at stressed incidence, not at the base.
- The 76% claim is relative to a fixed-threshold baseline in a world where agents start with large buffers; if real agents hold thinner buffers, the baseline looks worse and the absolute value is larger, but our stress test does not prove that real agents do.

## Limits
Synthetic demand and refill behaviour; one seed; one 14-day window; refill targets and opening balances scaled together (one knob among several possible); AI forecasts were not recomputed for the changed buffers. Delivery failure and delay are in docs/METHODS.md realism sensitivity (S4), not here.
