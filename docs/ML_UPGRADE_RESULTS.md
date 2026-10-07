# ML Upgrade — Results (synthetic data only)

Every number here is measured on the **synthetic** dataset (seed 42, 300 agents), fixed clock
(`CLOCK_MODE=fixed`, timeline 2026-01-05..2026-05-04), isolated verify stack. None of it is a
real-world accuracy claim. Raw outputs: `docs/ml_results/before.json`, `docs/ml_results/after.json`
(script `backend/scripts/ml_benchmark.py`); API timings `scripts/perf/out/api_ml_before.json`,
`scripts/perf/out/api_ml_final.json`.

- **Before** = the committed artifacts at the start (forecast `lgbq-1.0.0-56571e7f`, anomaly
  `iforest-1.0.0-25b1a7f6`, backed up in `D:\Backup\agentpulse_artifacts_before_ml`), scored by the
  same benchmark code. Its impact rows include the replay bug fix (below), so both columns use the
  same replay.
- **After** = served now: forecast `lgbq-1.1.0-7636a2e5` (q10 / q90 retrained on the train period +
  conformal bands; q50 = the unchanged 1.0.0 booster, DECISIONS ML2), anomaly
  `iforest-1.0.0-9aabad82` (contamination chosen on validation), helper model `helper-1.0.0-4305ed17`.
- Blind test = the last 14 days (2026-04-21..05-04), scored once. Validation = 04-07..04-20.

## Main numbers

| Area | Metric | Before | After |
|---|---|---|---|
| Forecast | MAE q50 cash-out / cash-in (BDT) | 2,211.4 / 2,162.8 | 2,211.7 / 2,162.6 |
| Forecast | Mean pinball q10/q50/q90 cash-out / cash-in | 708.5 / 686.8 | 705.5 / 686.4 |
| Forecast | Baselines cash-out: last week / 4-week mean / weekly exp. smoothing | 3,055.7 / 2,705.6 / 2,606.2 | same (baselines) |
| Forecast | Baselines cash-in: last week / 4-week mean / weekly exp. smoothing | 2,932.2 / 2,488.9 / 2,410.0 | same (baselines) |
| Bands | q10-q90 coverage, all hours, cash-out / cash-in (nominal 0.80) | 0.874 / 0.891 | 0.859 / 0.897 |
| Bands | coverage, open hours (68% of rows) cash-out / cash-in | 0.814 / 0.838 | 0.792 / 0.848 |
| Bands | largest open-hour group distance from 0.80, cash-out / cash-in | 0.031 / 0.071 | 0.025 / 0.083 |
| Bands | mean band width cash-out / cash-in (BDT) | 6,830 / 6,793 | 6,634 / 6,633 |
| Stockout (decision input, 24 h) | Brier / AUC | 0.0437 / 0.971 | 0.0438 / 0.971 |
| Stockout (decision input) | recall / precision at amber cut 0.20 | 0.984 / 0.240 | 0.984 / 0.239 |
| Stockout (decision input) | time-to-stockout MAE (h), events with a prediction | 3.50 (1,067 of 1,490) | 3.32 (1,086 of 1,490) |
| Stockout, joint (not default) | Brier / AUC / recall / precision | - | 0.0349 / 0.970 / 0.893 / 0.449 |
| Stockout, refill-aware view | Brier / AUC / recall / precision / TTS MAE | - | 0.0267 / 0.975 / 0.852 / 0.576 / 3.35 h |
| Anomaly | contamination | 0.005 (picked with holdout visible) | 0.0025 (validation folds) |
| Anomaly | blind window precision / recall | 0.957 / 0.733 (not blind) | 0.941 / 0.533 |
| Anomaly | agent precision / recall | 0.80 / 0.80 | 0.80 / 0.80 |
| Anomaly | precision at 10 / 20 / 30 / 50 (Isolation Forest) | 1.00 / 0.95 / 0.80 / 0.54 | 1.00 / 0.95 / 0.80 / 0.54 |
| Impact (perfect delivery) | stockout agent-hours, baseline / AI | 322 / 76 | 322 / 75 |
| Impact | value turned away AI (BDT) | 761,050 | 758,609 |
| Impact | van trips baseline / AI | 786 / 1,069 | 786 / 1,078 |
| Impact | full action cost AI - baseline (BDT; van, urgent, top-up fee, travel) | +879,147 | +865,096 |
| Impact, imperfect delivery | stockout h baseline / AI; value saved | 443 / 99; 2,705,914 | 443 / 104; 2,650,384 |
| Matching (assignment, default) | cash receivers matched / fully covered / need covered / km per hand-over | 789 / 287 / 8.0% / 1.88 | 788 / 277 / 8.2% / 1.88 |
| Matching (flow, opt-in) | matched / fully covered / need covered / km per hand-over; replay stockout h / van trips | 741 / 285 / 12.1% / 2.24; 76 / 1,032 | 722 / 278 / 12.5% / 2.26; 75 / 1,055 |
| Helper model (simulated) | blind AUC / Brier (true law 0.158) / ECE | - | 0.757 / 0.162 / 0.028 |

Original first baseline run (before the replay bug fix): AI van trips 1,065, swaps 281 (the
documented METHODS.md numbers). The fix alone changes AI trips to 1,069 with identical service.

## Reading

- **Forecast**: retraining on the train period only (14 days less data) with validation selection
  improved MAE (2,206.7 / 2,145.0) when q50 could grow, but that q50 broke the live tick budget;
  capped at the old size it was worse than the old q50 (2,226.9 / 2,170.2), so the old q50 is served.
  The model beats every baseline, including the stronger weekly smoothing (by 15% / 10%).
- **Bands**: calibration lifts the new model's under-covering cash-out groups (raw 0.766-0.776 ->
  0.775-0.809) and narrows bands (-3%) with better pinball. Cash-in stays above 0.80 (0.848)
  because much demand is exactly 0 and the lower bound cannot rise without missing all those
  zeros; its group gap got slightly worse (0.071 -> 0.083). Tier 3 cash-out is 0.775 on the blind
  test: conformal coverage holds only while the test period behaves like validation.
- **Stockout**: the old method stays the decision input. The joint method is better calibrated
  (Brier -20%) with equal ranking (AUC 0.970 vs 0.971) but flags fewer realised stockouts at the
  current cut. The refill-aware view is the best calibrated against the logged history, which
  contains the agents' own refills; it is shown as an extra reading only.
- **Anomaly**: the honest blind recall is 0.53 (16 of 30 windows), down from the 0.73 that was
  measured with the holdout visible. Volume bursts are the weak kind (0.30). Robust covariance
  ranks about as well (P@10 0.90 vs 1.00); Isolation Forest stays.
- **Impact**: with 10% failed and 25% late physical deliveries, both sides get worse (baseline
  322 -> 443 h, AI 75 -> 104 h); the AI's avoided hours grow (+37%) because the baseline's single
  urgent van per alert is hit harder. Counting all action costs, the AI costs 865k BDT more than
  the baseline over 14 days (van trips alone: +438k), against 2.05 M BDT of turned-away value saved.
- **Helper model**: learned from simulated behaviour only. In the policy simulation (563 blind
  requests, 165 with no feasible helper) the learned order did not beat the rule score
  (acceptance 0.276 vs 0.278, covered 0.341 vs 0.348). Learned wave sizing on top of the rule order
  cut asks 7% (1,090 vs 1,168) and covered slightly more (0.354), but cover took longer (5.8 vs
  5.6 min). With 2-person waves (sensitivity) the learned order had the best acceptance (0.351 vs
  0.340) and fastest cover (7.4 vs 8.3 min) but covered fewer requests (0.375 vs 0.384). All opt-in.

## API p95 and live tick (budgets in brackets)

Before: verify stack, fixed clock. After: final verify stack, live clock (default mode), so the
columns are not like-for-like; endpoints this upgrade did not touch (swaps, inbox) also slowed
about 2x in the same run. All 64 timed endpoints are within budget, no 5xx.

| Endpoint | Before p95 (ms) | After p95 (ms) |
|---|---|---|
| GET /agents/{id}/risk [agent] (300) | 11.2 | 13.8 |
| GET /agents/risk?horizon=24 [distributor] (500) | 117.2 | 47.0 |
| GET /agents/risk?horizon=72&sort=risk&page_size=100 (500) | 33.4 | 55.9 |
| GET /map/agents (500) | 34.5 | 54.5 |
| GET /agents/{id}/stockout [agent] (500) | 12.7 | 15.6 |
| POST /agents/{id}/whatif (300) | 23.3 | 42.8 |
| GET /swaps [agent] / [distributor] (300) | 15.8 / 14.3 | 32.8 / 32.0 |
| GET /liquidity-requests/inbox [agent] (300) | 15.0 | 30.0 |
| GET /admin/drift [admin] (300) | 9.0 | 19.1 |

| Live hourly tick (budget 60 s) | Before | After |
|---|---|---|
| Total | 25.1 s | 50.2 s |
| forecast / risk / anomalies / rebalance | 10.7 / 9.3 / 4.3 / 0.5 s | 21.4 / 19.6 / 8.0 / 0.9 s |
| Daily backtest at bootstrap | 74.3 s | 70.1 s |

A first version (uncapped q50, 2,000-path refill view) measured ~87 s per tick at bootstrap;
DECISIONS ML2 explains the fix.
