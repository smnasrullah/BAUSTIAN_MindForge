# Live Clock Upgrade — Progress

Baseline (start): `git status --short` = (clean), `git diff --stat` = (empty). Branch hardening-pass @ 8ef91ce.

| Phase | State | Result | Duration |
|---|---|---|---|
| 1 Investigate | done | Leaks listed below; model artifacts reusable (no absolute-date/trend features) | ~25 min |
| 2 Clock service | done | app/core/clock.py live/fixed, CLOCK_SHIFT_H, freshness.clock, admin /admin/clock | ~40 min |
| 3 Data aligned to now | done (stack check in 6) | live engine + catch-up + hourly tick; sqlite: regen 19 s, tick 39-59 s before SHAP threads | ~2 h |
| 4 Demo story relative | done (stack check in 6) | story at anchor, 15:40 stock-out, labelled demo event, re-anchor in DEMO_MODE | in 3 |
| 5 UI and docs | done | chip, admin Data clock card, landing date; README/METHODS/ARCHITECTURE/DEMO_SCRIPT/DECISIONS/ASSUMPTIONS/COMMANDS | ~50 min |
| 6 Tests and verification | done | fast tier PASS, -Slow PASS, -E2E 1 new-spec fail -> fixed, spec re-run PASS; fixed mode bit-identical to HEAD | ~1.5 h |

## Phase 6 measurements (verify stack, Postgres, 300 agents)
- Fresh live start (`check.ps1 -Up`, clock shifted -72 h): ready 242 s after up (images built 45 s; regenerate 74 s; precompute 111 s = forecast 14.8, risk 12.1, rebalance 0.5, anomalies 5.9, backtest 74.3).
- Restart with real clock (72 h gap): catch-up 72 h in 1.9 s (3 x 24 h), story re-anchored, ready 120 s.
- Hourly tick (natural, 18:00 Dhaka): 25.1 s = data 0.2, forecast 10.7, risk 9.3, rebalance 0.5, anomalies 4.3 (budget 60 s). The daily backtest adds ~65-75 s to the first tick after midnight (over budget then).
- Fixed-mode fingerprint HEAD vs working tree (sqlite, seed 42): data, forecasts, explanations, risk, recs, swaps, anomalies, impact, fairness, model metrics all identical.

## Phase 1 — where the fixed clock leaks (file:line)
- Fixed timeline constants: backend/ml/data_gen/timeline.py:9-16 (START 2026-01-05, N_DAYS 120, HOLDOUT_START, SIM_NOW 2026-04-30 20:00)
- system_meta sim_now written/read: ml/data_gen/load.py:116-118; app/services/forecast.py:35-37 (fallback to SIM_NOW)
- Demo story pinned to dates: ml/data_gen/demo_spec.py:13-20; demo_scenario.py:51,99,112; anomalies.py:75-77
- Generator calendar fixed to Jan-May 2026: calendar_effects.py:28 (EID_DAY), :41-45 (HOLIDAYS); weather.py:14-15 (months 1-5 only); demand.py:73 (trend from START)
- Generator randomness is window-sequential, not per date: demand.py:89-95,98-103; simulate.py:116; weather.py:32-45
- Panel/features hour index tied to START/N_HOURS: ml/features/panel.py:18,51-56,65-77,112-133; ml/features/anomaly.py:19,56-75,128
- Precompute at sim_now (cache keys include it): forecast.py:49-86; risk.py:65-69; rebalance.py:211; anomaly_scan.py:36-50; recommendation_read.py:30; whatif.py:85; llm/copilot/chat.py:41
- Holdout backtest re-runs the fixed generator: app/services/holdout_inputs.py:24,43-46,52,70,81-118; backtest.py:32-48 (key has no time -> never refreshes)
- Drift compares forecast vs data AFTER sim_now (needs future rows): app/services/drift.py:80-87
- Freshness/admin data period = fixed constants: app/services/freshness.py:14,25-26; admin_data.py:23,71
- Help trigger reads balances at sim_now: help_trigger.py:130; wall clock bridge app/core/clock.py:1-39 (already real UTC)
- Scheduler: only help scheduler exists (help_scheduler.py); no data tick; bootstrap precompute only (bootstrap.py:103-115, scripts/bootstrap.sh)
- Training (fixed window only, fine): ml/training/train.py:26,103-113; ml/training/anomaly.py:26,135-142
- Frontend: FreshnessChip.tsx (no mode shown); AdminDataPage.tsx:50 "Simulated now"; VersionInfo.tsx:50-53; landing/demoDay.ts:58 (fixed 2026-10-01, clock only); formatters already Asia/Dhaka (lib/format.ts)
- i18n: en/bn.json admin.data.simNow; no hard-coded calendar dates in UI strings
- Tests pinned to fixed clock (keep, run in fixed mode): test_freshness_api.py, test_forecast.py, test_data_gen_*.py, test_risk_api.py, rebalance_helpers.py, test_help_clock.py:48, frontend testFixtures (mock data only)
- Docs: METHODS.md:18,33,63,121-128,204-206; SYNTHETIC_ASSUMPTIONS.md:15,90-92; DEMO_SCRIPT.md:3; ARCHITECTURE.md:41,209,264; WALKTHROUGH_BN*.md
- Tooling: scripts/check.ps1 -Up/-E2E target the MAIN compose project (must run with COMPOSE_PROJECT_NAME=agentpulse-verify)

## Model artifact verdict
FEATURES (ml/features/build.py:15-21): horizon, hour, dow, dom, event flags, rain/temp, tier/area/district, capacities, scale-normalised lags. No day index, no trend, no year. Anomaly features are peer robust-z. => reuse committed artifacts; no retrain. Caveat: weather Jun-Dec unseen in training (trees clamp).

## Baseline timings (verify stack, fixed mode)
seed 153 s; precompute 126 s = forecast 38.1 + risk 9.8 + rebalance 0.4 + anomalies 13.8 + backtest 60.7.


# ML Upgrade — Progress (prompt: ML UPGRADE, started 2026-10-05)

## Baseline git state at start (nothing committed by this upgrade)

`git status --short`:
```
 M .env.example
 M README.md
 M backend/app/api/v1/__init__.py
 M backend/app/core/clock.py
 M backend/app/core/config.py
 M backend/app/main.py
 M backend/app/schemas/system.py
 M backend/app/services/admin_data.py
 M backend/app/services/anomaly_scan.py
 M backend/app/services/backtest.py
 M backend/app/services/drift.py
 M backend/app/services/explanation.py
 M backend/app/services/forecast.py
 M backend/app/services/freshness.py
 M backend/app/services/help_scheduler.py
 M backend/app/services/help_trigger.py
 M backend/app/services/holdout_inputs.py
 M backend/app/services/jobs.py
 M backend/app/services/pipeline.py
 M backend/bootstrap.py
 M backend/ml/data_gen/load.py
 M backend/ml/data_gen/timeline.py
 M backend/ml/explain/factors.py
 M backend/ml/features/anomaly.py
 M backend/ml/features/panel.py
 M backend/scripts/bootstrap.sh
 M backend/tests/conftest.py
 M docker-compose.verify.yml
 M docs/ARCHITECTURE.md
 M docs/COMMANDS.md
 M docs/DECISIONS.md
 M docs/DEMO_SCRIPT.md
 M docs/METHODS.md
 M docs/SYNTHETIC_ASSUMPTIONS.md
 M frontend/openapi.json
 M frontend/src/api/hooks/admin.ts
 M frontend/src/api/keys.ts
 M frontend/src/api/schema.d.ts
 M frontend/src/api/services/admin.ts
 M frontend/src/api/types.ts
 M frontend/src/app/shell/FreshnessChip.tsx
 M frontend/src/features/admin/overview/AdminOverviewPage.tsx
 M frontend/src/features/landing/demoDay.ts
 M frontend/src/i18n/bn.json
 M frontend/src/i18n/en.json
 M frontend/src/lib/format.test.ts
 M scripts/check.ps1
 M scripts/check.sh
?? backend/app/api/v1/admin_clock.py
?? backend/app/schemas/admin_clock.py
?? backend/app/services/admin_clock.py
?? backend/app/services/data_clock.py
?? backend/app/services/data_scheduler.py
?? backend/data/
?? backend/ml/data_gen/live.py
?? backend/ml/data_gen/live_calendar.py
?? backend/ml/data_gen/live_load.py
?? backend/ml/data_gen/live_plan.py
?? backend/ml/data_gen/live_story.py
?? backend/tests/test_live_clock.py
?? docs/UPGRADE_PROGRESS.md
?? e2e/tests/live-clock.spec.ts
?? frontend/src/app/shell/FreshnessChip.test.tsx
?? frontend/src/features/admin/overview/DataClockPanel.test.tsx
?? frontend/src/features/admin/overview/DataClockPanel.tsx
```

`git diff --stat`:
```
 .env.example                                       |   4 +
 README.md                                          |  24 +-
 backend/app/api/v1/__init__.py                     |   2 +
 backend/app/core/clock.py                          |  80 ++-
 backend/app/core/config.py                         |  12 +
 backend/app/main.py                                |   6 +-
 backend/app/schemas/system.py                      |  17 +-
 backend/app/services/admin_data.py                 |   7 +-
 backend/app/services/anomaly_scan.py               |  34 +-
 backend/app/services/backtest.py                   |   7 +
 backend/app/services/drift.py                      |  36 +-
 backend/app/services/explanation.py                |   4 +-
 backend/app/services/forecast.py                   |  46 +-
 backend/app/services/freshness.py                  |  31 +-
 backend/app/services/help_scheduler.py             |  12 +-
 backend/app/services/help_trigger.py               |  13 +-
 backend/app/services/holdout_inputs.py             | 103 +++-
 backend/app/services/jobs.py                       |  16 +-
 backend/app/services/pipeline.py                   |   3 +
 backend/bootstrap.py                               |  38 +-
 backend/ml/data_gen/load.py                        |  18 +-
 backend/ml/data_gen/timeline.py                    |  65 ++-
 backend/ml/explain/factors.py                      |   7 +-
 backend/ml/features/anomaly.py                     |  40 +-
 backend/ml/features/panel.py                       |  86 ++-
 backend/scripts/bootstrap.sh                       |   3 +
 backend/tests/conftest.py                          |   2 +
 docker-compose.verify.yml                          |   3 +
 docs/ARCHITECTURE.md                               |  27 +-
 docs/COMMANDS.md                                   |  25 +-
 docs/DECISIONS.md                                  |  93 +++
 docs/DEMO_SCRIPT.md                                |  33 +-
 docs/METHODS.md                                    |  43 +-
 docs/SYNTHETIC_ASSUMPTIONS.md                      |  21 +-
 frontend/openapi.json                              | 625 +++++++++++++++++++++
 frontend/src/api/hooks/admin.ts                    |  15 +
 frontend/src/api/keys.ts                           |   1 +
 frontend/src/api/schema.d.ts                       | 390 +++++++++++++
 frontend/src/api/services/admin.ts                 |  10 +
 frontend/src/api/types.ts                          |   3 +
 frontend/src/app/shell/FreshnessChip.tsx           |  22 +-
 .../features/admin/overview/AdminOverviewPage.tsx  |   2 +
 frontend/src/features/landing/demoDay.ts           |   8 +-
 frontend/src/i18n/bn.json                          |  35 +-
 frontend/src/i18n/en.json                          |  35 +-
 frontend/src/lib/format.test.ts                    |  17 +-
 scripts/check.ps1                                  |   8 +-
 scripts/check.sh                                   |   6 +-
 48 files changed, 1962 insertions(+), 176 deletions(-)
```

## ML upgrade — log

Artifacts backup (before any training): `D:\Backup\agentpulse_artifacts_before_ml` (5 files, sha256 = manifest).
Verify stack switched to `CLOCK_MODE=fixed` (`docker compose -p agentpulse-verify ... up -d backend`): data rebuilt, ready in ~4 min (18:07 -> 18:11).

| Step | State | Result | Duration |
|---|---|---|---|
| Baseline benchmark (`scripts/ml_benchmark.py`, verify, fixed) | done | docs/ml_results/before.json; forecast matches manifest exactly; impact matches METHODS.md | 102 s |
| Baseline API bench | done | scripts/perf/out/api_ml_before.json, 64 endpoints in budget | 30 s |
| M1 split + forecast selection (`ml/training/splits.py`, `train.py`) | done | train < 2026-04-07, validation 04-07..04-20, blind test 04-21..05-04; leaves/rounds per quantile chosen on validation (63/31 leaves, 300-600 rounds) | training 662 s (verify) |
| M1 anomaly contamination on validation folds (`training/anomaly.py`) | done | 4 rolling 14-day folds before the holdout, max pooled F1 -> 0.0025 (grid edge, 7 positives); blind: P 0.94 / R 0.53 (was 0.96 / 0.73 non-blind) | 55 s |
| M2 conformal bands (`ml/inference/conformal.py`) | done | CQR per tail, Mondrian cells closed-hour x tier x area x horizon bucket; first version had all-zero offsets (zero-demand ties, seen on validation) -> closed-hour cell added, boosters kept, recalibrated (`train --recalibrate`) | recalibrate 134 s |
| M3 joint/coupled/refill-aware stockout (`stockout_joint.py`, `refill.py`, `training/dependence.py`) | done | copula per segment from validation residuals (rho 0.05-0.16, cross-path 0.65-0.87); decision input stays old method (recall rule); refill-aware view = additive API field `refill_aware`, migration 0023 | - |
| M4 helper acceptance (`data_gen/helpers.py`, `training/helper_accept.py`) | done | simulated behaviour, logistic + Platt; blind AUC 0.757; learned order/wave size opt-in (HELP_RANK_MODEL, HELP_WAVE_SIZING) | 7 s |
| Artifacts installed in backend/ml/artifacts | done | forecast lgbq-1.1.0-8a958da8, anomaly iforest-1.0.0-9aabad82, helper helper-1.0.0-4305ed17 | - |
| check -Backend (verify) | done | 2 failures fixed (migration head pin 0022->0023, import order); targeted reruns pass | 216 s |
| check -Up (verify, fixed) | done | ready; precompute 244 s: forecast 127.6 s (was 38.1 s: bigger boosters, TreeSHAP), risk 18.8 s (was 9.8 s), backtest 84 s | 36 s + 244 s |
| After benchmark + API bench (verify, fixed) | done | docs/ml_results/after.json; 64 endpoints in budget (scripts/perf/out/api_ml_after.json) | 295 s + 38 s |
| S1 split matching (MILP) | done | `match_flow`, `SWAP_MATCHING` (default assignment); replay: need covered 12.7% vs 8.4%, stockout h 78 vs 75 | - |
| Pre-existing bug fixed | done | impact replay entered an agent short of both floats twice as a cash swap receiver; fix + regression test; effect: same service, +4 van trips (1,069 vs 1,065) | - |
| S2 baselines | partly | 4-week seasonal naive + weekly exponential smoothing added; new features + time-series CV not done | - |
| S3 robust covariance comparison | done | MinCovDet per peer group, precision@k on blind windows; Isolation Forest kept | 22 s |
| S4 imperfect delivery + costs | done | benchmark sensitivity `app/services/impact_realism.py` | 26 s |
| S5 calibration drift + retrain advice | done | drift report: coverage vs held-out coverage, `retrain.suggested` (advisory) | - |
| -Slow (verify tools) | done | PASS (ML gate incl.) | 37 s |
| Fast tier | done with a caveat | ruff/tsc/eslint/vitest PASS; pytest all pass but wall time 215-352 s vs 240 s step limit (timed out twice) | - |
| Live mode check (verify) | problem found | bootstrap forecast 49.8 s (was 14.8), risk 30.8 s (was 12.1), backtest 140 s (was 74): hourly tick ~87 s > 60 s budget. TreeSHAP on the q50 booster 11.9 s vs 1.8 s per target | ready 319 s |
| Latency fix | in progress | q50 capped at 31 leaves x 300 rounds (selection inside the cap, validation), refill view 500 paths, backtest predictions on all cores; forecaster retrained | - |
| Latency fix | done | q50 kept from 1.0.0 (capped train-period q50 had worse blind MAE), served lgbq-1.1.0-7636a2e5; refill view 500 paths; backtest predict on all cores | retrain 540 s, recalibrate 135 s |
| Final after benchmark (fixed) | done | docs/ml_results/after.json; before.json re-run on old artifacts with the same code | 265 s / 194 s |
| Live mode final (verify) | done | bootstrap ready 232 s (forecast 16.1, risk 23.4, backtest 70.1 s); natural hourly tick 50.2 s (budget 60 s; was 25.1 s) | - |
| Final API bench (live) | done | 64 endpoints in budget, no 5xx (scripts/perf/out/api_ml_final.json) | ~40 s |
| -E2E (verify, live) | done | PASS | 509 s |
| -Slow + full fast pytest + ruff (final code and artifacts) | done | PASS / all pass (238 s wall) / PASS | 29 s + 238 s |
| State at end | - | verify stack left running in LIVE mode; main stack never touched (still old image + artifacts); nothing committed | - |

## Phase 1E — Test health (ML-3, LC-8) — done
Verify project `agentpulse-verify`, synthetic data. Nothing committed.

| Step | State | Result | Duration |
|---|---|---|---|
| Per-file measurement of fast pytest (`--durations=0`) | done | 805 tests; setup 108 s, call 69 s; no test over 7 s; collection 11 s; no test belongs in `slow` | 201 s / 196 s |
| `scored` fixture uses session `scored_template` (conftest) | done | affects test_llm_api, test_copilot_api, test_prompt_injection, test_query_counts: ~40 s -> ~17 s | 29 s (4 files) |
| `-PytestTimeout` / `CHECK_PYTEST_TIMEOUT` (default 300) in check.ps1, env in check.sh; docs/COMMANDS.md | done | `-Slow`/`-Full` keep 1200 s unless set | - |
| Fast tier x3 (`check.ps1 -Backend -PytestTimeout 300`) | done | pytest step 168.7 s, 173.0 s, 181.3 s; all pass; target < 200 s met | 3 x ~185 s |
| `-Up` + full e2e (verify, ports 18000/15173) | done | 120 passed, 0 failed (11 spec files) | up 12 s, ready 27 s, e2e 542 s |

Commands over 2 minutes: fast pytest 3 x ~175 s; e2e 542 s.

## Phase 1A — Clean-machine readiness (ML-12, LC-1, LC-9, LC-11) — done
Verify project `agentpulse-verify`, new volume `agentpulse-verify_fresh1`, synthetic data. Nothing committed.

| Step | State | Result | Duration |
|---|---|---|---|
| PyYAML pinned (`requirements.txt`, F4) | done | `PyYAML==6.0.3` = version in the image | - |
| Fresh volume, live, `up --build -d` | done | ready=true; migrations 0001-0023 applied on empty DB, current = head = 0023 | up 87 s, ready 291 s |
| Demo login (agent, distributor, admin) + `/admin/clock` in live | done | all 3 logins OK; mode live | - |
| Switch to `CLOCK_MODE=fixed` (same volume) | done | rebuild, ready; mode fixed, data hour 2026-04-30 20:00 Dhaka; 3 logins OK; 11 users and audit kept | 189 s |
| Switch back to live | done | rebuild, ready | 157 s |
| README "First start after upgrading"; PERFORMANCE.md "Clean-database start" | done | numbers in PERFORMANCE.md | - |

Commands over 2 minutes: the three boots above (291 s, 189 s, 157 s). A cold build (no image cache) was not measured. Verify stack left running in LIVE mode on the fresh1 volume.

## Phase 1B — Tick performance (ML-2, LC-2) — done
Verify project `agentpulse-verify`, 300 agents, synthetic data. Nothing committed.

| Step | State | Result | Duration |
|---|---|---|---|
| Baseline profile (`scripts/perf/profile_tick.py`, `force_tick.sh`) | done | tick 31.2 s (forecast 11.4, risk 15.5, rebalance 0.3, anomalies 4.0); midnight 74.5 s (backtest 44.2) | ~3 min |
| Backtest out of the tick (`backtest_job.py`, F5) | done | own leader + 180 s budget, polls 60 s + wake, not during a tick; `GET /admin/clock` `backtest`; card line | - |
| Risk speed-up (F7) | done | projections on 4 threads (live), vectorised Postgres history; risk 14.7 -> 6.0 s isolated; old vs new rows identical | - |
| Non-overlap guard (F6) | done | `data_clock.tick_guard`; skip logged + `skipped_ticks` / `last_skipped_at` | - |
| Tests | done | `tests/test_tick_jobs.py` (4), DataClockPanel vitest (+2) | - |
| After (live, forced ticks) | done | normal 24.3-33.0 s, median 26.3 s; midnight 25.5 s; backtest job 42.2 s separately | - |
| Fixed-mode fingerprint (new volume `agentpulse-verify_fixed1`) | done | all caches identical: bootstrap vs recompute vs recompute with old history loader | boot 344 s, 3 x ~2 min |
| Back to live (default volume `agentpulse-verify_pgdata`) | done | ready 71 s | - |

Commands over 2 minutes: fixed boot 344 s (ran beside a pytest run); fingerprint recomputes ~2 min each; first `-Backend` run timed out at 300 s (CPU shared with the fixed boot, no failures shown); re-run on an idle PC: `-Backend` PASS (267 s), `-Frontend` PASS (172 s).
Not measured: a natural (hour-boundary) tick on the new code; a real midnight tick.

## Phase 1C — No-key LLM behaviour (LC-3) — done
Mocked providers only; no key was read, set or used. Nothing committed.

| Step | State | Result | Duration |
|---|---|---|---|
| `no_api_key` on every wording response + status; replay only on the fixed clock (F8) | done | `mode.py`, `service.py`, `status.py`, `schemas/llm.py`; openapi.json + schema.d.ts edited by hand | - |
| UI label "Template wording (no API key)" bn/en (Why, Copilot, briefing, anomaly) | done | `lib/wording.ts`; admin LLM page shows why replay is skipped | - |
| bn/en templates: next-step lines, no new numbers | done | `templates.py` | - |
| README: free OpenAI-compatible key steps | done | | - |
| Tests | done | `tests/test_llm_no_key.py` (16), vitest (wording, briefing, admin); `check.ps1 -Backend -Frontend` all PASS (pytest 197.6 s, vitest 86 s) | 372 s total |

## Phase 2 — Model quality (ML-6, ML-1, ML-5, ML-4) — doing
Verify project `agentpulse-verify`, `CLOCK_MODE=fixed`, volume `agentpulse-verify_fixed1`, synthetic data. Nothing committed.
Backup: `D:\Backup\agentpulse_artifacts_phase2` (all artifact files, before any training).
Adoption rules, fixed before any blind result was read:
- Anomaly (ML-6 + ML-1, one model): served only if the gate passes (blind P >= 0.5, R >= 0.5) and blind window F1 >= the old 0.681; else the old artifact stays.
- Bands (ML-5): per target, region cells only if the cross-fitted validation group gap is smaller; kept only if the blind open-hour group gap is not worse.
- Stockout (ML-4): joint becomes default only if, at its validation cut, blind TP >= and FP <= the independent method's.

| Step | State | Result | Duration |
|---|---|---|---|
| Code: ledger refills + burst measures, inputs per artifact | done | old artifact still loads (legacy inputs) | - |
| Code: 8 validation folds (14 d, every 8 d), selection inputs x burst_k x share | done | targeted pytest + ruff pass | 87 s |
| Code: region band cells + cross-fit choice; stockout cut script | done | | - |
| Anomaly candidate training | doing | | |

## Phase V1 — Van core backend (F14 core stage) — done (1 open item)
Spec: docs/VAN_ROUTING_SPEC.md (core stage). Verify project `agentpulse-verify`. Synthetic data. Nothing committed.
Approved changes to the plan: every vehicle default is a `VAN_*` setting (SYNTHETIC_ASSUMPTIONS.md), >= 2 vans; admins read-only (list/detail GET), create/decision/stop actions distributor-only.

| Step | State | Result | Duration |
|---|---|---|---|
| OR-Tools pinned + image build | done | ortools 9.15.6755 imports; fallback test passes without it | build 129 s |
| Rules (models, matrix, cost, heuristics, solver) | done | 18 rules tests pass; native matrices (callbacks were too slow) | - |
| Migration 0024, models, schemas, services, API | done | API + migration + route-sweep tests pass | - |
| Road cache script (one try) | done | run 1: internet OK, DST-DHK done, then one HTTP 400 (1-coordinate self block) aborted all (script bug); fixed to skip refused requests; run 2: all 3 distributors, every pair cached, 1.53 MB | run 1: 438 s, run 2: 1147 s |
| Tests (fast) + eval (slow) | done | fast van tests pass (~15 s); test_van_eval FAILS: D total BDT 6.46M > A 2.62M (open item 1) | eval 36 s |
| check.ps1 -Backend, -Slow once | done (2 open) | -Backend: all pytest pass after head 0023->0024 in test_system; ruff FAIL only on untracked scripts/ml_benchmark.py (not V1). -Slow: only test_van_eval fails | -Backend 309 s (timeout, CPU shared with cache run) + 395 s; -Slow 61 s |

Eval (backend/ml/van/van_v1_eval.json, synthetic data, seed 42, 39 held-out instances, 677 stops, road_cache): total BDT A 2.62M / B 10.90M / C 20.45M / D 6.46M; van BDT A 2.29M / D 0.44M; trips A 677 / D 64; stockout h A 58 / D 1,721; D solve mean 512 ms, max 2.76 s, 0 time-limit hits.
Open: (1) D beats B and C but not A: A has no fleet limit (677 trips at once), D has 2 vans; lost value dominates. Test kept as written, not loosened.

## Phase V2 — Van routes frontend (F14 UI) — done (1 note)
Spec: docs/VAN_ROUTING_SPEC.md section 9. Verify project `agentpulse-verify`. Synthetic data. Nothing committed. V1 was done (its open eval item is unchanged).

| Step | State | Result | Duration |
|---|---|---|---|
| Backend: `depot` on the plan response (additive) + test line | done | `pytest tests/test_van_plans_api.py` 8 passed, ruff clean | 32 s |
| `api/vanPlans.ts` (Zod, TanStack Query), route, nav (Truck), tokens, i18n bn/en | done | typecheck + eslint pass | - |
| Page: controls, map, stop list, savings, fairness, narrative, approve dialog, states | done | 11 components + page, each with a vitest file | - |
| e2e: `van-routes.spec.ts` (create, stops, approve with note, admin audit entry, agent gets 403) | done | passes; the e2e dataset gave 40 served / 64 skipped stops, road_cache | - |
| First-load budget (/login, 250 KB gzip) | done | broke at 253.6 KB; fixed to 255,992 B (8 B under 256,000), see V14, V15 | 3 builds, 35 s each |
| `check.ps1 -Frontend -Up -E2E` (final) | done | all PASS: typecheck, eslint, vitest, e2e | 649 s total (vitest 95 s, e2e 466 s) |

Note: the first full run took 814 s and had two e2e failures (budget 253.6 KB; a wrong audit-row assertion in my spec). Both fixed, then the full run above.
Open: first-load headroom is 8 B (the tree without the feature had 310 B). The next first-load addition will fail the budget test; see docs/DECISIONS.md V15.


## Phase V3 — Van should stage + evaluation (F14) — done (2 open items)
Spec: docs/VAN_ROUTING_SPEC.md (should stage). Verify project `agentpulse-verify`. Synthetic data. Nothing committed.

| Step | State | Result | Duration |
|---|---|---|---|
| Rules: fairness, safety, stability, robust; solver.plan; pins in OR-Tools + fallback | done | 13 new rules tests pass | - |
| Services: q50 amber amount, curve deadline, ETA range, before-arrival flag, freeze, pins API, store split | done | 9 new API tests pass; 2 V1 assertions moved to V3 (V23) | - |
| LLM narrative intent `van_narrative` (migration 0025), guard + log + fallback | done | mocked-provider test: llm / numbers_fail -> template | - |
| `GET /impact/van-comparison` + `ml/van/evaluate.py` (5 seeds, sensitivity) | done | D < C on 5/5 seeds; D > A on 5/5 (see METHODS.md) | eval 282 s |
| Frontend: `excluded` reason, at-risk / pin / fairness chips, Zod fields | done | vitest pass | - |
| ML-10 refill-aware line on /agent/stockout | not shipped | gate "all tests pass" not met (test_van_eval); patch kept outside the repo | - |
| check.ps1 -Backend -Frontend | done | ruff: only scripts/ml_benchmark.py I001 (pre-existing, import sort applied); pytest hit the 300 s step limit; frontend pass | 506 s |
| Fast pytest, direct run (limit unchanged) | done | 882 passed, 10 skipped, 0 failed | 519 s |
| check.ps1 -Slow | done (1 open) | only test_van_eval fails (V1 open item, unchanged) | 72 s |
| check.ps1 -Up -E2E | done (1 open) | run 1: port 8000 clash (verify ports not set, main stack untouched); run 2 cut off by a Docker restart; run 3: all e2e pass except the /login budget: 256,013 B gzip vs 256,000 (V2: 255,992). New van code is only in lazy chunks | e2e 541 s |

Open: (1) test_van_eval D <= A still fails: A has no fleet limit; D drops ~99 stops/seed for capacity with 2 vans. (2) ML-10 not shown (gated on (1)). (3) /login first load 13 B over budget (hash churn of first-load files that name lazy chunks, or other uncommitted work); needs a first-load trim outside V3 or a budget decision.

## Fix F3 — Test health (re-run) — done (target not met on every run)
Verify project `agentpulse-verify`, synthetic data. Nothing committed. Decision F9.

| Step | State | Result | Duration |
|---|---|---|---|
| Measure `--durations` (fast tier) | done | 3 x anomaly-forest fixture setup (56 + 46 + 40 s) = one fixture built once per importing module | 243 s wall |
| Fixture moved to conftest (built once) | done | anomaly setup 3 x ~45 s -> 1 x ~25 s | - |
| `shared_routes` (create_app 90 -> 28 ms) | done | per-test setup sum 125 s -> 87 s (incl. 25 s training) | - |
| ruff | done | `ruff check .` clean (ml_benchmark.py import order via `--fix`) | 2 s |
| `check.ps1 -Backend` after changes (x3) | done | pytest step 168.8 s, 212.2 s, 222.4 s; all pass. Host load varies run to run | 3 x ~215 s |

Commands over 2 minutes: fast pytest runs (170-250 s each).

## Phase V4 — Van map polish (status rings, stop card, headline savings) — done (e2e not run)
Frontend only, synthetic data. Nothing committed. Decision V24.

| Step | State | Result | Duration |
|---|---|---|---|
| Status rings + "!" badge on markers, legend keys (risk / in time / not served) | done | from `stockout_risk_flag` or `late_h > 0`; route colour kept as fill | - |
| Select from list or marker: ease to stop (reduced motion: instant) + stop card | done | card: van + stop no., ETA range, cash to bring, deadline, status; list click scrolls the map back into view | - |
| Savings panel headline: km saved, total cost saved (with %), approval status chip | done | negative savings shown as "Extra distance/cost", red | - |
| check.ps1 -Frontend | done | typecheck, eslint, vitest all pass (first run) | 179 s |
| vite build (to container /tmp) | done | builds; van code stays in the lazy VanRoutesPage chunk (28.9 KB gzip) | 12 s |
| check.ps1 -Up -E2E | not run | ~9 min, over the 5 min limit; no route or flow changed | - |

Open: e2e and the /login first-load budget (13 B over since V3) not re-measured this phase.

## Phase V5 — Van map sequential navigation (arrows, itinerary, street tiles) — done (e2e not run)
Frontend only, synthetic data. Nothing committed. Decision V25.

| Step | State | Result | Duration |
|---|---|---|---|
| Direction chevrons on route legs (SDF image, no sprite), zoom-scaled line width | done | layer `van-route-arrow`, hidden in separate-trips view | - |
| Itinerary per van: depot, leg km/time into each stop, drive back, van cost, savings line | done | `itinerary.ts`, `RouteItinerary.tsx`, `StopRow.tsx` split out of StopList | - |
| Stop card: delivery instruction, drive in, next stop / back to depot | done | skipped stops show neither | - |
| Street-tile toggle on van map (opt-in, shared with control room), CARTO @2x tiles | done | default stays offline | - |
| check.ps1 -Frontend (x2) | done | run 1: 1 type error + 1 test (compact cost text); fixed; run 2: typecheck, eslint, vitest all pass | 179 s, 175 s |
| check.ps1 -Up -E2E | not run | ~9 min, over the 5 min limit; no route added | - |

Commands over 2 minutes: check.ps1 -Frontend (179 s, 175 s).
