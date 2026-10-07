# Performance

All numbers are measured on the isolated verify stack (`docker-compose.verify.yml`, project
`agentpulse-verify`) on the dev PC: Windows 11, Docker Desktop, 12 CPUs, 7.6 GB for Docker.
Seeded synthetic data (300 agents, ~0.9 M transactions), LLM in template mode. Raw outputs are
written to `scripts/perf/out/` and `e2e/perf/out/` (not committed). How to re-run: end of file.

## Budgets and result

| Budget | Before | After | Met? |
|---|---|---|---|
| Read endpoints p95 < 300 ms (single client, 30 calls) | worst 74 ms | worst 115 ms | yes |
| Risk list, map, stockout p95 < 500 ms | 36 / 27 / 11 ms | 29 / 35 / 19 ms | yes |
| What-if p95 < 300 ms (single client) | 49 ms | 23 ms | yes |
| 50 users, realistic (3-6 s think time), zero errors, p95 in budget | not measured | p95 106 ms, heavy 170 ms, what-if 108 ms, max 835 ms, 0 errors | yes |
| 50 users, aggressive (1 s think time) | p95 1.72 s, 47 req/s | p95 0.60 s, 121 req/s, 0 errors | no (see below) |
| Initial JS < 250 KB gzip | 178 KB | 176 KB | yes |
| LCP < 2.5 s, cold cache, 4x CPU + Slow 4G | 10.0 s signed-in, 7.3 s public (median) | 6.4 s signed-in, 6.0 s public | no (see below) |
| LCP < 2.5 s, warm cache (returning visitor) | see note | 2.3 s signed-in, 2.1 s public (median) | yes (median) |
| CLS < 0.1 | max 0.69 | max 0.10 (one route at 0.103) | almost |
| INP < 200 ms | median 220-250 ms | median 208-212 ms signed-in, 68-152 ms public | no (see below) |
| Route change (data cached) < 200 ms | not measured comparably | 0.41-0.68 s, distributor desktop 1.08 s | no (see below) |
| Long task < 200 ms on key pages | max 276 ms | max 256 ms | no |
| Fresh start to ready | 189 s (images cached) | 291 s, new empty volume, live clock (see "Clean-database start") | |

"Before" for the browser is the original frontend built from `main` and measured side by side
with the new one (same machine, same minute; the first baseline run measured the startup
"Preparing" screen instead of the page and was discarded, see "Measurement notes").

## API (single client, 30 timed calls after warm-up, `scripts/perf/bench_api.py`)

Top 12 by original p95. ms p50 / p95, SQL queries per request (Server-Timing).

| Endpoint | Before | After | Queries |
|---|---|---|---|
| `GET /admin/data` | 67.7 / 74.0 | 11.6 / 18.7 | 13 -> 12 |
| `GET /distributor/briefing` | 32.4 / 49.9 | 28.1 / 38.6 | 13 |
| `POST /agents/1/whatif` | 37.2 / 48.5 | 18.1 / 23.3 | 6 |
| `GET /agents/risk?horizon=24` | 23.1 / 35.5 | 19.2 / 29.3 | 6 |
| `GET /agents/risk/export.csv` | 22.5 / 32.7 | 19.4 / 30.1 | 6 |
| `GET /responsible-ai/model-card` | 20.0 / 32.4 | 14.5 / 19.3 | 14 |
| `GET /admin/overview` | 19.8 / 30.4 | 16.8 / 26.9 | 18 |
| `GET /map/agents` | 22.4 / 26.5 | 22.8 / 35.3 | 6 |
| `GET /system/status` (polled) | 20.1 / 27.7 | 5.1 / 6.6 | 4 -> 3 |
| `GET /admin/llm/usage` | 8.8 / 10.9 at 470 log rows | 21.4 / 115 at 6,500 rows (was 251 / 283 before the fix at the same size) | 3 -> 4 |

64 read endpoints measured; none over budget or 5xx, before or after. Single-client latency was
never the problem; throughput under concurrency was.

## Load (k6, `scripts/perf/load.js`, 50 virtual users, 2 min, through nginx)

| Profile | Before | After |
|---|---|---|
| Aggressive (1 s think): req/s | 47 | 121 |
| Aggressive: p95 all / heavy / what-if | 1.72 s / 1.66 s / 1.89 s | 0.60 s / 0.62 s / 0.70 s |
| Aggressive: errors | 0 | 0 |
| Realistic (3-6 s think): p95 all / heavy / what-if / max | not measured | 106 ms / 170 ms / 108 ms / 835 ms |
| Realistic: errors | | 0 |

Backend memory: 256 MB with one worker before, ~600-700 MB with four workers under load after.

## Frontend (Playwright, headless Chromium, 4x CPU, DevTools "Slow 4G": 562 ms RTT, 1.44 Mbit/s)

Medians over 22 signed-in and 4 public route x viewport (1440 and 390 px) combinations.

| Metric | Original | New |
|---|---|---|
| Signed-in cold: page ready / LCP | 11.0 s / 10.0 s | 6.8 s / 6.4 s |
| Signed-in warm: page ready / LCP | 3.0 s / 1.1 s* | 2.7 s / 2.3 s |
| Public cold: ready / LCP | 7.0 s / 7.3 s | 5.9 s / 6.0 s |
| Public warm: ready / LCP | 2.1 s / 2.2 s | 2.0 s / 2.1 s |
| CLS max signed-in (cold / warm) | 0.19 / 0.69 | 0.10 / 0.06 |
| CLS max public (cold / warm) | 0.08 / 0.27 | 0.08 / 0.10 |
| INP median signed-in | 220-248 ms | 208-212 ms |
| JS heap after load | 9.5-22 MB | 9.5-25 MB |
| Extra JS files a cold /agent visit fetches after the shell | 68 | 19 |

\* the original's warm LCP is the "Preparing" screen painted before the page (fixed in D6).

## What changed (Phase 2) and the measured effect

1. Several uvicorn workers (D3): throughput 47 -> 90 req/s at 50 users.
2. What-if path cache (D9): what-if p95 under load 1.0 s -> 0.4 s (aggressive), 670 -> 108 ms
   (realistic).
3. `/system/status`: Alembic head parsed once, catalog query removed, manifest cached: 20 -> 5 ms.
4. `/admin/data`: big-table counts cached on max(id): 68 -> 12 ms.
5. `/admin/llm/usage`: aggregated in SQL: 251 -> 21 ms at 6,500 log rows (it grew with use).
6. Risk reads skip the 1 KB-per-row `prob_by_hour` JSON they never use.
7. Index `forecasts(model_version_id, generated_at)` for the polled freshness query.
8. Build chunk grouping (D5): 68 -> 19 extra files on a cold signed-in visit.
9. Boot requests in parallel with the language chunk; no "Preparing" flash (D6).
10. Duplicate notification fetches on every load removed (3 -> 1).
11. Layout shifts: footer pushed off-screen by loading content, freshness chip wrapping, copilot
    suggestions popping in, landing hero line wrapping during its intro (CLS 0.69 -> 0.10).
12. nginx serves precompressed assets (`gzip_static`, level 9 at build).

## Budgets still missed, and why

- Cold LCP on Slow 4G (6.0-6.4 s vs 2.5 s): a cold visit needs HTML, then JS (176 KB at
  180 KB/s), then the status check, the session refresh, the user, and the page data, each one
  round trip of 562 ms in this profile. The chain alone is about 4 s before rendering. Warm
  visits (assets cached) meet the budget at the median. Next step if needed: server-side
  rendering of the shell or an HTTP/2 + TLS front, both out of scope for a local Docker demo.
- INP ~210 ms and long tasks ~250 ms: measured on software rendering (no GPU in the container)
  at 4x CPU. The time is presentation delay (the next frame), not handlers (~1 ms). With reduced
  motion the same click takes ~40 ms: the decorative wave drift under the glass top bar costs
  a repaint every frame. The app already turns those off on devices with <= 4 cores (DESIGN.md
  low-end flag); the emulator reports the host's 12 cores so it measures the full-effects path.
- Route change 0.4-0.7 s (1.1 s on the distributor desktop): measured at 4x CPU; it is mostly
  rendering the target page (agents table, map). Not optimised further in this pass.
- Aggressive load profile (1 s think time per user): p95 0.60 s vs 0.3/0.5 s. The API is
  CPU-bound Python; four workers are saturated at ~120 req/s on this PC. The realistic profile
  meets every budget.

## Measurement notes (honest caveats)

- The first browser baseline counted the startup "Preparing" screen as the page (it has an h1
  and no skeleton). The harness now waits for the real page marker; old numbers were re-measured
  with the original build side by side.
- Single-client API numbers vary +-20% between runs (four workers, Docker on Windows).
- Bench warm-up hits each worker twice; the first calls to a fresh worker are slower.

## Clean-database start (fresh volume, 2026-10-06, synthetic data)

What was measured: a brand-new, empty Postgres volume on the verify project, so migrations,
seeding, model registration and all precompute steps run from nothing.

- Command (PowerShell, repo root):
  `$env:BACKEND_PORT=18000; $env:FRONTEND_PORT=15173; $env:CLOCK_MODE='live'; $env:VERIFY_PGDATA='agentpulse-verify_fresh1'`
  then `docker compose -p agentpulse-verify -f docker-compose.yml -f docker-compose.verify.yml up --build -d`.
  The main volume `agentpulse_pgdata` and the old verify volume were not touched.
- Machine: Intel Core i5-12450H (8 cores / 12 threads), 15.7 GB RAM; Docker Desktop with 12 CPUs
  and 7.6 GB. The main stack was also running (idle).
- Image cache: warm. Base images (python:3.11-slim, postgres:16-alpine, node, nginx) were
  already present; the backend image was rebuilt because `requirements.txt` changed (PyYAML
  pin), so the pip layer ran again and the frontend image came from cache. A fully cold build
  (no images, no layers) was not measured; it adds the download time of the base images and
  packages, which depends on the connection.
- Start = the moment the `docker compose up --build -d` command was typed. Ready =
  `GET /api/v1/system/status` returns `ready: true` (`bootstrap_state: ready`).

| Step | Time |
|---|---|
| `up --build -d` returns (build 1 backend image, start 3 containers) | 87 s |
| Start to ready | 291 s (about 204 s after `up` returned) |
| In that: database wait 5 s, migrations 0001 to 0023 4 s, seed 75 s (reference data, 120-day live window: 300 agents, 864,600 snapshots, 930,978 transactions), catch-up 3 s | |
| In that: precompute 103 s = forecast 16.2, risk 18.1, rebalance 0.5, anomalies 5.1, backtest 60.3 | |

Migrations: all 23 applied on the empty database without error; `alembic current` = `heads` =
`0023`, and `/system/status` shows `migration_current` = `migration_head` = `0023`.

Clock modes on the same volume (no image build, so `up` returns in 2 s):

| Switch | What happened | Start to ready |
|---|---|---|
| live (fresh volume) | full seed as above; demo story anchored today (stock-out 15:40 Dhaka) | 291 s |
| live to `CLOCK_MODE=fixed` | "clock_mode changed" rebuild; data hour 2026-04-30 20:00 Dhaka | 189 s |
| fixed to `CLOCK_MODE=live` | "clock_mode" rebuild, live window ending now | 157 s |

Checked in each mode: `/system/status` (`ready: true`), demo login for agent, distributor and
admin (all succeed), `/admin/clock` mode. After the live to fixed switch: 11 users and the audit
history were still there (only transactions, snapshots, events and weather are rebuilt).
Single runs, no repeats: expect +-20% on another PC.

## Live hourly tick (Phase 1B, verify project, 300 agents, synthetic data, 2026-10-06)

Measured with `scripts/perf/force_tick.sh`: cache keys cleared on the verify database, then a
real manual tick in the leader process (no new hour of data, so "data" is ~0.02 s; a natural
tick adds the append of one hour, 0.2 s in the earlier live-clock measurement).

| | Before | After |
|---|---|---|
| Normal tick | 31.2 s (forecast 11.4, risk 15.5, rebalance 0.3, anomalies 4.0) | 24.3-33.0 s, median 26.3 s of 4 runs (risk 8.0-12.5) |
| First tick after midnight | 74.5 s (backtest 44.2 s inside; over the 60 s budget) | 25.5 s (no backtest stage) |
| Daily backtest | inside the tick | own job: 42.2 s, after the tick, budget 180 s |
| Risk stage, isolated profile | 14.7 s (projections 10.2, refill history 3.8) | 6.0 s (projections ~3.3 on 4 threads, history 2.2) |

The refill-aware view itself (habit maths 0.01 s, its own 500-path run ~2 s) was never the main
cost; the 42-day history load (3.8 s) and the decision projections (2,000 paths x 2 floats,
~8 s) were. Run-to-run spread on this PC is +-20% (forecast 10.5-18 s for the same work).
Fixed-mode fingerprint (Postgres, fixed clock, seed 42): forecasts, explanations, stock-out,
risk, recommendations, swaps, anomalies, impact and fairness identical between the bootstrap
caches, a forced recompute, and a forced recompute with the old history loader.

## How to run

```
# Optional: $env:VERIFY_PGDATA='agentpulse-verify_fresh1' mounts a new empty volume (fresh-DB test)
$env:BACKEND_PORT=18000; $env:FRONTEND_PORT=15173
docker compose -p agentpulse-verify -f docker-compose.yml -f docker-compose.verify.yml up --build -d
# API bench (inside the verify network)
docker run --rm --network agentpulse-verify_default -v ${PWD}/scripts/perf:/w --entrypoint python agentpulse-verify-backend /w/bench_api.py --base http://backend:8000
# Load: realistic (default) or aggressive (THINK_MIN=1 THINK_MAX=1)
docker run --rm --network agentpulse-verify_default -v ${PWD}/scripts/perf:/w grafana/k6 run /w/load.js
# Web vitals
docker compose -p agentpulse-verify -f docker-compose.yml -f docker-compose.verify.yml --profile e2e run --rm --no-deps -T e2e npx playwright test -c playwright.perf.config.ts vitals
# Bundle report
docker compose --profile tools run --rm -T frontend-tools sh -c "npx vite build --manifest --outDir /tmp/d && node scripts/bundle-report.mjs /tmp/d"
# Live tick (verify only): stage profile in a rolled-back transaction, then a real in-process tick
docker compose -p agentpulse-verify exec -T backend mkdir -p /app/scripts_perf
docker compose -p agentpulse-verify cp scripts/perf/profile_tick.py backend:/app/scripts_perf/
docker compose -p agentpulse-verify exec -T -e PYTHONPATH=/app backend python /app/scripts_perf/profile_tick.py [--backtest]
bash scripts/perf/force_tick.sh [--midnight]   # clears cache keys on the VERIFY db, runs a manual tick
# Fixed-mode fingerprint (cp scripts/perf/fingerprint.py the same way): stored caches, or recomputed
docker compose -p agentpulse-verify exec -T -e PYTHONPATH=/app backend python /app/scripts_perf/fingerprint.py [--recompute] [--old-history]
```

## One-hour bug and latency pass (2026-10-06, verify stack, synthetic data)
Idle read bench (bench_api.py, 30 calls after warm-up): 62 endpoints, slowest p95 53.5 ms (`/impact/comparison`), all under the 300 ms budget; most p95 under 25 ms. Most queries: `/admin/overview` 18 (now 13), briefing and model-card 15. During one forced hourly tick (24 s, all caches invalidated, 150 s probe, 5 sequential reads): p95 13-39 ms, max 190 ms, 0 errors, so no tick isolation. After the changes and one rebuild: 64 endpoints, 0 over budget, max 15 queries.
First-load JS (same gzip method as security.spec): `/login` 256,013 B -> 231,922 B (login form no longer pulls zod); `/` 229,818 B. Initial chunk set unchanged (176.5 KB).
