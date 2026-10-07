# AgentPulse: Fix + Van Route — প্রম্পট গাইড

## এই সেটে ৩টা ফাইল
| ফাইল | কাজ |
|---|---|
| `docs/UPGRADE_RULES.md` | সব safety rule, test-এর নিয়ম, FINAL REPORT-এর ফরম্যাট এক জায়গায়। প্রতিটা প্রম্পট শুধু এই ফাইলের রেফারেন্স দেয়, তাই প্রম্পট ছোট আর token কম লাগে |
| `docs/VAN_ROUTING_SPEC.md` | Van Route Optimizer-এর পূর্ণ spec (তোমার Part B, রিপোর যেমন নিয়ম তেমনভাবে সাজানো) |
| এই ফাইল | কোন প্রম্পট, কোন ক্রমে, কোন মডেলে |

**LC-1-এর সিদ্ধান্ত লেখা হয়ে গেছে:** `docs/DECISIONS.md`-এ F1 হিসেবে। Default থাকবে `live`, আর fallback হিসেবে থাকবে `CLOCK_MODE=fixed`।

**রিপোতে যাচাই করা আছে:**
- `backend/ml/inference/refill.py`, `backend/ml/artifacts/anomaly_manifest.json`, `docs/ml_results/after.json` আর `scripts/check.ps1` সত্যিই আছে।
- Distributor-এর depot আগে থেকেই আছে: `distributors.hub_lat/hub_lng`। তাই নতুন column লাগবে না।
- Test-গুলো `backend/tests/`-এ সমতলে থাকে (`rules/`, `api/` নামে কোনো সাব-ফোল্ডার নেই)। Frontend কোড থাকে `features/distributor/...`-তে, `pages/` বা `hooks/`-এ নয়। তাই Part B-র file tree আমি রিপোর নিয়মে বদলে spec-এ লিখেছি।
- OR-Tools এখনো requirements-এ নেই। এটা নতুন dependency, তাই V1-এ এর কারণ লিখে পিন করতে হবে।

---

## নিয়ম (প্রতিটা প্রম্পটে)
1. **এক সেশনে এক ফেজ।** প্রতিটার আগে `/clear`।
2. **শুরুর আগে commit:** আগের ফেজ ঠিক লাগলে নিজে `git add -A` আর `git commit` করো। কিছু ভাঙলে ফিরে যাওয়ার পথ শুধু এটাই।
3. **Plan mode** (`Shift+Tab` দুবার) শুধু ⭐ চিহ্নিত ফেজে দাও। প্ল্যান পড়ে approve করো, তারপর build হবে। বাকি ফেজের spec এমনিতেই পরিষ্কার, সেখানে plan mode দিলে শুধু token নষ্ট হবে।
4. Model বা effort মাঝপথে বদলিও না। Docker Desktop চালু রাখো, অন্য Claude সেশন বন্ধ রাখো।
5. রিপোর্টের **NOT FIXED** অংশ পড়ে তারপর পরের ফেজে যাও।

## ক্রম আর মডেল

| # | ফেজ | মডেল / effort | Plan mode | আনুমানিক সময় |
|---|---|---|---|---|
| 1 | 1E Test health | Sonnet 5.5, High | না | ছোট |
| 2 | 1A Clean-machine readiness | Sonnet 5.5, High | না | মাঝারি (fresh build) |
| 3 | 1B Tick performance | Opus 5.5, Medium | না | মাঝারি |
| 4 | 1D Demo story stability | Opus 5.5, High | ⭐ হ্যাঁ | মাঝারি |
| 5 | 1C No-key LLM | Sonnet 5.5, High | না | ছোট |
| 6 | 2 Model quality | Opus 5.5, High | ⭐ হ্যাঁ | বড় |
| 7 | 3 Polish (ঐচ্ছিক) | Sonnet 5.5, High | না | মাঝারি |
| 8 | V1 Van core backend | Opus 5.5, High | ⭐ হ্যাঁ | বড় |
| 9 | V2 Van frontend | Sonnet 5.5, High | না | মাঝারি |
| 10 | V3 Van should + evaluation | Opus 5.5, Medium | না | মাঝারি |

**তোমার তালিকা থেকে ক্রম কেন বদলেছি:**
- **1E আগে:** test suite এখনই সময়সীমা ছাড়িয়ে যায়। এটা ঠিক না করলে পরের প্রতিটা ফেজের check timeout হবে আর token নষ্ট হবে।
- **1D আগে, 1C পরে:** 1C-র fixed-mode replay আর 1A-র "দুটো clock mode চালু হয়" চেক, দুটোই demo story স্থির থাকার উপর নির্ভর করে।
- **Scam guard (`docs/SCAM_GUARD_PLAN.md`):** Van-এর পরে, Prompt 3-এর আগে দাও। তার S0-এর ৩ নম্বর কাজ (test timeout) 1E-তে হয়ে যাবে, তাই সেখানে বাদ দিতে বলো।
- **ML-11** (বাংলা model-card লাইন) তুমি নিজে পড়বে। **ML-7, ML-8, LC-10** ঠিক করা হবে না, শুধু খোলাখুলি জানানো হবে (disclose)।

---

## 1. Phase 1E: Test health  (Sonnet 5.5, High)
```text
PHASE 1E TEST HEALTH. Follow docs/UPGRADE_RULES.md. Items ML-3, LC-8.
1. Measure the fast backend tier per test file (pytest --durations=30) on the verify project. Move tests that train models, load the full synthetic set or take > 10 s into @pytest.mark.slow ONLY if they belong there per CLAUDE.md; never delete or weaken a test. Prefer making slow fixtures reuse the session-scoped DB templates (seeded, ready, flagged, backtested).
2. Make the pytest step limit configurable in scripts/check.ps1 (-PytestTimeout, else env CHECK_PYTEST_TIMEOUT, else 300) in the same style as -E2ETimeout; update docs/COMMANDS.md.
3. Target: the fast tier finishes under 200 s on 3 consecutive runs. Report each duration.
4. Run the full e2e suite once on the verify project (-Up -E2E) and record pass/fail per spec.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 2. Phase 1A: Clean-machine readiness  (Sonnet 5.5, High)
```text
PHASE 1A CLEAN-MACHINE READINESS. Follow docs/UPGRADE_RULES.md. Items ML-12, LC-1, LC-9, LC-11. Decision F1 in docs/DECISIONS.md is final (live default, fixed fallback).
1. Add PyYAML to backend requirements explicitly with a pinned version matching the one already installed in the image.
2. On a brand-new volume of the verify project (create a new volume name there; never touch the main volume): build, bootstrap, reach ready=true. Verify migrations up to the head apply cleanly on an empty database. Record the command, CPU/RAM, image-cache state (cold or warm), the definition of start and ready, and the time in docs/PERFORMANCE.md.
3. Boot once with CLOCK_MODE=live and once with CLOCK_MODE=fixed on the verify project; check /api/v1/system/status and a demo login for each.
4. README: one short section "First start after upgrading" saying the first rebuild replaces the old fixed April data with live data (logins and settings kept), and how to set CLOCK_MODE=fixed.
Acceptance: fresh volume -> ready; login works; both clock modes start; docs match behaviour.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 3. Phase 1B: Tick performance  (Opus 5.5, Medium)
```text
PHASE 1B TICK PERFORMANCE. Follow docs/UPGRADE_RULES.md. Items ML-2, LC-2.
1. Profile the hourly tick on the verify project (300 agents): time per step (data, forecast, risk incl. refill-aware view, rebalance, anomalies). Record the baseline.
2. Move the daily impact backtest out of the tick into its own leader-guarded background job with its own budget; show its last run, duration and status as a line on the admin Data clock card (additive API field).
3. Reduce or cache the refill-aware computation (e.g. reuse per-agent refill patterns that only change daily) and remove any other repeated work you find, without changing results in fixed mode (compare the fixed-mode fingerprint before and after).
4. Add a non-overlap guard: a tick that is still running blocks the next one, which is skipped and logged.
Acceptance: normal tick <= 40 s, the first tick after midnight < 60 s, the backtest runs separately, fixed-mode outputs unchanged. Tests for the guard and the job split.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 4. Phase 1D: Demo story stability  (Opus 5.5, High, ⭐ Plan mode)
```text
PHASE 1D DEMO STORY STABILITY. Follow docs/UPGRADE_RULES.md. Items LC-5, LC-6, plus the story-list part of LC-7. Plan first, then build after my approval.
Goal: a judge starting the app at ANY date and time sees the scripted cash shortage for AGT-0001 a few hours ahead (a sensible afternoon or next-afternoon time) with a donor nearby, and AGT-0005 clearly flagged as an anomaly.
1. Find the current re-anchor logic (ml/data_gen/live_story.py, demo_scenario.py, demo_spec.py, the system_meta story list). Explain in the plan why the predicted time drifts (15:40 scripted vs 19:28 predicted 22 h ahead) and why the anomaly score fades.
2. Pinned demo story: re-anchor daily so the shortage always lies inside the next hours, and inject the AGT-0005 anomaly episode so its score stays clearly above the threshold (target margin >= 0.03 over the threshold, measured). Labelled demo event only, never a fake holiday. Keep DEMO_MODE actions (simulate shortage, reset demo) working.
3. Prune old story entries: keep only the last 7 in system_meta.
4. Test: inject the clock at 5 different times of day across at least 3 simulated days (incl. a midnight crossing); assert the shortage window and the anomaly flag each time. Fixed mode must stay bit-identical.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 5. Phase 1C: No-key LLM behaviour  (Sonnet 5.5, High)
```text
PHASE 1C NO-KEY LLM. Follow docs/UPGRADE_RULES.md. Item LC-3. Never use or call a real key.
1. In live mode without a key, every LLM surface (copilot, explanations, briefing, anomaly narrative) shows a clear label "Template wording (no API key)" in bn/en, and generated_by stays truthful (template / replay / llm). Check every surface.
2. Improve the deterministic bn/en templates where they read thin, without changing any number (numbers guard still passes).
3. Keep replay working in CLOCK_MODE=fixed for the scripted scenario; in live mode replay is skipped by design and the status endpoint says why.
4. README: steps to use a free OpenAI-compatible key (LLM_PROVIDER, base_url, model) set by the user in .env themselves; do not create or edit .env.
Acceptance: tests with mocked providers for with-key and no-key; labels visible; no live call during tests.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 6. Phase 2: Model quality  (Opus 5.5, High, ⭐ Plan mode)
```text
PHASE 2 MODEL QUALITY. Follow docs/UPGRADE_RULES.md (backup the artifacts first). Items ML-6, ML-1, ML-5, ML-4. Plan first, then build after my approval. Run benchmarks in CLOCK_MODE=fixed.
Record the before numbers from backend/ml/artifacts/anomaly_manifest.json, manifest.json and docs/ml_results/after.json in docs/ML_UPGRADE_RESULTS.md (new "Phase 2" columns).
1. ML-6: switch the anomaly "refills" feature to the ledger-based detector in backend/ml/inference/refill.py. Report refills found vs the real count (about 19,365).
2. ML-1: add volume-burst features (peer-relative short-window volume ratio, burst count, rate change). Choose features, thresholds and contamination on train/validation only. Score the blind test ONCE at the end; report precision/recall overall and per anomaly style. The anomaly gate must still pass.
3. ML-5: recalibrate the cash-in quantile bands on validation, per group (tier, region, urban/rural). Report coverage and the group gap before/after; state plainly if tier-3 stays below 0.80.
4. ML-4: re-tune the joint stockout alert cut on validation only. Switch the default only if it catches at least as many stockouts at equal false alerts on the blind test; otherwise keep the default and document.
Keep the old artifact as default for any item that got worse. Update METHODS.md, the model card text and DECISIONS.md.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 7. Phase 3: Polish (ঐচ্ছিক)  (Sonnet 5.5, High)
```text
PHASE 3 POLISH. Follow docs/UPGRADE_RULES.md. Do the items in this order and stop cleanly when time runs out:
1. LC-7: daily retention job pruning snapshot and transaction rows older than the 120-day window (leader-guarded, idempotent, keeps is_holdout consistent); in live mode the retrain action shows a clear bn/en message explaining it runs only in CLOCK_MODE=fixed.
2. LC-4: the drift report waits for a minimum window (e.g. 7 days of live data) before raising an alarm and shows a seasonality note (months unseen in training).
3. ML-9: time-series cross-validation on the training period only, reported next to the current validation numbers; keep the model unchanged unless validation improves.
(ML-10 refill_aware in the UI is done after the van phases.)
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 8. V1: Van core backend  (Opus 5.5, High, ⭐ Plan mode)
```text
VAN V1 CORE BACKEND. Follow docs/UPGRADE_RULES.md and docs/VAN_ROUTING_SPEC.md (core stage only: BDT objective, soft windows, drop reasons, road cache with estimate fallback, baselines A-C, API, narrative template). Plan first, then build after my approval.
1. Add OR-Tools (pinned) with a DECISIONS.md entry; confirm the backend image builds and the fallback heuristic works when OR-Tools is absent.
2. Migration (next free number), models, schemas, app/rules/van_routing/*, services, app/api/v1/van_plans.py, decision -> audit_log, role scoping.
3. backend/scripts/build_road_cache.py: try it once; if no internet in the container, ship the haversine-estimate path only and report it.
4. Tests from spec section 11 (fast tier); the evaluation test is @pytest.mark.slow.
5. Run check.ps1 -Backend, then -Slow once.
FINAL REPORT per docs/UPGRADE_RULES.md, including the measured solve time and the cost vs separate trips (synthetic data).
```

## 9. V2: Van frontend  (Sonnet 5.5, High)
```text
VAN V2 FRONTEND. Follow docs/UPGRADE_RULES.md, docs/VAN_ROUTING_SPEC.md section 9, docs/DESIGN.md and docs/PRODUCT_CHECKLIST.md. V1 must be done (check docs/UPGRADE_PROGRESS.md); otherwise stop.
Build /distributor/van-routes in frontend/src/features/distributor/vanRoutes with frontend/src/api/vanPlans.ts (Zod, TanStack Query, no `any`), reusing the control-room MapLibre setup. Navigation item (lucide Truck). Add the route to e2e/routes.ts and write e2e/tests/van-routes.spec.ts (create plan, see stops, approve with note, see the audit entry as admin). Vitest for each component.
Run check.ps1 -Frontend, then -Up -E2E once at the end.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

## 10. V3: Van should + evaluation  (Opus 5.5, Medium)
```text
VAN V3 SHOULD STAGE. Follow docs/UPGRADE_RULES.md and docs/VAN_ROUTING_SPEC.md (should stage): forecast-aware amount and ETA range, stockout-before-arrival check, fairness guard, safety (cash cap, near-optimal random choice), stability (freeze, lock/include/exclude), LLM narrative through the existing guard, GET /impact/van-comparison, ml/van/ evaluation of policies A-D with >= 5 seeds and sensitivity. Report D vs C honestly. Then, only if all tests pass, show refill_aware in the agent stockout UI (ML-10). Update METHODS.md, SYNTHETIC_ASSUMPTIONS.md, JUDGING_MAP.md, DEMO_SCRIPT.md.
Run check.ps1 -Backend -Frontend, then -Slow and -Up -E2E once at the end.
FINAL REPORT per docs/UPGRADE_RULES.md.
```

---

## মাঝপথে সেশন থেমে গেলে  (একই মডেলে)
```text
Read docs/UPGRADE_PROGRESS.md and docs/DECISIONS.md. Continue the unfinished phase (named in the progress file) from its first unfinished item, following docs/UPGRADE_RULES.md and, for van phases, docs/VAN_ROUTING_SPEC.md. Do not redo finished items. End with the FINAL REPORT.
```

## Token বাঁচানোর টিপস
- প্রম্পট শুধু ফাইলের রেফারেন্স দেয়, তাই নিয়ম বারবার পাঠাতে হয় না। কোনো নিয়ম বদলাতে চাইলে শুধু `UPGRADE_RULES.md` বদলাও।
- Plan mode-এ প্ল্যান ভালো না লাগলে পুরো প্রম্পট আবার দিও না। শুধু লেখো কোন অংশ বদলাতে হবে।
- রিপোর্ট পাওয়ার পর একই সেশনে ছোট প্রশ্ন করো। নতুন ফেজ শুরু করার আগেই শুধু `/clear` দাও।
- `-Full` কখনো চাইবে না। প্রতিটা ফেজ নিজের check একবার করেই চালাবে।
