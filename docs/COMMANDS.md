# Commands

All commands run from the project root (`D:\Git\AI_Hackathon_DIU`). Only Docker Desktop is needed;
never run npm / tsc / pytest on the host.

## Run the app

| What | Windows | Linux / Mac |
|---|---|---|
| Start (build if needed, wait until ready) | `run.bat` | `./run.sh` |
| Start with a fresh database | `run.bat --reset` | `./run.sh --reset` |
| Stop | `docker compose down` | same |
| Backend logs | `docker compose logs -f backend` | same |

- App: http://localhost:5173 (nginx serves the built SPA and proxies `/api`)
- API docs: http://localhost:8000/docs
- Readiness: http://localhost:5173/api/v1/system/status (`ready`, `bootstrap_state`)

## Checks (`scripts\check.ps1`, Linux/Mac `scripts/check.sh --flag`)

| Flag | Runs | Measured on the dev PC |
|---|---|---|
| (none) | FAST tier: ruff, `pytest -m "not slow"`, tsc, eslint, vitest | ~2 min |
| `-Backend` | `secrets` (git scan) + ruff + fast pytest | ~2.5 min (pytest step limit 300 s; `-PytestTimeout <sec>` or env `CHECK_PYTEST_TIMEOUT` to change; `check.sh` honours the env var; `-Slow`/`-Full` pytest steps keep 1200 s unless it is set) |
| `-Frontend` | tsc + eslint + vitest | ~55 s |
| `-Slow` | `pytest -m slow` (ML gate, full synthetic set) | ~15 s |
| `-Up` | rebuild app images with the `/dev/kit` route and start the stack | 15 s cached, minutes on first build |
| `-E2E` | `secrets`, `bootstrap.py e2e-fixtures`, then Playwright: route smoke, axe a11y + 390/1440 layout, security, bundle budget | ~7-8 min (step limit 900 s; `-E2ETimeout <sec>` or env `CHECK_E2E_TIMEOUT` to change) |
| `-Full` | everything: all pytest, frontend, `-Up`, e2e | |

Behaviour:
- Output is one line per step (`PASS`/`FAIL name time`) plus only failing test names / errors.
- Tool images (`backend-tools`, `frontend-tools`, `e2e`) rebuild only when their Dockerfile,
  requirements or package files change (stamps in `scripts/.check-build-*.stamp`). Source is mounted.
- Every step has a hard timeout. A second concurrent run prints `BUSY` (lock `scripts/.check.lock`).
  Check containers (`agentpulse-check-*`) older than 15 min are removed at start.
- `secrets` (host git, with `-Backend` and `-E2E`): fails on a tracked `.env`, key-shaped strings
  (Anthropic / OpenAI / AWS / GitHub / Slack / private keys) or any long `.env` secret value found
  in a tracked file. It prints file names only, never values.
- `-E2E` refuses to run when the stack is not ready or the frontend was built without `/dev/kit`
  (`run.bat` builds without it); run `-Up` first.

Typical use: backend change `-Backend`; UI change `-Frontend` (plus `-Up -E2E` when routes or flows
change); ML or data-generation change also `-Slow`.

## Backend CLI (`backend/bootstrap.py`)

Run inside the running stack: `docker compose exec -T backend python bootstrap.py <command>`.

| Command | Does |
|---|---|
| `wait-db` | wait until Postgres accepts connections |
| `needs-seed` / `seed` | check / load the synthetic dataset + reference seed (live clock: 120 days ending at the current hour; also rebuilt after a gap > 14 days or a mode/seed change) |
| `seed-reference` | re-run only the idempotent distributor / agent / user seed |
| `catch-up` | live clock: append the hours missed while stopped (24 h batches), anchor a demo story if none lies ahead (DEMO_MODE); no-op on the fixed clock |
| `needs-train` / `train` | check / retrain forecast artifacts (slow path) |
| `precompute` | register models, cache forecasts, risk, rebalance, anomalies, impact |
| `mark-ready` | set `bootstrap_state=ready` |
| `seed-notifications` | e2e: demo distributor's inbox becomes all read + exactly one unread notice |
| `e2e-fixtures` | e2e: `seed-notifications` + clear the wrong-password spec account's lockout |

`scripts/check -E2E` runs `e2e-fixtures` before every Playwright run, so the suite can be rerun
without `run.bat --reset`.

## Clock (live / fixed)

| Setting (`.env`) | Default | Effect |
|---|---|---|
| `CLOCK_MODE` | `live` | `live`: real time in Asia/Dhaka, hourly tick, catch-up on start. `fixed`: frozen at 2026-04-30 20:00 Dhaka (benchmarks). Switching rebuilds the data on the next start. |
| `DATA_TICK_INTERVAL_S` | `30` | how often the leader looks for a new hour (0 = off) |
| `DATA_CATCHUP_BATCH_H` | `24` | hours per catch-up transaction |
| `DATA_REGEN_GAP_DAYS` | `14` | a longer gap rebuilds the 120-day window instead |
| `CLOCK_SHIFT_H` | `0` | verification only: shift the live clock by N hours |

- Admin overview, card "Data clock": mode, now, data hour, last tick (seconds per stage), next
  tick, catch-up, demo story, and **Run tick now** (audited).
- Live-clock checks on the isolated stack (never the main one):
  ```powershell
  $env:COMPOSE_PROJECT_NAME='agentpulse-verify'; $env:COMPOSE_FILE='D:\Git\AI_Hackathon_DIU\docker-compose.yml;D:\Git\AI_Hackathon_DIU\docker-compose.verify.yml'  # absolute paths
  $env:BACKEND_PORT=18000; $env:FRONTEND_PORT=15173
  scripts\check.ps1 -Up; scripts\check.ps1 -E2E
  # catch-up after a 3-day gap: start with the clock 72 h behind, then restart normally
  $env:CLOCK_SHIFT_H=-72; docker compose up -d backend   # wait for ready
  $env:CLOCK_SHIFT_H=0;   docker compose up -d backend   # logs: "catch-up: 72 h"
  ```

## ML training and benchmark (fixed clock, isolated verify stack only)

Run with `CLOCK_MODE=fixed` on project `agentpulse-verify`; back up `backend/ml/artifacts` first.
`--out DIR` writes a candidate folder instead of the served artifacts.

| Command (`python -m ...` in the backend container) | Does |
|---|---|
| `ml.training.train [--out DIR]` | forecaster: train-period fit, validation selection + conformal, blind test, stockout copula (~11 min) |
| `ml.training.train --out DIR --recalibrate` | keep a candidate's boosters; redo calibration, scoring and the copula (~2 min) |
| `ml.training.anomaly [--out DIR]` | Isolation Forests, contamination from validation folds (~1 min) |
| `ml.training.helper_accept [--out DIR]` | helper acceptance model + policy simulation, simulated behaviour (~10 s) |
| `scripts.ml_benchmark --out FILE [--skip impact ...]` | every number of docs/ML_UPGRADE_RESULTS.md as JSON (~5 min) |

Method switches (`.env`): `FORECAST_CONFORMAL`, `STOCKOUT_METHOD`, `SWAP_MATCHING`,
`HELP_RANK_MODEL`, `HELP_WAVE_SIZING`, `HELP_WAVE_TARGET` (defaults and reasons: docs/DECISIONS.md ML1-ML9).

## Tool containers (one-off commands)

- Backend: `docker compose --profile tools run --rm -T backend-tools pytest tests/test_x.py`
- Frontend: `docker compose --profile tools run --rm -T frontend-tools npx vitest run src/...`
- e2e (stack up): `docker compose --profile e2e run --rm --no-deps -T e2e npx playwright test tests/shell.spec.ts`

- Van road cache (dev only, needs internet, ~11 min at 1 request/s):
  `docker compose -p agentpulse-verify -f docker-compose.yml -f docker-compose.verify.yml --profile tools run --rm --no-deps backend-tools python -m scripts.build_road_cache`
- Van evaluation (policies A-D, held-out synthetic days):
  `docker compose -p agentpulse-verify -f docker-compose.yml -f docker-compose.verify.yml --profile tools run --rm --no-deps backend-tools python -m ml.van.backtest --out ml/van/van_v1_eval.json`
  (or run `tests/test_van_eval.py` via `scripts\check.ps1 -Slow`)

## Tests

- pytest marker `slow`: model training, the full synthetic set, the ML gate. Fast tier excludes it.
- Test DBs are session-scoped templates (`seeded`, `ready`, `flagged`, `backtested`) copied per test.
- vitest setup skips motion animations and resets stores, storage, the app QueryClient, mocks and
  timers after every test.
