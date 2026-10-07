# Decisions (hardening pass)

Decisions taken during the hardening pass without asking, each with the safest default.
Format: what, why, alternative considered.

## D1. Isolated verify stack with a compose overlay
- What: `docker-compose.verify.yml`, run as project `agentpulse-verify` on ports 18000/15173 with
  its own volume. It forces `LLM_PROVIDER=template`, `PERF_HEADERS=true`,
  `API_RATE_PER_MIN=1000000`.
- Why: load, fuzz and chaos tests must never touch the main stack or spend LLM credit. Bench and
  load clients share one IP, so the coarse per-IP cap would turn a latency test into a 429 test;
  that cap is covered by pytest (`test_hardening.py`) instead.
- Alternative: a second `.env`. Rejected: compose always reads the project `.env` via `env_file`,
  and `environment:` is the only layer that reliably overrides it.

## D2. Opt-in `Server-Timing` header (`PERF_HEADERS`, default off)
- What: per-request SQL query count, DB time and total time (`app/core/perf.py`).
- Why: the only way to count queries per endpoint from outside, and to catch N+1 regressions in
  the -Perf gate. Off by default so production responses carry no timing data.

## D3. Several uvicorn workers + shared security rate limits
- What: `entrypoint.sh` starts `WEB_CONCURRENCY` workers (default: CPU count clamped to 2..4).
  The security limits (login per IP, demo login, signup, password reset, per-user LLM calls)
  moved from process memory to the `rate_limit_hits` table (`app/core/shared_limit.py`), so they
  stay exact across workers. The coarse per-IP request cap stays in process and is divided by
  the worker count.
- Why: measured. One process served ~47 req/s at 50 users (p95 1.7 s) because handlers are
  CPU-bound Python. In-process limiters would silently become N times looser with N workers.
- Alternative: keep one worker and only shave CPU per request. Not enough: even halving the cost
  leaves one core for every user.
- Trade-off: the coarse cap is approximate per worker (a client can be limited slightly early if
  its requests land unevenly). It is a flood guard, not a security boundary.

## D4. Load-test user model
- What: each k6 virtual user loads a page's requests, then thinks for 3-6 s (see
  `scripts/perf/load.js`).
- Why: a 1 s think time made every virtual user ~10x busier than a real person. Budgets are set
  for realistic users; the aggressive profile is still reported in docs/PERFORMANCE.md.

## D5. Build chunk grouping (frontend/vite.chunks.ts)
- What: modules the first load needs (the entry, landing and auth pages) keep the default split;
  everything else is grouped: icons, libraries and app code shared by two or more routes.
  A small build plugin records the entry's and the public pages' static import graphs (and the
  lucide icons they import, resolved through lucide's own export table) at `buildEnd`.
- Why: measured. A cold visit to /agent fetched ~70 chunks under 2 KB after the shell, six at a
  time over HTTP/1.1; on Slow 4G that was ~7 s of the 10 s LCP. Now +19 files (was +68); initial
  JS 176 KB gz (was 178), / and /login first loads unchanged (budget 250 KB).
- Alternatives measured (scripts/bundle-report.mjs): one shared chunk for everything (initial
  231-240 KB, /login over budget); one lazy vendor chunk (+120-140 KB per route); icons only
  (+44 files per route). HTTP/2 would lift the six-connection limit but needs TLS in browsers.

## D6. Startup screen only when it is true
- What: BootstrapGate renders a blank page while the first status answer is in flight, and the
  "Preparing" screen only when the backend reports not-ready or cannot be reached.
- Why: every cold load flashed "First start takes a minute", which was also measured as the LCP
  element.

## D7. Refresh-token retry grace (30 s)
- What: a rotated refresh token presented again within 30 s, while its successor has never been
  used, replaces that unused successor instead of revoking the whole session family. A row lock
  serialises two refreshes of the same token. Any other reuse still revokes the family.
- Why: found while measuring. A reload, navigation or dropped mobile connection during a refresh
  leaves the browser with the old cookie although the server already rotated it; the next load
  looked like token theft and signed the user out (reproduced in the vitals run; regression
  tests in tests/test_auth_refresh.py).
- Trade-off: a thief who replays a stolen token inside those 30 s, before the real user's
  browser uses its new token, gets a session and the real user is signed out (visible to them).
  Before, both were signed out. Alternative: keep strict reuse detection and accept random
  logouts on flaky networks; rejected for a product aimed at agents on mobile data.

## D8. Thread pool left at the anyio default (40 per worker)
- Measured with 50 users: 8 threads per worker gave 10-25% more throughput, 4 threads
  deadlocked (requests hung 60 s: sync dependencies with `yield` need a free thread to finish).
  The gain is not worth a deadlock margin, so the default stays.
- Pool size (5+10 vs 20+0) and 8 workers instead of 4 made no meaningful difference.

## D9. What-if path cache (per worker, 8 entries)
- What: the 2,000 sampled demand paths and the "before" scenario are kept per agent and float;
  each slider move only re-projects the new balance. The key includes a digest of the cached
  forecast quantiles and the balance, so new data never hits a stale entry.
- Why: sampling was most of a what-if call (p95 under 50 users: 670 ms before, 108 ms after).
  Results are identical (tests compare cached and fresh answers bit for bit). Memory: ~2.3 MB
  an entry, ~18 MB per worker at most.

## D10. A network failure during the page-load session check retries instead of signing out
- What: only a 401 from /auth/refresh ends a session. During the check on page load, a network
  error, 5xx or restart keeps the user "checking" and retries after 1, 2, 4, 8, then every 15 s
  (at once when the browser comes back online), with a "Cannot reach the server" note.
- Why: found by the offline e2e test. A blip while the refresh was in flight sent users with a
  valid cookie to the login page.
- Alternative: give up after N tries and show the login page. Rejected: signing in cannot work
  while the server is unreachable either, and the retry note says what is happening.

## D11. OpenAPI describes the real error shape and statuses
- What: `app/core/openapi.py` replaces FastAPI's default 422 schema with the app's one error shape
  (`ErrorResponse`) and declares 400/413/422/429/500 everywhere, 401/403/404 on signed-in
  operations, 409 on signed-in writes. Frontend types regenerated (scripts/gen-api.ps1).
- Why: Schemathesis found 102 schema violations and ~300 undocumented statuses, all caused by the
  spec, not by the API. No API behaviour changed.

## D12. Double-submit guard on chosen actions, not a global scheduler change
- What: `useSingleFlight` (a ref set in the click) on the actions where a second request would
  create a duplicate or a confusing error: event and user forms, demo shortage, job start, and
  "Mark all read" (both places).
- Why: switching React Query's notify scheduler to microtasks fixed double clicks everywhere but
  changed callback ordering (a test lost an error toast when the card unmounted first). Server
  state machines already reject repeated claims, decisions and requests (409 / idempotent).

## D13. /dev/kit is exempt from the phone layout and skeleton checks
- The design kit is built only for e2e (VITE_DEV_KIT=true), shows loading states on purpose and
  has oversized demo visuals. Every product route is checked at 390 and 1440 px.

## D14. Signup approval and rejection lock the user row
- What: `SELECT ... FOR UPDATE` on the user in update/approve and reject.
- Why: reproduced on Postgres: two admins approving and rejecting the same pending signup at once
  both succeeded, leaving an active-and-rejected account with two contradictory audit entries.

## D15. Database outage is a 503, not a 500
- What: SQLAlchemy `OperationalError` (database unreachable or restarting) answers
  503 `database_unavailable` with `Retry-After: 5`; the frontend's reconnect banner treats 502,
  503, 504 and network errors as "server unreachable", pings /health and refetches when back.
- Liveness vs readiness: `/health` = the process answers (no database); `/system/status` = the
  database, migrations and bootstrap are ready. Docker's healthcheck uses liveness.

## D16. nginx re-resolves the backend name
- What: `resolver 127.0.0.11 valid=10s` and a variable `proxy_pass`.
- Why: reproduced: with the original config, recreating the backend container with a new IP
  left nginx answering 502 until nginx itself restarted. Now it follows within 10 s.

## D17. Postgres ends sessions of vanished clients
- What: `client_connection_check_interval=5s`, TCP keepalives 20 s / 5 s / 3 probes.
- Why: reproduced: killing the backend during the first seeding left its COPY session
  "active" for 10+ minutes; the restarted bootstrap waited on its locks and never got ready.

## D18. No statement_timeout on API connections
- The API process also runs admin background jobs (retraining) on the same engine; a timeout
  could kill those. No request-path query took more than ~70 ms under fuzzing or 50-user load.

# Decisions (live clock upgrade)

## L1. Two clock modes; live is the default
- What: `CLOCK_MODE=live` (default: run.bat, run.sh, local, judges) follows the real time in
  Asia/Dhaka; `CLOCK_MODE=fixed` keeps the frozen SIM_NOW timeline. pytest sets fixed by default
  (`tests/conftest.py`); the live tests opt in. One server clock (`app/core/clock.py`) for all roles.
- Why: the fixed path must keep reproducing the benchmark; live is what users should see.
- Alternative: live only. Rejected: benchmarks and most tests need a frozen, reproducible clock.

## L2. Fixed generator untouched; a separate live engine
- What: `ml/data_gen/live*.py` re-implements the same world per calendar date (randomness
  seeded by (seed, purpose, date[, agent])); the fixed generator files are not changed.
- Why: fixed mode must stay bit-identical. Refactoring the fixed code risks tiny float changes.
- Alternative: one parameterised generator. Rejected for that risk; cost is ~250 lines of
  deliberate duplication of formulas (constants are shared, not copied).

## L3. Whole-BDT balances in the live engine
- What: targets and balances are rounded to whole BDT inside the live engine.
- Why: continuing from the balances stored in the database then gives exactly the values of an
  uninterrupted run (tested), so catch-up is deterministic.

## L4. Committed model artifacts are reused
- What: no retraining for live mode. Features are hour, weekday, day of month, events,
  weather, agent attributes and scale-normalised lags; none is an absolute date or trend.
- Why: verified in Phase 1. Caveat: training saw Jan-May weather only (trees clamp unseen
  monsoon values). Retrain jobs and the bootstrap train step refuse to run in live mode (they read
  the fixed timeline); the message says to use `CLOCK_MODE=fixed`.

## L5. No future rows; calendar known ahead, weather not stored ahead
- What: transactions up to the current hour, balances at its top. Calendar events (salary days,
  hat days, holidays) are written 3 days ahead; weather rows only up to today. The forecast reads
  the next days' weather from the deterministic synthetic outlook (`forecast.weather_outlook`,
  in memory, never stored), as the fixed timeline's model read the stored future weather.
- Why: "never write future data". Calendar facts are known in advance in reality; the outlook is
  a perfect synthetic weather forecast, the same assumption the model was trained and benchmarked
  with.

## L6. Catch-up vs regenerate
- What: on start and every tick, missing hours are appended in batches of 24 h, one transaction
  each (`DATA_CATCHUP_BATCH_H`). A gap above 14 days (`DATA_REGEN_GAP_DAYS`), another seed, data
  version or mode, or data ahead of the clock (the clock moved back) rebuilds the 120-day window.
- Why: bounded transactions are safe to interrupt; very long gaps are faster to rebuild.

## L7. Hourly tick on the leader; help trigger woken after it
- What: `app/services/data_scheduler.py` checks every 30 s (`DATA_TICK_INTERVAL_S`); the process
  holding its advisory lock runs the tick. Every data writer also takes a transaction-level
  advisory lock. After a tick it wakes its process's help scheduler loop.
- Why: same leader pattern as the help scheduler. Limit: if another process is the help leader,
  the trigger reads the fresh caches on its own next turn (at most HELP_TRIGGER_INTERVAL_S later).

## L8. Tick budget: threaded TreeSHAP in live mode, daily backtest
- What: explanations use all cores in live mode (fixed keeps one thread; per-row SHAP values do
  not depend on the thread count). The holdout impact backtest reruns once a day (its key holds the
  holdout start), not every hour. Live ticks read only the history the features use (4-5 weeks).
- Why: a full precompute took ~126 s; the hourly budget is 60 s.

## L9. Demo story anchored at the data hour
- What: on a fresh window the story agent (AGT-0001) gets a top-up at the current hour that runs
  out at 15:40 on the next feasible afternoon (today, or tomorrow when today is too close).
  When no salary/wage/Eid day explains it, a labelled event "Demo event: Mirpur factory wage day
  (synthetic)" is added to the world and the events table (admin can edit it). In DEMO_MODE a new
  story is anchored whenever none lies ahead (only the future is shaped; never today's past hours).
  AGT-0005 gets night structuring around a fresh anchor; re-anchors add an episode only when the
  last one ended 21+ days ago (an episode every day would become the agent's normal).
- Why: the story must work whenever someone opens the app, without pretending a holiday.

## L10. Holidays from `backend/data/holidays_bd.yaml`
- What: fixed-date national days (21 Feb, 26 Mar, 14 Apr, 1 May, 16 Dec, 25 Dec) 2025-2028 are
  `fixed_date`. Eid-ul-Fitr, Eid-ul-Adha, Ashura and Eid-e-Miladunnabi are computed with the
  tabular Hijri calendar and marked `unverified` (they appear on the Events page with
  "(date unverified)"). Not included: Durga Puja, Buddha Purnima, Janmashtami, Shab-e-Barat,
  Shab-e-Qadr, Jumatul Bidah, 17 Mar and 15 Aug (status changed in 2024-25).
- Why: never invent holiday dates. The file is the world; the Events page edits what the forecast
  knows. Parsed with PyYAML, which `uvicorn[standard]` already installs (no new dependency).

## L11. Anomaly flags keyed by agent, not window start
- What: an open flag is "known" per agent; a reviewed flag whose window overlaps the current one
  suppresses a re-flag. Fixed mode has one window, so its behaviour is unchanged.
- Why: the live window moves every hour; keyed by window start, every tick would re-notify.

## L12. Help trigger subtracts the forecast lag
- What: live mode subtracts the minutes since the origin hour from the stock-out shown on a help
  request (`clock.lag_h`, 0 in fixed mode).

## L13. Drift on live data uses a backcast
- What: live mode scores the model run at origin - 72 h on the history before it against the
  demand logged since (there is no data after now).

## L14. Verification tooling
- What: `docker-compose.verify.yml` passes `CLOCK_MODE` and `CLOCK_SHIFT_H` through;
  `scripts/check.ps1|.sh` use `COMPOSE_PROJECT_NAME` as the image prefix, so -Up/-E2E can target
  the isolated stack. `CLOCK_SHIFT_H` is for verification only.

# Decisions (ML upgrade)

All numbers: synthetic data, fixed clock, seed 42 (docs/ML_UPGRADE_RESULTS.md).

## ML1. Train / validation / blind test split
- What: train targets before 2026-04-07; validation 04-07..04-20; blind test = the last 14 days
  (04-21..05-04, unchanged holdout). `ml/training/splits.py` checks every row set (leakage
  tests in `tests/test_ml_split.py`). Served forecast boosters are trained on the train period
  only and never refitted on validation, so the conformal offsets stay valid.
- Why: hyper-parameters, thresholds and calibration had no clean place to be chosen.
- Alternative: refit on train + validation after selection (more data). Rejected: the
  validation residuals would no longer be out-of-sample for the conformal calibration. Cost:
  14 fewer training days; blind MAE still improved.

## ML2. Forecast selection grid fixed before looking; q50 kept from 1.0.0
- What: per target, q10 and q90 pick leaves {31, 63} x rounds {150, 300, 450, 600} by validation
  pinball (winners at the 600-round edge; the grid was not widened after the blind test was
  seen). q50 is the booster TreeSHAP explains on every live tick, so it is capped at 31 leaves x
  300 rounds (the 1.0 size). Inside that cap the train-period q50 had a higher blind MAE than
  the old q50 (2,227 vs 2,211 cash-out), so the served q50 is the UNCHANGED 1.0.0 booster
  (trained through 2026-04-20; its validation metrics are in-sample, marked in the manifest).
  Served version lgbq-1.1.0-7636a2e5 = old q50 + new train-period q10 / q90 + conformal.
- Why: the uncapped q50 (63 x 600) made TreeSHAP 6.6x slower (11.9 s vs 1.8 s per target) and
  the live tick ~87 s against its 60 s budget. Rule "keep the old behaviour when a metric gets
  worse" then keeps the old point forecast. Bands stay valid: conformal uses q10 / q90 scores
  only, and keeping q10 <= q50 <= q90 can only widen a band.
- Alternative: uncapped q50 (blind MAE 2,207 / 2,145, better) - rejected for the tick budget.
## ML3. Anomaly contamination from rolling validation folds
- What: 4 blocks of 14 days ending at the holdout start; forests fitted on windows before each
  block; max pooled F1 over a fixed grid (0.25%..3%); no positive -> 0.5%. Chosen 0.25% (grid
  edge; 7 positive windows). Blind: window precision 0.94, recall 0.53 (old, chosen with the
  holdout visible: 0.96 / 0.73); agent level 0.80 / 0.80 both.
- Why kept although recall is lower: picking the old share because it scores better on the
  holdout would put the leak back. The gate test (>= 0.5) still passes, narrowly.

## ML4. Conformal bands: closed-hour cell, calibration on by default
- What: CQR per tail, Mondrian cells closed (raw q90 < 1 BDT) x tier x area x horizon bucket.
  The first version (no closed cell) gave all-zero offsets on validation because tied zero
  scores pinned the quantile; the cell was added and the candidate recalibrated (same
  boosters), then the blind test scored. Setting `FORECAST_CONFORMAL` (default true).
- Why on: pinball improves for both targets and the under-covering cash-out groups move to
  ~0.79-0.81. Cash-in open-hour coverage ends at 0.85 (lower tail cannot rise above the many
  exact zeros) - reported, not hidden.

## ML5. Stockout decision input stays the old independent method
- What: `STOCKOUT_METHOD=independent` (default). The joint method (estimated copula per segment,
  coupled floats) is better calibrated (Brier 0.035 vs 0.044) with the same AUC (0.970 vs
  0.971), but at the unchanged amber cut 0.20 its recall of realised stockouts is 0.89 vs 0.98.
- Why: user rule "if a change makes a metric worse, keep the old behaviour as default"; missed
  stockouts are the costly error. Next step: re-tune the cut on the validation period, then
  switch. The refill-aware view (joint paths + own refill habit) is stored beside the decision
  input as an extra field (`refill_aware` in GET /agents/{id}/stockout), never used to decide.

## ML6. Refills detected from the transaction ledger
- What: a refill = snapshot cash not explained by the previous snapshot and that hour's logged
  transactions (19,365 found); the old rule "cash + e-money jumped" finds 602, because a refill
  resets both floats to targets and the total often does not move.
- Note: the anomaly feature `refills_peer_z` still uses the old rule (not changed here; open).

## ML7. Helper acceptance model is opt-in
- What: `HELP_RANK_MODEL=rules`, `HELP_WAVE_SIZING=false` by default. In the simulation the learned
  order did not beat the existing rule score (acceptance 0.276 vs 0.278, covered 0.341 vs
  0.348), and learned wave size (with the rule order) cut asks 7% and raised coverage
  slightly but made time to cover longer (5.82 vs 5.63 min).
- Why: every number comes from simulated behaviour, and each option worsens at least one metric.
  The model never adds or removes a helper; wave size never exceeds the rule's cap.
- Platt recalibration was fitted on validation and kept although blind ECE was better without
  it (0.014 vs 0.028); dropping it after seeing the blind test would be selection on the test.

## ML8. Split matching (S1) is selectable, assignment stays default
- What: `SWAP_MATCHING=assignment` (default) | `flow` (MILP via scipy HiGHS, 10 s limit;
  per-donor cap 2 receivers, per-receiver cap 3 donors, travel time = km / 15 km/h within the
  deadline). Final replay: flow covers 12.5% of the needed BDT vs 8.2%, same service (75
  stockout hours), 23 fewer van trips, but 35% more hand-over km and up to 2 receivers per
  donor; one earlier run (larger q50) had 78 vs 75 stockout hours.
- Why default unchanged: travel km and donor load get worse, and the service gain is not stable
  across runs.
- Also fixed: the replay entered an agent short of both floats twice as a cash swap receiver
  (once with its e-money amount); regression test in tests/test_impact_realism.py.

## ML9. Realism (S4) and drift advice (S5) are readings, not behaviour changes
- What: imperfect delivery (10% of physical deliveries arrive empty, 25% two hours late) and
  full action costs are a benchmark sensitivity (`app/services/impact_realism.py`); the stored
  impact backtest is unchanged. The drift report adds band coverage vs the held-out coverage
  and `retrain.suggested` with reasons; nothing retrains by itself.

## F1. Judges' default clock is live, fixed stays as fallback (LC-1)
- What: `CLOCK_MODE=live` stays the default for run.bat / run.sh. The scripted demo story
  (AGT-0001 shortage, AGT-0005 anomaly) must be guaranteed in live mode (fix phase 1D).
  `CLOCK_MODE=fixed` remains a documented one-line fallback that reproduces the benchmark.
- Why: a fixed April 2026 clock makes every date look stale to a judge (report finding F-001);
  live mode is only safe once the demo story re-anchors reliably at any start time.
- Alternative: fixed as default. Rejected: reproducible, but the app looks frozen in the past.

## F2. Fast pytest tier kept as is; shared risk cache becomes a session template (ML-3)
- What: no test moved to `@pytest.mark.slow`. The measured fast tier has no test over 7 s and none
  trains models or loads the full synthetic set. The `scored` fixture (test_llm_api, reused by
  copilot, prompt-injection and query-count suites) now copies a session-scoped `scored_template`
  (conftest) instead of re-running `risk.precompute` for every test.
- Why: setup was 108 s of ~200 s in total, spread over ~800 tests. CLAUDE.md allows `slow` only for
  training, the full synthetic set and the ML gate; moving others would hide coverage.
- Alternative: mark the four LLM suites slow. Rejected: they are fast API tests and guard the
  numbers guard and prompt-injection rules.

## F3. pytest step limit is configurable, default 300 s (LC-8)
- What: `check.ps1 -PytestTimeout <sec>`, else env `CHECK_PYTEST_TIMEOUT`, else 300 s for the fast
  tier. `-Slow` / `-Full` keep 1200 s unless the flag or env is set. `check.sh` reads the env var.
- Why: the fast tier took 215-352 s on a loaded PC and hit the old fixed 240 s limit.
- Alternative: raise the fixed value only. Rejected: hides the next regression and does not help
  slower judge PCs.

## F4. PyYAML declared and pinned; verify volume name configurable (ML-12, LC-11)
- What: `PyYAML==6.0.3` in backend/requirements.txt (the version already in the image).
  `docker-compose.verify.yml` names the Postgres volume `${VERIFY_PGDATA:-agentpulse-verify_pgdata}`,
  so a fresh-database test uses a new volume without touching the existing ones.
- Why: `live_calendar.py` imports `yaml` for the holiday file; it only worked because
  `uvicorn[standard]` pulls PyYAML in. A change there would break a clean build. No new package
  is installed: the pin makes an existing one explicit.
- Alternative: parse the holiday file as JSON and drop the dependency. Rejected: the file is
  hand-edited (comments) and already committed as YAML.

## F5. Daily impact backtest runs as its own background job, not inside the tick (ML-2, LC-2)
- What: `app/services/backtest_job.py`: own leader lock, looks every 60 s and right after each
  tick, reruns `backtest.precompute` only when its key changed (a new day), own 180 s budget,
  status in `system_meta.backtest_job_status`, shown as one line on the admin Data clock card
  (`GET /admin/clock` field `backtest`, additive). It does not start while a tick runs. A failed
  or self-skipped run is retried when the key changes or after one hour, not every poll. The
  hourly tick calls `pipeline.precompute(backtest_too=False)`; bootstrap and the admin
  "generate data" job still run the backtest inline (unchanged, fixed mode unchanged).
- Why: the backtest (42-75 s) made the first tick after midnight 74.5 s, over the 60 s budget.
- Alternative: keep it in the tick and only speed it up. Rejected: it would still be the
  largest stage and the tick budget would depend on it.

## F6. Non-overlap guard for the hourly tick (LC-2)
- What: `data_clock.tick_guard()` holds a second lock (Postgres session advisory lock
  7_310_455_004; file lock on SQLite) for the whole tick. A tick that finds it taken is skipped,
  logged as a warning and counted (`skipped_ticks`, `last_skipped_at` in the clock status and
  in `GET /admin/clock`, additive).
- Why: the leader lock alone does not stop overlap when a leader loses its connection (and so
  its lock) while its tick is still running; a new leader would start a second tick.
- Alternative: make the next tick wait. Rejected: queued ticks pile up when ticks are slow; the
  next tick catches up all missed hours anyway.

## F7. Risk stage: threads for the projections, vectorised refill history (ML-2)
- What: live ticks run the per-agent stock-out projections on 4 threads (each agent has its own
  seeded generators, so rows are identical; fixed mode keeps one thread). On Postgres the 42-day
  refill-aware history is read with float/epoch casts in SQL and scattered with numpy
  (`app/services/risk_history.py`); SQLite keeps the old row loop.
- Why: risk was the largest tick stage (15 s). Projections 9.9 -> 3.3 s (isolated), history
  3.7 -> 2.2 s. Old vs new rows compared on the verify Postgres: 600 stock-out and 1,800 risk
  rows identical.
- Alternative: cache the refill habits per day. Rejected: habits slide every hour, so a daily
  cache changes live results; the history load, not the habit maths (0.01 s), was the cost.
  8 or 12 threads were slower than 4 on this PC.

## F8. No-key label is a new field; replay runs on the fixed clock only (LC-3)
- What: `LlmText.no_api_key` (true when template wording is served because no key is set, never
  for `LLM_PROVIDER=template` chosen on purpose, a failed live call, or a copilot refusal) and
  `LlmStatus.no_api_key` / `replay_skipped` ("live_clock"). The UI chip reads "Template wording
  (no API key)" in bn/en. In `auto` mode recorded replay is used only when `CLOCK_MODE=fixed`;
  an explicit `LLM_PROVIDER=replay` is still honoured. Templates gained number-free next-step
  sentences (briefings, anomaly narrative).
- Why: the recorded answers belong to the scripted fixed-clock scenario, so on the live clock they
  can only miss (or mislead); a visitor with no key should be told that the wording is a template.
  All changes are additive to the API, the numbers guard is unchanged.
- Alternative: reuse the existing `fallback_reason: "not_configured"`. Rejected: existing tests
  and clients read `fallback_reason is None` for template mode by configuration, so changing it
  would be a contract change.

## V1. OR-Tools 9.15.6755 for van routing, with a pure-Python fallback (F14)
- What: `ortools==9.15.6755` (exact pin, newest wheel for python:3.11-slim on 2026-10-06) solves
  the capacitated van routing with soft deadlines and optional stops
  (`app/rules/van_routing/solver.py`). It adds pandas 3.0.6, protobuf 6.33.6, absl-py and
  immutabledict to the image (about +129 s on the first build of the verify images). If the
  import fails or no solution is found, nearest-neighbour + 2-opt runs instead, labelled
  `solver: fallback` with a note (`ortools_unavailable` / `ortools_no_solution`).
- Why: the spec asks for capacity, soft time windows and droppable stops in one BDT objective;
  scipy (already present) has no routing solver. The fallback keeps the feature working without it.
- Alternative: a hand-written heuristic only. Rejected: weaker plans, and the evaluation
  (policy C vs D) needs a real solver for a fair comparison.

## V2. Determinism from a fixed solution budget, not the time limit
- What: OR-Tools runs one search thread with a solution limit (`VAN_SOLUTION_LIMIT`, 300) and
  native transit matrices (no Python callbacks). The time limit (`VAN_TIME_LIMIT_S`, 10 s; 85% for
  the search, the rest for repair and costs) is a safety net only; when it is what stopped the
  search, the plan says `stopped_by: time_limit`.
- Why: a time-limited local search gives different plans on fast and slow machines; a fixed
  budget gives the same plan for the same input anywhere. With Python callbacks the budget took
  over 5 s for 30 stops; native matrices need about 0.6 s (probe on seeded test instances, not on
  held-out data).
- Alternative: time limit only. Rejected: not reproducible.

## V3. van_stops gets plan_id; route_id may be NULL; routes keep their legs
- What: `van_stops.plan_id` (not in spec section 7) and nullable `route_id`, `seq`, `eta_*`:
  dropped stops (any reason, including `swap_suggested`) belong to the plan but to no route.
  `van_routes.legs` (JSON) stores every leg's km, minutes and source (`road_cache`/`estimate`);
  `van_stops.details` keeps the numbers behind each stop (lost value per hour, deadline hours,
  arrival, insertion cost vs skip penalty). Plan statuses: pending, approved, rejected,
  superseded (a newer plan for the same distributor replaces a pending one).
- Why: every number must be traceable, and a drop reason needs a row without a route.
- Alternative: dropped stops in a JSON column of the plan. Rejected: not queryable, no ids for
  the stop actions.

## V4. Lost value, skip penalty and drop reasons
- What: lost value per stockout hour = the agent's forecast cash-out per hour (q50), the impact
  model's unit (turned-away cash-out). Late arrival costs lost value x hours after the expected
  stockout (soft window); skipping costs it until the horizon. A stop is dropped with
  `cost_gt_value` when its cheapest feasible insertion costs more than skipping it, with
  `capacity` when no van can take it (cash or shift time), and with `swap_suggested` when a
  pending/approved swap covers it. A repair pass after the solver inserts any dropped stop that a
  single insertion makes worth serving. Hard-deadline mode (evaluation policy C only) uses
  `deadline_missed`. No split deliveries.
- Why: one BDT objective, as the spec asks; the stored insertion cost vs skip penalty makes every
  drop explainable.
- Alternative: the fee lost per turned-away cash-out (1.85%). Rejected: the impact model's
  value_lost_bdt counts the full turned-away amount, and the two numbers must agree.

## V5. V1 scope: core only
- What: V1 ships the BDT objective, soft windows, drop reasons, the road cache with estimate
  fallback, policies A-D on held-out days (one seed, oracle needs), and the API: create, list,
  detail, decision, stop delivered, narrative. Moved to V3: fairness bounds, near-optimal seeded
  choice, freeze/lock/include/exclude, red q90 / amber q50 amounts (V1 uses the rebalance amount,
  pessimistic q90, labelled `source_quantile: q90`), ETA ranges (V1: `eta_lo == eta_hi`),
  stockout-before-arrival probability (NULL), LLM wording, `/impact/van-comparison`, >= 5 seeds and
  sensitivity. Section 11 tests for fairness bounds come with V3.
- Why: the approved V1 plan.
- Alternative: all of section 6 at once. Rejected: V3 owns those parts.

## V6. Admins read van plans; only distributors act
- What: `GET /distributor/van-plans`, `GET .../{id}` and `GET .../{id}/narrative` allow
  distributor (own plans) and admin (all, optional `distributor_id` filter). Create, decision and
  stop actions are distributor-only (admin 403). Agents get 403 everywhere: they never see route
  details. Unknown and out-of-scope ids both return 403.
- Why: the user asked for admin read-only access (oversight, audit); the narrative is a read of
  the same plan, so it follows the read rule.
- Alternative: distributor-only (the spec). Changed at the user's request.

## V7. Van narrative is template-only in V1, not an LLM intent yet
- What: `app/llm/van_template.py` renders bn/en text from an evidence pack of stored plan numbers;
  the API labels it `generated_by: template`. No LLM call, so nothing goes to `llm_call_log`.
- Why: a new LLM intent needs a new `llm_intent` enum value (a Postgres enum migration) and the
  guard wiring, which V3 does; V1 keeps language and numbers deterministic.
- Alternative: route through the LLM service now. Deferred to V3.

## V8. Plan cache by input hash
- What: the input hash covers the distributor, forecast origin, the current wall-clock hour, the
  full van config, every candidate (agent, recommendation, amount, deadline, lost value, day
  factor, swap cover), the road cache version and the rules version. A request with the hash of
  a pending plan returns that plan (`reused: true`) without solving.
- Why: re-plan only on a meaningful input change (spec section 4); including the hour keeps the
  departure time honest.
- Alternative: always re-solve. Rejected: wasted solver time and a new plan id on every click.

## V9. The plan response carries the depot (additive field)
- What: `VanPlanOut.depot` = {code, name, lat, lng}, read from `distributors.hub_lat/hub_lng`.
- Why: the map and the "separate trips" view must draw the depot, and legs only name it by key.
  Without the field the frontend could only guess it from a road polyline, which is missing when
  distances are estimated.
- Alternative: derive the depot from the first polyline point. Rejected: it fails in estimate mode.

## V10. One API module with Zod for van plans
- What: `frontend/src/api/vanPlans.ts` holds the Zod schemas, the calls and the TanStack Query
  hooks. Every response is parsed, so a contract drift shows as an error state, never as NaN.
- Why: the V2 prompt asks for Zod; the van endpoints are not in `schema.d.ts` yet.
- Alternative: split into `api/services` and `api/hooks` like the older modules. Not done: three
  small files for one feature added no value.

## V11. Route colours are tokens, and the marker number carries the identity
- What: `--route-1..6` and `--route-ink` in `tokens.css` (light and dark), none of them red, amber
  or green. Each stop marker shows its sequence number, the legend and the stop list name the van.
- Why: DESIGN.md: route colours, not risk colours, and never colour alone.
- Alternative: reuse the chart or float colours. Rejected: cash violet and e-money cyan already mean
  a float type.

## V12. V2 shows only what the backend already provides
- What: no lock, include or exclude controls (those endpoints are not built), no per-stop
  "stockout before arrival" flag (the field is null until V3, and the limit is not in the response),
  no delivered feedback form. The stop list shows the probability when it is present.
- Why: the page must not invent numbers or buttons that do nothing.
- Alternative: a client-side limit such as 50 percent. Rejected: an invented threshold.

## V13. Controls re-solve after a pause; approval is a note dialog
- What: changing vans, capacity or cash cap posts a new plan 600 ms after the last change; the old
  plan stays on screen, dimmed. Approve and reject are two buttons enabled by a note of 5+ characters.
- Why: the spec says controls re-solve on change; one solve per slider tick would flood the solver.
  Swaps use a hold-to-approve gesture because they move a counterparty; a van plan is advisory.
- Alternative: re-solve on every change, or HoldToApprove. Not done.

## V14. Van wording is its own i18n namespace
- What: `i18n/vanRoutes.{en,bn}.json`, registered by `i18n/vanRoutes.ts` and bundled with the page
  chunk, like `helpAdmin`. Only `page.vanRoutes` (the nav title) stays in `en.json` / `bn.json`.
- Why: the first version put about 190 lines in the main dictionaries and the `/login` first load
  went from under the 250 KB budget to 253.6 KB gzip (the e2e budget test failed).
- Alternative: raise the budget. Rejected: the budget is a gate, not a suggestion.

## V15. The van page must not grow the /login first load (250 KB gzip budget)
- What: measured on the isolated stack, in bytes of gzip JS (budget 256,000). Tree without the van
  feature: 255,690 (310 B of headroom; the earlier 249.4 KB measure had shrunk because of other
  uncommitted work). First van build: 259,700 (253.6 KB). Moves that fixed it: van wording in its own
  namespace (V14, about -1.7 KB); `api/vanPlans.ts` imports `zod/v3`, a separate module graph that
  stays in the lazy page chunk (about -1.8 KB; the classic build made the shared zod chunk grow, and
  `zod/mini` was worse at 252.7 KB); van query keys in `vanPlans.ts` instead of `keys.ts`; the page
  route inlined in `router.tsx`; no `prediction` flag (the page shows the model version and plan time
  itself). Result: 255,992 bytes, 8 B under the budget.
- Why: the e2e test `first load of /login ships under 250 KB` is a gate.
- Alternative: raise the budget, or leave Zod out. Both rejected. What the feature still costs in the
  first load is the nav item (the Truck icon is about 150 B gzip) and the route entry.
- Follow-up: headroom is now almost zero for any later first-load change.

## V16. Forecast-aware amount and deadline (V3)
- What: red agents keep the rebalance amount (q90 drain vs q10 inflow, `source_quantile: q90`);
  amber agents get the same rule on the median path (q50 vs q50, `q50`), or the q90 amount when
  the median path needs nothing. The deadline is the first hour the agent's P(stockout) curve
  (`stockout_predictions.prob_by_hour`) reaches `VAN_STOCKOUT_P_LIMIT` (0.3), else the
  recommendation's stockout time; each stop says which (`deadline_rule`).
- Why: spec section 3 (red q90, amber q50; deadline from a probability limit).
- Alternative: keep the V1 rebalance amount for everyone. Rejected: amber agents would be loaded
  for the pessimistic path the risk level says is unlikely.

## V17. ETA range on driving time; stockout before arrival at the late ETA
- What: `eta_lo/eta_hi` = driving time x 0.85 / x 1.3 plus the stop minutes (`robust.py`). The
  stockout chance is read from the agent's curve at the late ETA (plus the live-mode lag); a
  stop is flagged when it is above the same 0.3 limit. No curve: probability and flag stay null.
- Why: spec section 4 (robustness); the late end is the safe reading for a cash shortage.
- Alternative: a symmetric +/- band. Rejected: road delays are skewed late.

## V18. Fairness guard per area: hard max wait, min service rate by insertion
- What: groups are the area (urban / peri_urban / rural). Max wait is a hard bound on every
  arrival (cost.fits and the OR-Tools time window). The service bound (0.5) is enforced after the
  search: the cheapest dropped stop of a short group is inserted until the group meets the bound
  or no van can take one (reported in `fairness_short`). Stops added this way are marked
  `fairness_forced`. Policy D (full model) includes the guard; C does not.
- Why: a soft penalty would let the BDT objective trade fairness away silently; insertion keeps
  every number traceable.
- Alternative: groups by area x tier (9 groups). Rejected: most groups would hold one agent per
  plan, so a rate bound would mean "serve everyone".

## V19. Near-optimal seeded pick from local variants
- What: candidates are the solved plan, each route reversed and each pair of neighbouring stops
  swapped; any feasible one within 3% of the best candidate may be picked with
  `random.Random(seed)`. Plans: seed = first 8 hex digits of the input hash (same inputs, same
  pick). Evaluation: seed x 1000 + instance index. The plan reports `choice` as "k/n".
- Why: spec section 4 (safety); re-running OR-Tools with other strategies would multiply the
  solve time.
- Alternative: no randomisation. Rejected by the spec.

## V20. Pins and freeze: must-serve as a very high drop price
- What: lock = must serve on the same van, include = must serve, exclude = left out with the new
  drop reason `excluded`; a pin re-solves the plan as a new pending plan (the old one superseded),
  audited as `van_plan.stop_<action>` on the old plan with `new_plan_id`. Pins are stored in
  `params.pins` and are part of the input hash. "Must serve" costs 100 M BDT in the search only;
  a stop no van can take is still dropped (`capacity`). Frozen = open stops of the latest approved
  plan that their van reaches within `VAN_FREEZE_MIN` (30 min): locked to that van, overriding
  pins. Route index k is now always van k + 1 (empty vans keep their number).
- Why: a hard constraint would make the whole plan infeasible over one stop.
- Alternative: hard mandatory nodes. Rejected for that reason.
- Limit: the new plan still starts every van at the depot; a frozen stop is re-timed from there.

## V21. Van narrative is an LLM intent (migration 0025)
- What: `llm_intent` gains `van_narrative` (Postgres only; SQLite stores text). The narrative goes
  through `app/llm/service.generate` with the van template as the draft: numbers guard, action and
  echo guards, cache, `llm_call_log`, template fallback. `VanNarrativeOut` gains
  `fallback_reason` and `no_api_key` (additive). The admin LLM log shows the new intent with a
  readable fallback label; its filter list is unchanged.
- Why: spec section 6. Adding the intent label to the main dictionaries would break the /login
  first-load budget (V15).
- Alternative: keep template-only. Rejected (V7 deferred it to V3).

## V22. Van evaluation: oracle needs, 5 seeds on estimate distances, sensitivity on seed 42
- What: `python -m ml.van.evaluate` runs policies A-D on held-out days of seeds 42-46 with
  estimate distances (each seed places agents differently; the road cache only knows seed 42),
  reports mean and 95% t-interval over seeds, paired D-C and D-A differences with a computed
  verdict, sensitivity (road factor 1.2 / 1.5, fuel 20 / 30 BDT per km, delivery reliability
  0.90 / 0.95 replayed with the same failed agents for every policy) and a seed-42 road-cache
  reference. Written to `ml/van/van_v3_eval.json`, served by `GET /api/v1/impact/van-comparison`
  (distributor and admin). V1's single-seed file and test are unchanged.
- Why: the forecaster only runs on the seeded database (its panel is loaded from the DB), so other
  seeds cannot be forecast; oracle needs isolate routing quality, as in V1.
- Alternative: a forecast-aware backtest on seed 42 only. Not done: it would not give 5 seeds.

## V23. Two V1 assertions changed to V3 behaviour
- What: `test_van_plans_api.py` asserted `eta_lo == eta_hi` and `source_quantile == "q90"` for
  every stop: V1 scope markers (V5). Now: `eta_lo < eta_hi` for every planned stop, red agents
  `q90`, others `q50` or `q90`; the test also checks the fairness report and the stockout limit.
- Why: the spec asks for exactly these changes; the new assertions are stricter where they apply.
- Alternative: keep V1 behaviour. Rejected: the spec's should stage replaces it.


## F9. Fast-tier speed-up: shared fixtures and shared routes in conftest (F3 test health)
- What: (1) `anomaly_artifacts`, `flagged_template`, `flagged` moved from `test_anomalies_api.py`
  to `tests/conftest.py`; the two LLM suites no longer import them. (2) A session-wide autouse
  fixture `shared_routes` makes `FastAPI.include_router` reuse the APIRoute objects it already
  built for the same router and prefix, so `create_app()` (one per `client` fixture) drops from
  ~90 ms to ~28 ms. No test was deleted, loosened or moved to `slow`; no dependency added.
- Why: a session fixture imported into other test modules is built once per module, so the
  Isolation Forest selection (~25-45 s) ran three times. Routes carry no per-app state here
  (no test uses `dependency_overrides`), so sharing them is safe.
- Alternative: pytest-xdist (new dependency, every worker rebuilds the session templates);
  a smaller anomaly grid in tests (would weaken what the test covers); a shared TestClient
  portal (saves ~5 ms per request, changes event-loop lifetime). All rejected.

## V24. Van map: cash status as a ring and badge, route colour kept as the fill (V4 polish)
- What: each served stop marker keeps its van colour as the fill and gets a ring for cash status:
  red ring plus a "!" badge when the backend flags a stockout before the van arrives
  (`stockout_risk_flag`) or the stop is late for its deadline (`late_h > 0`); green ring otherwise.
  Skipped stops keep the neutral hollow "×". The legend, the marker name and the stop card say the
  status in words. No new threshold: the rule only reads the two fields the backend already sends.
- Why: the request asked for red/green stops; VAN_ROUTING_SPEC section 9 asks for route colours,
  not risk colours, and DESIGN.md asks for colour + icon + word. A ring keeps both readable.
- Alternative: fill markers red/green. Rejected: the van a stop belongs to would be lost on the map.
- Note: the van carries cash only (spec section 1); the card says "Cash to bring". There is no
  e-money amount in the plan, so none is shown.

## V25. Van map: sequential navigation view (V5)
- What: (1) chevron arrows along every route leg, from a signed-distance image built in code
  (`routeArrows.ts`, no sprite or glyph fetch) so the travel order shows on the lines; route lines
  get thicker with zoom. (2) The stop list is now an itinerary per van: depot, the stored leg (km,
  time, "estimated" when not from the road cache) into each stop, the drive back, the van cost, and
  a savings line from the same numbers as the savings panel. (3) The stop card adds a delivery
  instruction, the drive in and where the van goes next. (4) The van map gets the control room's
  opt-in street-tile toggle (same persisted choice); tiles are now CARTO "@2x" for sharp labels.
- Why: the request asked for Google-Maps-style sequential navigation and crisp tiles. CLAUDE.md
  requires the app to run offline after the first build, so street tiles stay off by default and
  the bundled offline map is unchanged. A missing leg shows "Drive not stored", never a made-up km.
- Alternative: online tiles on by default (breaks offline judges' machines); a CARTO vector style
  (needs remote glyphs and sprites, same offline problem); a maplibre Popup at the marker instead of
  the existing stop card (the card already sits over the map and the camera offsets the stop above
  it; a second popup would duplicate it). Per-stop savings were not added: the plan only stores
  savings for the whole plan, so per-stop numbers would be invented.
