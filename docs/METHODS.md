# Methods (AgentPulse AI)

How each number on screen is produced, and which code produces it. Paths and tables refer to docs/ARCHITECTURE.md. Items not yet decided are listed under "Open questions"; this file does not guess them.
Principle: rules and ML compute every number; the LLM only words them; a human approves anything that moves money.

## 1. Synthetic data generation

| Item | Method | Implemented in |
|---|---|---|
| Source | Fully synthetic, no real customer or agent data | `backend/ml/data_gen/` |
| Seed | One fixed random seed for all generators; stored in `system_meta.seed` | `backend/ml/data_gen/`, `system_meta` |
| Entities | Distributors (district, hub lat/lon); agents (district, upazila, `area_type` urban/peri/rural, lat/lon, cash + e-money capacity, opened_on); hourly flows per agent; events; daily weather; demo users; Playbook docs | tables `distributors`, `agents`, `agent_hourly`, `events`, `weather_daily`, `users`, `knowledge_docs` |
| Hourly flows | Per agent and hour: cash_in/out, emoney_in/out, txn_count, resulting cash/e-money balance | `agent_hourly` |
| Event effects | Event types salary, eid, hat_bazar, weather, holiday with `intensity` and optional district scope; they shift hourly flows | `events`, `weather_daily` |
| Distributions + assumptions | Documented in docs/SYNTHETIC_ASSUMPTIONS.md (single source; not repeated here) | docs/SYNTHETIC_ASSUMPTIONS.md |
| Holdout | Last 14 days flagged `is_holdout = true`; never used for training | `agent_hourly.is_holdout` |
| Versioning | `system_meta.data_version` compared to code version; regenerate only on mismatch (idempotent) | `backend/bootstrap.py` step 5 |
| Clock | The forecast origin is stored in `system_meta.sim_now` and read through `app/core/clock.py`. Fixed clock: SIM_NOW (2026-04-30 20:00 Dhaka), identical on every PC. Live clock (default): the current hour, moved by the hourly tick (see "Live clock vs fixed clock" below) | `backend/app/core/clock.py`, `system_meta` |

## 2. Forecasting (F1, F2, F6)

| Item | Method | Implemented in |
|---|---|---|
| Model | LightGBM quantile regression, one booster per target and quantile: q10 / q50 / q90 (low / expected / high) = 6 boosters; lr 0.05, min 100 rows/leaf; q10 / q90 leaves (31 / 63) and rounds (150-600) chosen on the validation period, q50 = the 1.0.0 booster (31 leaves, 300 rounds; §ML upgrade), `deterministic=true`, fixed seed | `backend/ml/training/train.py` |
| Targets | Hourly **cash_out** and **cash_in** demand per agent (observed served BDT from `transactions`), trained separately. Cash float is drawn by cash_out, e-money float by cash_in; the API returns them as `float_type` cash / emoney | `forecasts` (q_low, q_mid, q_high, horizon_h) |
| Multi-horizon | Direct: one row per (agent, origin t0, horizon h = 1..72); target hour t = t0 + h - 1; `horizon_h` is a feature. Only demand before t0 is read | `backend/ml/features/build.py` |
| Features | Target-hour calendar: hour, day of week, day of month. Events at the target hour for the agent's district (from `events`): salary (1st-3rd), factory wage, Eid day number, holiday, hat-bazar, severe weather. Weather of the target day: rain_mm, temp_c. Agent: tier, area type, district, cash/e-money capacity. History (divided by `scale`): most recent observed same hour (lag 24 / 48 / 72 h depending on h), lag 168 h, lag 336 h, same-hour mean of last 4 weeks, rolling 24 h mean, last hour; plus log(scale) | `backend/ml/features/` |
| Scaling | `scale` = agent's trailing 168 h mean hourly demand at t0. The model predicts demand / scale; inference multiplies back (quantiles are scale-equivariant), so one model serves tier 1 and tier 3 agents | `backend/ml/features/build.py` |
| Quantile order | Predictions clipped at 0 and sorted per row so low <= expected <= high (no quantile crossing) | `backend/ml/inference/forecaster.py` |
| Split | Training rows: origins from day 28 (4 weeks of lag history), 2 random origin hours per agent-day, 12 random horizons each, kept only if the target hour is before the validation period (2026-04-07) → 450,148 rows. Validation 2026-04-07..04-20 (selection + calibration only); the last 14 days are the blind test, never trained on or selected on | `backend/ml/training/train.py` (`sample_rows`) |
| Backtest | Origins every holdout day at 08:00 and 20:00, all 300 agents, every horizon 1..72 inside the holdout (536,400 rows per target). Baseline = same hour last week, y[t-168], used as the point forecast for every quantile | `backend/ml/training/evaluate.py` |
| Metrics | MAE (q50) and pinball loss per quantile vs baseline; q10-q90 coverage; MAE by horizon bucket. Stored in `manifest.json` and `model_versions.metrics` | `backend/ml/artifacts/manifest.json`, `model_versions` |
| Serving | Inference is separate from training: bootstrap verifies artifact sha256, registers the active `model_versions` row, then caches forecasts for every agent at SIM_NOW (300 agents x 2 floats x 72 h = 43,200 rows). The API only reads this cache | `backend/ml/inference/`, `backend/app/services/forecast.py`, `GET /agents/{id}/forecast?horizon_hours=24` |

Fixed-mode benchmark (`CLOCK_MODE=fixed`). Held-out results (model `lgbq-1.0.0-56571e7f`, seed 42, data_version 1.0.0; BDT per agent-hour, all 24 hours incl. closed night hours):

| Target | Mean demand | MAE model | MAE baseline | MAE skill | Pinball q10 / q50 / q90 (mean) model | Pinball q10 / q50 / q90 (mean) baseline | q10-q90 coverage |
|---|---|---|---|---|---|---|---|
| cash_out | 5,052 | 2,211 | 3,056 | 27.6% | 404 / 1,106 / 616 (708) | 1,234 / 1,528 / 1,822 (1,528) | 87.4% |
| cash_in | 4,517 | 2,163 | 2,932 | 26.2% | 372 / 1,081 / 607 (687) | 1,303 / 1,466 / 1,630 (1,466) | 89.1% |

MAE by horizon (model / baseline): cash_out 1-6 h 2,395 / 3,326, 7-24 h 2,078 / 2,921, 25-72 h 2,240 / 3,073; cash_in 1-6 h 2,344 / 3,200, 7-24 h 2,044 / 2,811, 25-72 h 2,186 / 2,944. The band is wider than nominal (coverage 87.4% and 89.1% vs the 80% target), i.e. conservative. The conformal step (`backend/ml/inference/conformal.py`) guarantees at least 80%; the excess comes from hours with exactly zero demand, which any band that starts at 0 covers and which no valid offset can narrow. The excess is kept, not trimmed: in liquidity management a stockout is far more costly than mild excess float, so a band that errs wide is the safe direction and acts as a conservative safety envelope. Hour-level demand is noisy by construction (Poisson ticket counts, see SYNTHETIC_ASSUMPTIONS.md), so the MAE floor is high relative to the mean.
Limitations: the target is *served* demand, so hours where a float already hit zero are censored (under-stated); the target-day weather is taken as known (perfect weather forecast).
| Time-to-stockout (F2) | Per agent and float, from the balance at SIM_NOW (snapshot = top of the hour) and the cached q10/q50/q90 paths, assuming **no refill**: balance(h) = b0 + Σ(inflow − drain). Cash float: drain cash_out, inflow cash_in; e-money float the reverse. Monte Carlo, 2,000 paths, seeded per (seed, agent, float): each hour's demand is drawn from a two-piece linear quantile function through q10/q50/q90 (linear tails, clipped at 0); hours are tied by a Gaussian copula with a shared path factor (ρ = 0.6), drain and inflow independent (`STOCKOUT_METHOD=independent`, the default decision input; the joint alternative is in §ML upgrade). First passage to the floor (0 BDT) is interpolated inside the hour | `backend/ml/inference/stockout.py`, `backend/app/services/risk.py` |
| Stockout probability | P(stockout within 6 / 24 / 72 h) = share of paths whose first passage is ≤ h | `risk_levels.probability` |
| Most likely stockout time | Median first-passage time (earliest t with P(T ≤ t) ≥ 0.5). Null when no stockout within 72 h is the more likely outcome | `stockout_predictions.stockout_at`, `.hours_to_stockout` |
| Stockout confidence | With a time: share of paths that run out within ±max(1 h, 25%) of it. Without: P(no stockout within 72 h). Flat (zero-width) forecasts give exactly 1 | `stockout_predictions.confidence` |
| Stockout limitations | The decision input ignores refills (it answers "if nothing is done"), float coupling and cash-in / cash-out correlation, with an assumed ρ. The joint method and the refill-aware view (§ML upgrade) address these; the joint method is not the default because its recall at the current cut is lower | - |
| Why LightGBM quantile | Fast on CPU, handles mixed tabular features, native quantile loss gives an uncertainty band without extra models, works with SHAP | - |
| Explanation (F7) | Exact TreeSHAP (LightGBM `pred_contrib`, same values as `shap.TreeExplainer`, no extra dependency) on the q50 model for every agent's next 24 h at SIM_NOW, written with the forecast cache (same panel). Per-hour contributions x the agent's scale are summed to BDT and grouped into factors: salary (salary/wage flags + day of month, since salary days are fixed dates), eid, holiday, hat_bazar, rain (rain mm + severe flag), temperature, last_week (same-hour lags), recent_demand (last 24 h), time_of_day, weekday, agent_profile. usual (base value) + Σ impacts = model q50 for the window. Reasons = top 3 by \|impact\| with share ≥ 5%; impacts rounded (nearest 100 BDT from 1,000, else 10). Facts per factor (event name + today/tomorrow/in N days, last-week and last-24 h ratio vs the 7-day mean, rain mm, temperature, weekday) fill bn/en templates "<cause>: <effect>." (Bangla digits, lakh grouping); unknown factor or missing fact -> "Other factors". LLM may reword (§4) | `backend/ml/explain/`, `backend/app/services/explanation.py`, `forecast_explanations`, `GET /agents/{id}/explanations?target&lang` |
| Evidence pack (F7, LLM) | Per agent/float, deterministic: agent id/code/district, as_of, model_version, window, expected + usual demand, balance, capacity, stockout hours + confidence, risk per horizon, top drivers with facts. No `generated_at`, language-independent, so replay hashes match; every number a reason sentence quotes is in it | `backend/app/services/evidence.py` |
| Events (F6) | Admin CRUD (audit_log keeps before/after). The forecast cache key includes an events fingerprint, so forecasts, explanations, risk and recommendations refresh at the next precompute (restart) | `backend/app/services/events.py`, `GET/POST/PUT/DELETE /events` |
| What-if (F8) | Re-run the stockout projection for `{float_type, delta_amount}` added to the balance now, on the same seeded Monte Carlo paths as the risk cache (so `before` reproduces it and a positive delta can never move any path's stockout earlier); balance series = p10/p50/p90 of the no-refill paths per hour, floored at 0; new balance must stay in 0..capacity; no retraining | `backend/ml/inference/whatif.py`, `backend/app/services/whatif.py`, `POST /agents/{id}/whatif` |
| Map time scrubber (F10) | Risk cache also stores P(stockout by hour h), h = 0..72 (`stockout_predictions.prob_by_hour`). Level at hour h uses cut-offs linearly interpolated between the 6/24/72 h horizons (flat outside), so it equals the cached level at those horizons | `backend/app/rules/risk_rules.py` (`cut_at`), `backend/app/services/risk_map.py`, `GET /map/agents?at_hour` |
| Output contract | Every response carries `model_version` + `generated_at` | `backend/app/schemas/` |

## 3. Risk scoring and actions (F3, F4, F5, F9, F11)

| Item | Method | Implemented in |
|---|---|---|
| Risk inputs | Per agent and float: `stockout_at`, confidence, current balance, capacity | `backend/ml/inference/` -> `backend/app/rules/` |
| Risk level | Per float and horizon: P(stockout within h) ≥ red cut-off → red, ≥ amber cut-off → amber, else green. Cut-offs (amber / red): 6 h 0.10 / 0.30, 24 h 0.20 / 0.50, 72 h 0.35 / 0.70 (near horizons act on lower odds). Overridable via `RISK_THRESHOLDS` env (JSON `{"6": [amber, red]}`); a change re-runs the precompute. Agent level = worst float (per horizon). Headline level (float and agent) = the 24 h level: the 72 h view assumes no refill at all and would mark most agents amber (seed 42: 6 h 277/11/12, 24 h 136/128/36, 72 h 18/240/42 green/amber/red of 300), so it is shown per horizon, not headlined. Level confidence = max(p, 1 − p) | `backend/app/rules/risk_rules.py`, `risk_levels.level`, `.probability`, `.confidence` |
| Serving | Precomputed at bootstrap right after the forecast cache, for every agent at SIM_NOW (skipped when forecast cache, rules, method and seed are unchanged); API reads only the cache | `backend/app/services/risk.py`, `risk_read.py`; `GET /agents/{id}/summary`, `/stockout`, `/risk`, `GET /agents/risk?horizon&level&sort&page&page_size&q` |
| Display | Always colour + icon + word: Safe / Watch / Act now (নিরাপদ / নজরে রাখুন / এখনই করুন) | frontend per DESIGN.md |
| Rebalance (F4) | Per float over `REBALANCE_HORIZON_H` (24 h): need = peak cumulative net drain on the pessimistic path (drain q90, inflow q10); shortfall = need - balance. `amount_bdt` = shortfall + buffer (max(`REBALANCE_BUFFER_MIN_BDT`, `REBALANCE_BUFFER_SHARE` x capacity)), rounded up to 500, capped at free capacity. `deadline_at` = stockout time (earlier of the median projection and the pessimistic crossing) - `REBALANCE_LEAD_TIME_H`; urgent when already past. `kind` = swap / van when that channel is chosen, else add_cash / add_emoney | `backend/app/rules/rebalance_rules.py`, `backend/app/services/rebalance.py`, `recommendations`, `GET /agents/{id}/recommendation` |
| Delivery channel (F4) | First match wins: (1) e-money shortage -> `top_up` (digital, never a van); (2) cash and a pending/approved swap covers the whole amount -> `swap`; (3) cash receivers with time to deadline >= `VAN_LEAD_TIME_H` are greedily clustered per distributor (largest amount seeds; others within `VAN_CLUSTER_RADIUS_KM` haversine of the seed join); cluster total >= `VAN_MIN_BATCH_AMOUNT_BDT` -> `van`, one `van_route_id` (one trip) per cluster; (4) distributor hub within `SELF_FETCH_MAX_KM` and round trip (2 x km / `SELF_FETCH_SPEED_KMH`) <= time to deadline -> `self_fetch`; (5) else `urgent_manual` (call distributor). Every channel is scored as a ranked alternative (feasible, est. cost, ETA, reason): top-up fee `TOPUP_FEE_PCT` % of amount, ETA `TOPUP_ETA_H`; van `VAN_COST_PER_TRIP_BDT` / cluster size, ETA van lead time; self-fetch and swap hand-over `TRAVEL_COST_PER_KM_BDT` x km; urgent `URGENT_MANUAL_COST_BDT`. Chosen first, then feasible by cost, then infeasible. `rationale.alternatives` + `rationale.rule_trace` hold the explanation | `backend/app/rules/channel_rules.py`, `backend/app/services/rebalance.py`, `recommendations.channel`, `.van_route_id` |
| Channel assumptions | Defaults (synthetic, not upay figures; all `.env` overridable): van batch 100,000 BDT, van lead time 4 h, cluster radius 10 km, 1,500 BDT per van trip, top-up fee 0.5 %, top-up ETA 0.25 h, self-fetch max 10 km at 15 km/h, travel 10 BDT/km, urgent manual 2,500 BDT. Deadline already subtracts `REBALANCE_LEAD_TIME_H`, so van and self-fetch are checked against the time left to that deadline | `backend/app/core/config.py`, `.env.example` |
| Request flow (F4) | Agent requests own recommendation (idempotent: a requested / approved / fulfilled request is returned). Distributor approves or declines with a required note, then fulfils an approved one; agent may cancel while requested. requested -> approved -> fulfilled; requested -> declined / cancelled; anything else is 409. Recommendation status follows (requested / done / open again). A rebuild expires, never deletes, open recommendations with request history. Nothing moves money | `backend/app/services/recommendation_requests.py`, `recommendation_requests`, `audit_log` |
| Swap matching (F5) | Receivers: agents amber/red at 24 h with a cash top-up need (e-money shortages are topped up digitally, so they are not matched). Donors: other agents with surplus = balance - need - buffer. Feasible pair: same distributor, haversine <= `SWAP_RADIUS_KM`, amount = min(need, surplus) rounded down to 500 >= `SWAP_MIN_AMOUNT_BDT`. scipy `linear_sum_assignment` minimises total distance over feasible pairs (one swap per agent). `van_trip_saved` = swap covers the whole need; `score` = coverage x (1 - distance / radius). Precomputed at bootstrap after risk; a rebuild replaces only pending swaps and never re-matches agents in an approved swap | `backend/app/rules/swap_rules.py`, `backend/app/services/rebalance.py`, `swaps.py`, `swap_suggestions` |
| Agent risk (F9) | Window = the 7 days (168 h) before the window end; baseline = the agent's own 28 days before the window. Raw measures: **cash_out_growth** = log(window cash-out / own baseline rate); **hour_shift** = Jensen-Shannon distance (base 2) between the window's and the baseline's hour-of-day profile of cash-in + cash-out; **refills_per_day** = hours where cash + e-money jumps by > 10 BDT (every transaction conserves the total, so a jump is a refill) / 7; **out_in_log_ratio** = log(cash-out / cash-in). Model inputs = each measure as a robust z vs the peer group in the same window ((x − median) / (1.4826 × MAD), spread floored at 0.05), so market-wide shifts (Eid, salary days) cancel; growth, hour shift and refills are one-sided (below-peer clipped to 0). Peer group = tier × urban_rural; groups with < 10 agents use the global group (seed 42: tier 1 peri-urban/rural). One scikit-learn `IsolationForest` per group + one global (200 trees, seeded, `contamination` chosen on rolling validation folds before the holdout: 0.0025, see §ML upgrade), fitted on daily-stride windows ending on or before the holdout start (21,600 agent-windows); labels are never used for fitting. Flag = score > the group's threshold (score = −`score_samples`, 0..1) | `backend/ml/features/anomaly.py`, `backend/ml/training/anomaly.py`, `backend/ml/inference/anomaly.py`, `backend/ml/artifacts/anomaly_*` |
| Anomaly serving (F9) | Bootstrap verifies the committed artifact (sha256 + feature list; refits in seconds if missing), registers `model_versions` (`agent_anomaly`, metrics = evaluation below), scores every agent's 7 days before SIM_NOW and stores only flagged windows. `anomalies.features` = evidence: peer group + count, threshold, peer score p50/p90/max, per raw measure the value, peer p10/p25/p50/p75/p90, percentile and deviation (= model input), top ≤ 3 reasons (deviation ≥ 2, else the largest one), window totals (cash-out, cash-in, baseline cash-out, refills). A rescan replaces open flags and keeps reviewed ones | `backend/app/services/anomaly_scan.py`, `anomalies.py`; `GET /anomalies?status&page&page_size`, `GET /anomalies/{id}` |
| Anomaly review (F9) | Distributor (own agents) or admin sets `confirmed` / `dismissed` with a required note; once only (409 after). Writes `reviewed_by`, `reviewed_at`, `note` and an `audit_log` row (`anomaly.confirmed` / `anomaly.dismissed`, user id, note, score, window, model_version). Agents never see flags. Nothing else happens: a flag is a lead, not an accusation | `POST /anomalies/{id}/review`, `audit_log` |
| Impact (F11) | Counterfactual replay of the 14 held-out days (2026-04-21..05-04, never trained on), all agents, hour by hour. Ground truth = the seeded generator re-run in memory (same seed + agent count; checked against the stored balances at the holdout start, else skipped): full customer demand incl. what the logged history turned away, opening balances, each agent's own routine refills (identical in every scenario; not counted as trips). Each hour: routine refill -> deliveries that land -> policy orders -> customers served with the simulator's rules -> balances move. **Baseline** (fixed-threshold alert): every business hour (08-21), a float below `IMPACT_ALERT_SHARE` (20%) of capacity alerts once until its delivery lands; cash by a dedicated van (1 trip, ETA `REBALANCE_LEAD_TIME_H` 3 h), e-money by digital top-up (next hour); both refill to the agent's usual refill target. **AI**: at each planning round (`IMPACT_DECISION_HOURS` 08/14/20) LightGBM forecasts from the logged history before the round -> rebalance rule (F4, balance incl. deliveries on the way) -> swap matching (F5) -> channel rules (F4); an order is placed when the next round would leave less than the channel lead time (van 4 h for cash, top-up for e-money) to its deadline. Swap = donor cash for receiver e-money (capped by both); van route = 1 trip per cluster; urgent_manual = 1 trip (3 h); self-fetch and top-up = no van. Physical deliveries landing after 21:00 land at 08:00. Metrics per scenario x distributor x day: stockout hours = agent-hours with any customer turned away (> 0.5 BDT), value lost (turned-away BDT), van trips, actions by channel; value saved = baseline lost - AI lost; fee = `IMPACT_CASHOUT_FEE_PCT` x turned-away cash-out. Threshold sweep (10-50%) for an equal-service and an equal-van-budget reading (linear between thresholds) | `backend/app/rules/impact_rules.py`, `backend/app/services/{holdout_inputs,impact_sim,impact_policies,impact,impact_read,backtest}.py`, `impact_results`, `system_meta.impact_cache`, `GET /impact/summary?van_cost`, `GET /impact/comparison?from&to&van_cost` |
| Impact assumptions | Synthetic, not upay figures; all `.env` overridable: alert threshold 20% of capacity, cash-out fee 1.85% of the turned-away cash-out (cash-in assumed free), van 1,500 BDT per trip (`VAN_COST_PER_TRIP_BDT`), dedicated delivery 3 h, batched van 4 h, top-up within the hour, business hours 08-21, AI planning rounds 08 / 14 / 20. Channel assumptions above apply unchanged | `backend/app/core/config.py`, `.env.example` |

Fixed-mode benchmark (`CLOCK_MODE=fixed`). Impact backtest (model `lgbq-1.0.0-56571e7f`, seed 42, 300 agents, 14 held-out days; `GET /impact/summary`):

| Scenario | Stockout hours | Value turned away (BDT) | Cash-out fee lost (BDT) | Van trips | Van cost (BDT) | Deliveries by channel |
|---|---|---|---|---|---|---|
| No action (routine refills only, reference) | 4,484 | 28,010,860 | 431,162 | 0 | 0 | - |
| Baseline: alert at 20% of capacity | 322 | 2,813,340 | 44,579 | 786 | 1,179,000 | 786 dedicated van, 184 top-up |
| AI: forecast + recommendation + swaps | **76** | 761,050 | 12,083 | 1,065 | 1,597,500 | 2,320 on 317 batched van routes, 748 urgent, 549 self-fetch, 281 swaps, 1,656 top-up |
| AI - baseline | **-246 (-76.4%)** | **2,052,290 saved** | 32,496 saved | **+279 (none avoided)** | +418,500 | |

By distributor (stockout hours baseline -> AI, BDT saved, van trips baseline -> AI): DST-DHK 105 -> 16, 679,204, 203 -> 338; DST-CTG 91 -> 14, 600,798, 268 -> 387; DST-SYL 126 -> 46, 772,288, 315 -> 340.
Threshold sweep of the baseline (stockout hours / van trips): 10% 718 / 528, 20% 322 / 786, 30% 152 / 1,198, 40% 118 / 2,029, 50% 104 / 4,030. Equal van budget: at the AI's 1,065 trips the rule would have ~207 stockout hours (AI 76, i.e. 131 fewer). Equal service: no threshold up to 50% reaches the AI's 76 hours (50% still has 104 with 4,030 trips), so "van trips avoided at equal service" has no value (`null`). Sensitivity (not stored): with two planning rounds (08 / 20) the AI has 240 stockout hours with 786 trips, i.e. the same trips as the baseline and 25% fewer stockout hours.
Reading: the AI does not save van trips against the 20% rule; it moves the trade-off. It serves far more customers for a moderate rise in trips, and no fixed threshold matches its service at any trip count in the sweep. In fee terms alone the extra van cost (418,500 BDT) exceeds the cash-out fee recovered (32,496 BDT); the case rests on the 2.05 M BDT of transactions customers could complete and on the equal-budget comparison.
Limitations: the AI's forecasts use the logged history (status-quo stockouts), not the counterfactual one; the recommendation knows nothing about routine refills (it plans for "no refill") and orders the 24 h need, so it orders small amounts often; perfect delivery reliability; the AI's own action costs other than vans (top-up fee 0.5%, self-fetch / swap travel) are not netted out; one synthetic seed.

Anomaly evaluation (model `iforest-1.0.0-25b1a7f6`, seed 42, data_version 1.0.0) against the ~3% injected anomalous agents (`system_meta.synthetic_labels`; kinds night_structuring, volume_burst, circular_flow; SYNTHETIC_ASSUMPTIONS.md). Unit = agent-window (7 days, daily stride). A window is a true anomaly when ≥ 3 of its 7 days overlap an injected window; windows with a smaller non-zero overlap are ambiguous and excluded.

| Period | Windows (excluded) | True | Flagged | TP / FP / FN | Precision | Recall | Recall night / burst / circular | Agents: precision / recall |
|---|---|---|---|---|---|---|---|---|
| Holdout (last 14 days, never fitted) | 2,393 (7) | 30 | 23 | 22 / 1 / 8 | 0.96 | 0.73 | 0.92 / 0.40 / 0.88 | 0.80 / 0.80 (4 of 5) |
| Training period (fitted, labels unused) | 21,587 (13) | 27 | 104 | 24 / 80 / 3 | 0.23 | 0.89 | 0.82 / 0.86 / 1.00 | 0.09 / 1.00 |

At SIM_NOW the scan flags 5 of 300 agents, exactly the 5 with an injected anomaly overlapping the last 7 days (incl. the demo agent AGT-0005, night structuring). Contamination was chosen as the smallest value with training-period recall ≥ 0.85 (recall matters more than precision for a review queue). Sweep, training period, precision / recall (flagged windows): 0.002 0.46 / 0.70 (41), 0.003 0.34 / 0.78 (62), **0.005 0.23 / 0.89 (104)**, 0.0075 0.17 / 0.96 (153), 0.01 0.13 / 0.96 (205), 0.02 0.06 / 0.96 (422), 0.03 0.04 / 1.00 (641). The holdout was also scored for 0.01-0.03 while building (0.77 / 0.90, 0.57 / 1.00, 0.38 / 1.00), so the holdout figure above is not a fully blind estimate. An earlier version that fed hour shift, refills and the ratio as raw values (not vs peers) had holdout precision 0.59 at 0.03 and was dropped.
Limitations: volume bursts are the hardest kind (holdout recall 0.40), likely because served volume is capped by the float, so a burst partly shows as stock-outs instead of volume. Most training-period flags are agents without an injected anomaly; their cause is not labelled, so the training-period precision is a lower bound on how often a flag is worth a look. Only three synthetic patterns are tested; real fraud looks different. An agent with < 35 days of data would be scored against a partly empty baseline (every synthetic agent has the full 120 days).

| Who | Sees | Can do | Logged in |
|---|---|---|---|
| Agent | Own risk, countdown, recommendation, swap status | Request distributor action, cancel while requested (no money moves) | `recommendation_requests`, `recommendations.status`, `audit_log` |
| Distributor | Own agents' risk map, swap queue, requests, anomalies | Approve / reject swap with note; approve / decline request with note, mark fulfilled; review anomaly confirmed / dismissed with note | `audit_log` (user id + note), `swaps.decided_by`, `recommendation_requests.decided_by`, `anomalies.reviewed_by` |
| Admin | All | Users, models, LLM logs, audit | `audit_log` |

### Liquidity help requests (automatic trigger)

Advisory coordination only: the system asks nearby helpers, a human confirms the money arrived;
nothing moves money. Rules: `backend/app/rules/help_trigger_rules.py`, `help_request_rules.py`;
services `help_trigger.py`, `help_trigger_run.py`, `help_waves.py`, `liquidity_requests.py`.

- **Trigger**: per agent and float, the cautious path (drain q90, inflow q10) over
  `HELP_TRIGGER_HORIZON_H` drops below the agent's buffer, the headline risk is red, and the gap
  is at least `HELP_TRIGGER_MIN_SHORTFALL_BDT`. Each float fires on its own; one active request
  per agent and float (dedupe), cooldown and daily cap across both floats.
- **Amount** = shortfall to zero + buffer, rounded up to 500, capped at
  `HELP_TRIGGER_MAX_REQUEST_BDT`.
- **Buffer** = `HELP_TRIGGER_BUFFER_PCT` of the agent's **expected 24 h drain from the forecast**
  (sum of the hourly q50 drain for the next 24 h), not a historical average. A helper keeps its own
  need plus its own buffer before anything counts as surplus.
- **Time base**: the forecast is a snapshot made at the data clock's origin (`system_meta.sim_now`:
  SIM_NOW on the fixed clock, the current hour on the live clock); its hours count from that origin. Every workflow time (created, needed_by, claim expiry, wave
  timers, notifications, the UI countdown) is real wall-clock UTC (`backend/app/core/clock.py`),
  and the one conversion `forecast_to_wall()` places a forecast moment at "now + the same offset".
  So a request made when the agent page says "stock-out in 3 h 40 m" stores `stockout_at` =
  now + 3 h 40 m, and `needed_by` = (earlier of the cautious crossing and that median stock-out)
  - `HELP_TRIGGER_LEAD_MARGIN_H`, never sooner than `HELP_TRIGGER_DEADLINE_FLOOR_MIN` (15 min).
  The agent page shows the snapshot ("as of" the origin); the request counts down in real time. On
  the live clock the origin is at most one tick behind now and that lag is subtracted
  (`clock.lag_h`), so the request's stock-out time is the forecast's real time.
- **Urgent**: forecast stock-out sooner than twice the deadline floor; wave 1 then asks
  `HELP_TRIGGER_URGENT_WAVE_MULTIPLIER` times as many agents.
- **As soon as possible**: when the floor pushes `needed_by` past the forecast stock-out
  (stock-out sooner than the floor), the request is flagged (`deadline_after_stockout` in the
  database, `deadline_asap` in the API, helpers included) and the UI and notifications say "as
  soon as possible" instead of a time after the stock-out.
- **Late delivery**: if a helper's claim timed out but the money still arrived, the requester or
  their distributor confirms it late (`confirm_late`); allowed while the request is open again,
  or up to `HELP_LATE_CONFIRM_GRACE_H` (24 h) after it expired, never once cancelled.
- **New shortages appear only when the data changes**: the forecast is tied to the synthetic
  clock, so with the shipped data the set of short agents is fixed after bootstrap (regenerating
  data or retraining changes it). In a demo, the admin **simulate shortage** button
  (`DEMO_MODE` only, audited, results marked simulated) is the path to a fresh request.
- **Waves**: the requester's distributor is always asked; agents (same distributor, within
  `HELP_TRIGGER_RADIUS_KM`, surplus covers the whole amount, not opted out, not asked in the last
  `HELP_TRIGGER_RECENT_ASK_H`) are ranked by distance, recent asks and past acceptance. After
  `HELP_TRIGGER_WAVE_TIMEOUT_MIN` unanswered, the next agents are asked; after
  `HELP_TRIGGER_MAX_WAVES` the request expires and the distributor and admins are escalated.
- **Who sees the reason**: stored as a code plus parameters and rendered in the reader's language
  for the requester, their distributor and admins; helpers see only a coarse category
  (salary_day, eid, holiday, market_day, weather, high_demand, unknown), never numbers or balances.
- **Scheduler**: one tick every `HELP_TRIGGER_INTERVAL_S` (claim-timeout sweep, wave advance,
  trigger), only after bootstrap is ready and only in the process holding the leader lock
  (Postgres advisory lock; file lock on SQLite). Status on `GET /admin/overview`.
- **Pacing**: a tick opens at most `HELP_TRIGGER_MAX_NEW_PER_TICK` (3) new requests, earliest
  stock-out first (then larger amount, then agent id); the others are reported `tick_cap` and are
  re-evaluated on the next ticks, where dedupe, cooldown and the daily cap still apply. A fresh
  start of the shipped data finds about 20 short agents, so they arrive over several minutes
  instead of all at once. In `DEMO_MODE`, after a fresh bootstrap only (the database was just
  seeded; a plain restart does not wait), the first tick waits
  `HELP_SCHEDULER_DEMO_START_DELAY_S` (120 s) after bootstrap is ready.
- **DEMO_MODE only** (`DEMO_MODE=false` keeps exactly the rules above): demo defaults for the
  wave story (`HELP_DEMO_DEFAULTS`: 1 helper agent per wave, 2-minute waves, 3 waves, largest
  request 100 000, recent-ask window 0; an admin's saved value wins); at most
  `HELP_DEMO_AUTO_PER_DAY` (1) automatic request per agent and float per rolling 24 h; the
  admin's simulate shortage skips the cooldown, daily cap and recent-ask window (the scheduler
  does not); **reset demo state** cancels the demo agents' active requests and restarts their
  limits and the helper rotation from that moment.
- **Leader guard**: the scheduler acts only in the process holding the leader lock (above), so
  several workers or instances never tick twice; each tick is idempotent as a second guard.
- **Rate limiting**: login, demo login, sign-up and password-reset limits use an in-process
  sliding-window limiter (`app/core/rate_limit.py`); lockouts and LLM daily caps live in the
  database. With several instances the in-process counters are per instance (see
  docs/PATH_TO_PRODUCTION.md for moving them to a shared store).
- **Access tokens after a password reset**: a reset revokes every refresh token at once, but an
  access token already issued stays valid until it expires (at most `JWT_ACCESS_TTL_MIN`,
  15 minutes).

## 4. LLM usage (language only; matches docs/LLM_SPEC.md)

| Feature | Intent (`llm_call_log.intent`) | Deterministic part | LLM-generated part | Endpoint |
|---|---|---|---|---|
| Agent Copilot (chat + voice) + Playbook RAG | copilot | Evidence pack, allow-listed tools (`get_whatif`, `get_swap_status`, `get_forecast_window`), TF-IDF top-3 retrieval | Answer wording, cites doc title | `POST /copilot/chat` |
| "Why?" wording (F7) | narrate | SHAP factors + template sentence | Natural bn/en rewrite | `POST /explanations/narrate` |
| Agent morning summary | agent_briefing | Evidence pack | Summary text | `GET /agents/{id}/briefing` |
| Distributor daily briefing | distributor_briefing | Evidence pack (own agents only) | Briefing text | `GET /distributor/briefing` |
| Anomaly investigation | anomaly_narrative | Isolation Forest score + features | Narrative | `GET /anomalies/{id}/narrative` |

| Mechanism | Method | Implemented in |
|---|---|---|
| Grounding | LLM sees only the role-scoped evidence pack + user question + retrieved passages | `backend/app/services/` (evidence pack), `backend/app/llm/rag/` |
| Providers | `LLM_PROVIDER=auto\|anthropic\|openai_compatible\|replay\|template`; auto: key -> live, no key -> replay, replay miss -> template | `backend/app/llm/providers/` |
| Guards | Injection filter (delimiters, 500 chars, out-of-scope refusal); numbers guard (every number/time must exist in pack); Pydantic output schema `{text, lang, cited_factors[]}`; max_tokens copilot 350 / narrate 150 / briefing 400 | `backend/app/llm/guards/` |
| Fallback | Timeout 8 s, 1 retry, then fall back; any guard failure -> template. UI shows template first, swaps in LLM text when ready | `backend/app/llm/` |
| Cache | Key = sha256(evidence pack + intent + lang); stored with expiry; replay answers in a pre-recorded file | `llm_cache`, `backend/app/llm/cache/demo_replay.json` |
| Logging | One row per call: user, intent, provider, model, lang, evidence_hash, tokens, latency_ms, generated_by, guard_result, error | `llm_call_log`, `GET /admin/llm/logs` |
| Labelling | Every response has `generated_by: llm\|template\|replay`; UI chip "AI-generated wording" kept apart from "Model prediction" | `backend/app/schemas/`, WhyStones |
| Never | Decide risk, approve swaps, set amounts, compute numbers, see other agents' data | enforced by guards + role scoping in `backend/app/core/` deps |

## 5. Reproducibility

| Item | Method | Implemented in |
|---|---|---|
| Seeds | Fixed seed for data generation and model training; recorded in `system_meta.seed` | `backend/ml/data_gen/`, `backend/ml/training/` |
| Artifacts | Trained `*.joblib` + `manifest.json` (model_version, sha256) committed to git; fresh PC needs no training | `backend/ml/artifacts/` |
| Startup check | Verify manifest sha256 + feature list, register in `model_versions` (artifact_sha256, metrics, is_active), then precompute the forecast cache (skipped when model, origin and data are unchanged) | `backend/bootstrap.py` (`needs-train`, `precompute`) |
| Retrain | Only if artifacts missing / hash mismatch: retrain from seed (slow path, logged); fail if still missing | `backend/bootstrap.py` step 6 |
| Demo state | Fixed clock: precompute at `SIM_NOW`, identical on every PC. Live clock: the demo story is anchored at the current hour (deterministic given seed + anchor); replay answers keyed by evidence-pack hash | `backend/bootstrap.py`, `ml/data_gen/live_plan.py`, `demo_replay.json` |
| Readiness | `GET /api/v1/system/status` reports db, migration head, seed/data_version, artifacts ok, model_version, llm mode, `ready` | `backend/app/api/v1/` (system) |

Verify on a fresh PC:
1. `run.bat --reset` (or `run.sh --reset`), wait for `ready: true`.
2. Compare `/system/status` seed, data_version, model_version with the values in `backend/ml/artifacts/manifest.json`.
3. `/admin/models`: holdout metrics equal those in the manifest / committed `model_runs` metrics.
4. With no LLM key: `/llm/status` shows replay; `/admin/llm/logs` shows `generated_by=replay` for the demo scenario.

## 6. Limitations and responsible AI (F12)

Shown on `/responsible-ai`: `GET /api/v1/responsible-ai/model-card?lang` (active models + held-out metrics, data, intended use, out of scope, limitations, human oversight, `advisory_only: true`, fairness gaps) and `GET /api/v1/responsible-ai/fairness?groupBy=urban_rural|tier|region`. Both readable by every role (group aggregates only). Wording lives in `backend/app/services/model_card_text.py` (bn/en); every number comes from `model_versions` and the backtest caches.

| Limitation / safeguard | Note |
|---|---|
| Synthetic data only | Patterns are assumptions (SYNTHETIC_ASSUMPTIONS.md), not measured upay behaviour; metrics show method soundness, not real-world accuracy |
| Advisory only | No endpoint moves money; swaps and anomaly outcomes need a distributor decision with note in `audit_log` |
| Uncertainty | Forecasts are a q10–q90 band; stockout time always shown with confidence |
| Fairness | Same holdout and planning rounds as the impact backtest (08/14/20, rounds with a full 24 h ahead: 2026-04-21..05-03, 39 rounds), per agent group (urban_rural, tier, region): forecast MAE of q50 vs logged served demand over hours 1-24, its baseline (same hour last week), nMAE = MAE / mean demand (comparable across busy and quiet groups) and skill = 1 - MAE / baseline MAE; stockout recall = share of real stockouts (agent x float x round with a customer turned away in the logged history within 24 h) that the 24 h risk level flagged amber/red (P >= 0.20; Monte Carlo as in §2 with 500 paths), precision alongside. Gap = largest - smallest group value. Stored in `system_meta.fairness_cache` by `backend/app/services/fairness.py` |
| Anomaly ≠ fraud | Isolation Forest flags are leads for human review, not accusations |
| LLM wording | May be imperfect; numbers guard + template fallback; always labelled |
| Privacy | Role-scoped evidence; no cross-agent data in prompts; LLM key only in backend env |
| Footer notices | "Advisory only — a human approves" and "Synthetic data only" on relevant pages |

Fixed-mode benchmark (`CLOCK_MODE=fixed`). Fairness results (model `lgbq-1.0.0-56571e7f`, seed 42, 300 agents; `GET /responsible-ai/fairness`). nMAE and skill as cash_out / cash_in:

| Group | Agents | nMAE | Skill vs last week | Stockout recall | Precision |
|---|---|---|---|---|---|
| All | 300 | 0.43 / 0.47 | 0.28 / 0.27 | 0.984 (1,466 / 1,490) | 0.24 |
| urban | 104 | 0.40 / 0.42 | 0.29 / 0.26 | 0.988 | 0.16 |
| peri_urban | 89 | 0.45 / 0.53 | 0.28 / 0.28 | 0.974 | 0.21 |
| rural | 107 | 0.50 / 0.68 | 0.26 / 0.27 | 0.987 | 0.38 |
| tier 1 | 45 | 0.35 / 0.38 | 0.31 / 0.26 | 0.984 | 0.28 |
| tier 2 | 116 | 0.42 / 0.46 | 0.28 / 0.28 | 0.992 | 0.24 |
| tier 3 | 139 | 0.64 / 0.75 | 0.26 / 0.27 | 0.978 | 0.24 |
| Dhaka | 110 | 0.39 / 0.42 | 0.29 / 0.27 | 0.986 | 0.17 |
| Chattogram | 100 | 0.45 / 0.50 | 0.28 / 0.26 | 0.980 | 0.22 |
| Sylhet | 90 | 0.50 / 0.65 | 0.26 / 0.28 | 0.986 | 0.38 |

Gaps (largest - smallest): recall 1.3 pts by area, 1.4 by tier, 0.7 by region; nMAE 0.10 / 0.26 by area, 0.29 / 0.37 by tier, 0.10 / 0.23 by region.
Reading: stockout recall, the safety-relevant metric, is even across groups (97-99%). Relative forecast error is higher for small (tier 3) and rural agents because their hourly demand is small and Poisson-noisy, but the gain over the baseline (skill) is the same for every group, so no group is served by a weaker model. Precision is lowest for urban agents (0.16): they get more false alarms (a burden on them, not a missed stockout), partly because the "no refill" projection ignores their frequent routine refills. Synthetic groups only; real-data fairness needs re-checking.

## 7. Live clock vs fixed clock

| Item | Fixed clock (`CLOCK_MODE=fixed`) | Live clock (`CLOCK_MODE=live`, default) |
|---|---|---|
| Now | SIM_NOW = 2026-04-30 20:00 Dhaka, frozen | the real time in Asia/Dhaka (server clock, one for all roles) |
| Data window | 2026-01-05 .. 2026-05-04, generated once, includes 4 days after SIM_NOW as ground truth | 120 days before today .. the current hour; nothing after the current hour |
| Generator | `ml/data_gen/dataset.py` (window-sequential randomness) | `ml/data_gen/live.py`: same world, randomness seeded by (seed, purpose, date), so a date always gives the same values |
| Calendar | fixed constants (Eid 2026-03-21 assumed, 3 holidays) | salary 1st-3rd, wage days 7th-9th, weekly hat days, Eid/holidays from `backend/data/holidays_bd.yaml` (Islamic dates `unverified`), weather for all 12 months |
| Updates | none after bootstrap | hourly tick: new hour of data, then forecast, stock-out + risk, rebalance + swaps, anomaly flags; impact backtest once a day |
| After downtime | n/a | catch-up of the missing hours on start (24 h batches, one transaction each); > 14 days: rebuild the window |
| Holdout | last 14 days of the window | the 14 days before today (the model never trained on any live data) |
| Drift report | forecast at SIM_NOW vs the stored 72 h after it | backcast: the model at now - 72 h vs the demand logged since |
| Demo story | AGT-0001 runs dry 2026-05-01 15:40 (salary day) | AGT-0001 runs dry 15:40 today or tomorrow; a labelled demo wage event when no real calendar day explains it; re-anchored in DEMO_MODE when no story lies ahead |
| Use | tests, benchmarks (numbers in this document), reproducible evaluation | run.bat / run.sh, judges, demos |

The committed model artifacts serve both clocks. The forecast features are hour, weekday, day of
month, calendar/event flags, weather, agent attributes and lags divided by the agent's own
trailing 7-day mean; there is no absolute date, day index or trend feature, so the model does
not need retraining when the window moves. Caveat: training saw January-May weather only.
Retraining reads the fixed timeline and therefore runs only with `CLOCK_MODE=fixed`.

Tick budget: 60 s for 300 agents. Measured numbers are in docs/UPGRADE_PROGRESS.md.

## Open questions

1. Seed value, number of distributors/agents, districts covered, length of generated history.
2. Exact value of SIM_NOW and whether it falls inside the 14-day holdout.
3. Decided (§2): cash_out and cash_in modelled separately; direct multi-horizon with horizon as a feature.
4. Decided (§2): stockout probability, time and confidence from a Monte Carlo over the quantile paths.
5. Decided (§3): probability cut-offs per horizon in `backend/app/rules/risk_rules.py`.
6. Decided (§3, Rebalance, Delivery channel): shortfall at q90 + buffer, capped at capacity; channel by the five ordered rules, `van` only for clustered cash batches >= `VAN_MIN_BATCH_AMOUNT_BDT` with enough lead time (defaults under Channel assumptions).
7. Decided (§3, Swap matching): `linear_sum_assignment` on distance, radius 5 km, minimum 5,000 BDT (configurable).
8. Decided (§3, Agent risk): 7-day window vs own 28-day baseline, four peer-relative features, contamination 0.005; ~3% of agents carry injected, labelled anomalies, evaluated above.
9. Decided (§3, Impact): alert at 20% of capacity (swept 10-50% for equal-service / equal-budget readings); targets in docs/IDEA_CHAIN.md step 6.
10. Decided (§6, Fairness): groups urban_rural, tier, region; metrics nMAE + skill (forecast) and stockout recall + precision (24 h risk flag), with the largest group gap.
11. Drift metric shown on `/admin/models`.
12. Partly decided: training uses `deterministic=true`, `force_row_wise=true`, 4 threads and a fixed seed, but bit-identity across CPUs is not guaranteed. The committed artifacts are therefore canonical; bootstrap retrains only if they are missing or fail the sha256 / feature-list check, and a retrain gets a new `model_version`.
13. `llm_cache` TTL; whether a live-provider failure falls back to replay before template.
14. Whether the evidence pack excludes volatile fields (e.g. `generated_at`) so replay hashes match on every PC.

## ML upgrade (2026-10-05)

All results on synthetic data only; numbers in docs/ML_UPGRADE_RESULTS.md, choices in
docs/DECISIONS.md (ML1-ML9). Benchmark: `backend/scripts/ml_benchmark.py` (fixed clock).

| Item | Method | Implemented in |
|---|---|---|
| Split | Train targets < 2026-04-07; validation 04-07..04-20; blind test 04-21..05-04, scored once after every choice. Leakage tests: no target after a boundary, features at origin t0 unchanged when demand >= t0 is altered, anomaly folds never read holdout labels | `backend/ml/training/splits.py`, `tests/test_ml_split.py` |
| Forecast selection | q10 / q90 per target: leaves {31, 63} x rounds {150, 300, 450, 600} by validation pinball, served booster = that candidate (trained on train only). q50 (explained by TreeSHAP each tick) is capped at 31 x 300; inside the cap the old 1.0.0 q50 had the lower blind MAE, so it is served unchanged (DECISIONS ML2) | `backend/ml/training/train.py` |
| Conformal band | Split-conformal CQR, one offset per tail (TAIL 0.10, finite-sample rank ceil((n+1)(1-TAIL))), scores in units of the agent scale, Mondrian cells closed hour (raw q90 < 1 BDT) x tier x area x horizon bucket (1-6, 7-24, 25-72 h), pooled fallback below 200 rows; then clip at 0 and keep q10 <= q50 <= q90 (both only widen). `FORECAST_CONFORMAL` | `backend/ml/inference/conformal.py`, artifact `forecast_conformal.json` |
| Joint stockout (alternative decision input) | Cash-out and cash-in drawn together: Gaussian copula with path factor share rho_out / rho_in and cross correlations of the path factors and hourly shocks, estimated per segment (tier x area) on validation residuals (PIT through the served quantile function, randomised at zero mass; one-way ANOVA intraclass correlation; hours with q50 < 1 BDT skipped). Both floats served hour by hour with the generator's rule (a dry float stops feeding the other); stockout = first hour turning customers away (> 0.5 BDT). `STOCKOUT_METHOD=joint` | `backend/ml/inference/stockout_joint.py`, `backend/ml/training/dependence.py`, artifact `stockout_dependence.json` |
| Refill-aware view | Same joint paths plus the agent's own refill habit from the last 42 days before the origin: refill = cash snapshot not explained by the previous one and that hour's transactions; P(refill) per weekday x hour slot; level = median after-refill balance per float; a refill raises a float to its level. Stored as `refill_hours_to_stockout`, `refill_prob_24h`; API `refill_aware` (extra reading only) | `backend/ml/inference/refill.py`, `backend/app/services/risk.py`, migration 0023 |
| Stockout validation | Blind test, 39 rounds x 300 agents x 2 floats, 24 h: Brier, AUC, reliability bins, recall / precision at the amber cut, time-to-stockout error vs the first realised turned-away hour | `backend/ml/evaluation/stockout_eval.py` |
| Helper acceptance (simulated) | Generator of help requests and helper answers (hidden logistic law: distance, hour band, asks in 7 days, surplus ratio, tier, personal propensity; common random numbers); logistic regression on train asks + Platt on validation asks; policy simulation on blind-test requests. Opt-in ordering / wave size inside the rule-feasible set (`HELP_RANK_MODEL`, `HELP_WAVE_SIZING`, `HELP_WAVE_TARGET`); wave size rule `learned_wave_size` never exceeds the rule cap | `backend/ml/data_gen/helpers.py`, `backend/ml/training/helper_accept.py`, `backend/ml/inference/helper_accept.py`, `backend/app/rules/help_trigger_rules.py` |
| Split matching (S1) | MILP (scipy HiGHS, 10 s limit): integer 500-BDT units per feasible pair, binary hand-over flags, minimum swap per hand-over, donor surplus and receiver need limits, per-donor (2) and per-receiver (3) caps, travel time km / 15 km/h within the receiver's deadline; maximise covered BDT minus 200 BDT per hand-over and 10 BDT per km. `SWAP_MATCHING=flow` | `backend/app/rules/swap_rules.py` (`match_flow`) |
| Forecast baselines (S2) | Same hour last week; mean of the same hour over 4 weeks; exponential smoothing (alpha 0.3) over the same hour of 8 weeks | `backend/scripts/ml_benchmark.py` |
| Second anomaly detector (S3) | Minimum Covariance Determinant per peer group, robust Mahalanobis distance; precision at k on blind windows. Comparison only | `backend/ml/training/anomaly_compare.py` |
| Impact realism (S4) | Physical deliveries fail (10%, arrive empty) or land 2 h late (25%); digital top-ups unchanged; full action costs (van trip, urgent 2,500 BDT, top-up fee 0.5%, travel 10 BDT/km). Benchmark sensitivity, not the stored backtest | `backend/app/services/impact_realism.py` |
| Drift (S5) | Drift report adds q10-q90 coverage of the compared hours vs the model's held-out coverage (watch >= 0.10 gap, drift >= 0.20) and an advisory `retrain` suggestion with reasons; nothing retrains by itself | `backend/app/services/drift.py` |

## Van route optimizer (F14, V1 core, 2026-10-06)
- Inputs: open/requested cash recommendations of the distributor's agents (rebalance amount,
  pessimistic q90; stockout time from the recommendation), forecast cash-out per hour (q50) as
  lost value per stockout hour, day travel-time factors (events, weather), the hub as depot.
  Agents covered by a pending/approved swap are listed as `swap_suggested`, not routed.
- Objective (BDT): van fixed cost + km cost + time cost + lateness penalty (lost value x hours
  after the expected stockout) + skip penalty (lost value until the horizon). Pure rules in
  `app/rules/van_routing/`; OR-Tools with soft deadlines and optional stops, fixed solution budget
  (deterministic), fallback nearest-neighbour + 2-opt. Every number is recomputed by `cost.py`.
- Distances: committed road cache (OSRM, built offline) or haversine x road factor, labelled per
  leg; the plan is `road_cache` only when every leg is cached.
- Solved on demand (`POST /api/v1/distributor/van-plans`), never in the hourly tick; a human
  approves or rejects with a note (audit_log). Assumptions: docs/SYNTHETIC_ASSUMPTIONS.md section 9.
  Decisions: docs/DECISIONS.md V1-V8. Evaluation (policies A-D, held-out days, synthetic data):
  `ml/van/backtest.py`, results in `backend/ml/van/van_v1_eval.json`.

### Should stage (V3, 2026-10-06)
- Forecast-aware inputs: red agents get the q90 rebalance amount, amber agents the median-path
  (q50) amount; deadline = first hour the agent's P(stockout) curve reaches 0.3, else the
  recommendation's stockout time (`deadline_rule` per stop).
- Robustness: ETA range = driving time x 0.85 / x 1.3 + stop minutes; P(stockout before the late
  ETA) from the same curve, stops above 0.3 flagged (`stockout_risk_flag`, plan `flagged`).
- Fairness guard per area (urban / peri_urban / rural): hard max wait 8 h; min service rate 0.5
  enforced by inserting the cheapest dropped stop of a short group; per-group report with the plan.
- Safety: per-van cash cap (load limit); seeded pick among route variants (reversal, neighbour
  swap) within 3% of the best cost (`choice` "k/n"; seed from the input hash).
- Stability: lock / include / exclude per stop re-solve as a new pending plan (audit_log); open
  stops of the approved plan reached within 30 min are frozen to their van; re-plan only on a new
  input hash.
- Narrative: LLM intent `van_narrative` through the guarded service (numbers guard,
  `llm_call_log`, template fallback).
- Code: `app/rules/van_routing/{fairness,safety,stability,robust}.py`, `solver.plan`,
  `services/van_plan_store.py`, `POST .../van-plans/{id}/stops/{stop_id}/{lock|include|exclude}`.
  Decisions V16-V23.

### Van evaluation V3 (synthetic data, oracle needs: routing quality only)
`python -m ml.van.evaluate` -> `backend/ml/van/van_v3_eval.json`, `GET /api/v1/impact/van-comparison`.
Seeds 42-46, 39 held-out instances each (08:00, per distributor), 618-752 stops per seed, estimate
distances; mean over seeds [95% t-interval]. Default config: 2 vans, BDT 1.5 M cap, 8 h shift.

| Policy | Total BDT | Van BDT | Trips | Stockout h | Service rate | Deadline hit | Solve ms mean / max |
|---|---|---|---|---|---|---|---|
| A separate trips (no fleet limit) | 3.07 M [2.80, 3.35] | 2.40 M | 695 | 137 | 1.000 | 0.803 | 0.2 / 0.7 |
| B nearest-neighbour | 13.32 M [10.17, 16.48] | 0.39 M | 65 | 2,303 | 0.855 | 0.602 | 3 / 52 |
| C OR-Tools, hard deadlines | 23.40 M [21.01, 25.79] | 0.35 M | 63 | 4,260 | 0.719 | 0.719 | 206 / 1,358 |
| D full model | 9.43 M [7.63, 11.22] | 0.39 M | 68 | 2,052 | 0.857 | 0.622 | 420 / 2,327 |

- D vs C: D is lower on all 5 seeds, mean -13.97 M BDT [-15.69, -12.25] per seed (verdict
  `lower`). C's hard deadlines drop 107 stops per seed as `deadline_missed`, each then counted as
  stocked out until the horizon; D serves them late at a lower lost value.
- D vs A: D is higher on all 5 seeds, +6.35 M BDT [4.76, 7.94] (verdict `higher`). A has no fleet
  limit (about 695 vans at once) and no cash limit across vans; D has 2 vans and drops about 99
  stops per seed for `capacity` (cash load or shift time). D's van cost is 6x lower (0.39 M vs
  2.40 M BDT). Not claimed as a saving: with 2 vans the lost value of unserved agents dominates.
  The V1 gate test (`test_van_eval`: D <= A on seed 42) therefore still fails, unchanged.
- Service rate by area, D: urban 0.954, peri-urban 0.894, rural 0.797 (C: 0.819 / 0.769 / 0.651).
- Road-cache reference, seed 42 (39 instances, 677 stops), total BDT: A 2.62 M, B 10.90 M,
  C 20.45 M, D 6.46 M (V1: 6.457 M; V3 adds the fairness guard and the near-optimal pick).
- Sensitivity, seed 42, estimate distances, total BDT (A / C / D): road factor 1.2: 2.66 M /
  20.85 M / 5.91 M; 1.5: 3.10 M / 22.83 M / 7.83 M; fuel 20 BDT/km: 2.69 M / 21.64 M / 7.09 M;
  30 BDT/km: 3.07 M / 21.71 M / 7.36 M; delivery reliability 0.95: 6.14 M / 23.98 M / 9.77 M;
  0.90: 9.20 M / 26.01 M / 12.59 M. The order A < D < C holds in every case.
- Limits: oracle needs (no forecast error), one decision hour, day factors off, synthetic data.
