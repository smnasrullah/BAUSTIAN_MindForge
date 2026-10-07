# AI_Hackathon_DIU

AgentPulse AI: smart agent liquidity predictor for MFS agents (synthetic data only, advisory:
a human approves anything that moves money).

## Decision dashboards and one-click demo logins

Three role-based **AgentPulse Decision Dashboards**. With `DEMO_MODE=true` (default) each one has a
one-click demo login in the Judge demo section of http://localhost:5173/login (accounts in
"Demo logins" below).

| Dashboard | Link | What it shows |
|---|---|---|
| Agent Decision Hub | [/agent](http://localhost:5173/agent) | Hourly cash and e-money forecasts, 3:40 PM stockout countdown, What-if simulator, AI Copilot |
| Distributor Control Room | [/distributor](http://localhost:5173/distributor) | Geospatial liquidity risk map, bipartite swap matching queue, anomaly investigation, counterfactual impact calculator |
| Administrator Operations Hub | [/admin](http://localhost:5173/admin) | Model performance, TreeSHAP registry, audit trail, automated scheduler status |

## First run: what judges see during `run.bat`

1. **Stage 1, image pull and build (~2 min, internet needed).** Docker pulls base images and
   builds the backend and frontend. Time depends on your connection.
2. **Stage 2, database migration and seed (measured ~3.5 min, 203 s).** Alembic migrates, then the
   fixed-seed synthetic data is generated deterministically (empty volume, base images cached).
3. **Stage 3, readiness check (instant).** `GET /api/v1/system/status` returns `ready: true` and
   the script prints the URL.

Later starts take well under a minute and work offline.

## Automated verification

| Check | Result |
|---|---|
| Backend pytest | 78 passed, 0 failed, 100% core rule coverage |
| Frontend vitest | 42 passed, 0 failed |
| Accessibility (axe-core) | 0 violations |
| Performance | Initial bundle budget < 200 KB gzipped |

Run them with `scripts\check.ps1` (see [docs/COMMANDS.md](docs/COMMANDS.md)).

## Data freshness and timeline

The frozen benchmark timeline is **30 April 2026, 20:00 (Asia/Dhaka)** with 100% fresh simulated
inputs, so judging is reproducible. It is active with `CLOCK_MODE=fixed`; the default
`CLOCK_MODE=live` follows the real clock instead (see "Live clock vs fixed clock" below).
All data is synthetic.

## Quick start

1. Install Docker Desktop and start it.
2. Double-click `run.bat` (Windows) or run `./run.sh` (Linux/Mac) in the project folder.
3. Open http://localhost:5173 when the script says the app is ready.
4. Sign in with a demo account (one click on `/login`, see "Demo logins" below).

The **first** start needs internet (Docker base images and packages) and takes several minutes:
building the images (download time depends on your connection), then about 3.5 minutes to
create and seed a fresh database (measured on the live clock, empty volume, base images cached:
about 200 s of bootstrap after the build, 291 s from `up --build` to `ready`). Later starts take
well under a minute and work fully offline, except an
optional live LLM key (below); no other service is called. `run.bat`/`run.sh` wait up to 5
minutes for `GET /api/v1/system/status` to report `ready: true`; if it times out they print the
container logs. Fresh database: `run.bat --reset` (deletes the local data). More commands:
[docs/COMMANDS.md](docs/COMMANDS.md).

Problem evidence (public figures, replenishment, incidence stress test, sizing; no field interviews yet): [docs/PROBLEM_EVIDENCE.md](docs/PROBLEM_EVIDENCE.md), [docs/INCIDENCE_SENSITIVITY.md](docs/INCIDENCE_SENSITIVITY.md).

**`DEMO_MODE`** (in `.env`, created from `.env.example` on first start):
- `DEMO_MODE=true` (default) for local and judge runs: one-click demo logins, the help-request
  demo tools (simulate shortage, reset demo state) and demo defaults for the help-request waves.
- `DEMO_MODE=false` for any public hosting: no one-click logins, no demo tools, the real
  help-request rules only. Also set your own `JWT_SECRET` and demo passwords.

## Live clock vs fixed clock

The app shows the **real present** (Asia/Dhaka) by default: `CLOCK_MODE=live`.
- On a fresh database it generates 120 days of synthetic history ending at the current hour.
- While it runs, an hourly tick adds the new hour of synthetic data and recomputes forecasts,
  risk, recommendations, swaps, anomaly flags and (once a day) the impact backtest.
- After the app was stopped, it fills the missing hours on the next start (catch-up); after more
  than 14 days it rebuilds the window instead. Nothing is ever generated for a future hour.
- Every user sees the same server clock. The freshness chip says "Live simulation (synthetic
  data)"; the admin overview has a "Data clock" card (last/next tick, catch-up, "Run tick now").

`CLOCK_MODE=fixed` freezes the clock at 30 April 2026 20:00 Dhaka (the benchmark time): same data
and numbers on every PC. Tests and the published benchmark numbers use it. Details:
[docs/METHODS.md](docs/METHODS.md) ("Live clock vs fixed clock").

### First start after upgrading

The first start after upgrading from the fixed-clock version rebuilds the synthetic data once:
the old fixed April 2026 history is replaced by 120 days ending now (live clock). This takes
about as long as a fresh start (a few minutes; the app shows the "Preparing" screen meanwhile).
Demo logins, users, accounts, settings and audit history are kept; only transactions, float
snapshots, events and weather are regenerated. To keep the old fixed April data instead, add
`CLOCK_MODE=fixed` to `.env` and start again with `run.bat` / `./run.sh`; the first start in a
new mode rebuilds the data once more. Without a `CLOCK_MODE` line the default is `live`.

## 3-minute demo

A scripted walkthrough: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). On the live clock the demo
story is relative to now (AGT-0001 runs short this afternoon or tomorrow afternoon); with
`CLOCK_MODE=fixed` the timings are the same on every PC.

## Optional LLM key

The app works with **no key at all** — see "Replay and template answers" below. Setting one in
`.env` turns on live LLM wording (never numbers, never decisions — see docs/LLM_SPEC.md):

```
LLM_PROVIDER=anthropic        # or openai_compatible / auto (default)
LLM_MODEL=claude-haiku-4-5-20251001
LLM_API_KEY=...
```

### Use a free OpenAI-compatible key

Any OpenAI-compatible endpoint works. You create the key and edit `.env` yourself (the project
never creates or edits `.env`, and never ships a key):

1. Get a free key from a provider, for example **Groq** (console.groq.com) or **Google AI Studio**
   (Gemini). Do not paste it into chat, issues or commits.
2. Open your own `.env` (copy `.env.example` to `.env` first if you have none) and set these four
   lines. Example for Groq (check the provider's page for the current model name):

   ```
   LLM_PROVIDER=openai_compatible
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_MODEL=llama-3.3-70b-versatile
   LLM_API_KEY=<your key>
   ```

   Other endpoints (only `LLM_BASE_URL` and `LLM_MODEL` change):

   - **Gemini** free tier — `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`
   - **Local Ollama** (no key, no cost, no internet) — `LLM_BASE_URL=http://host.docker.internal:11434/v1`, `LLM_API_KEY=ollama`
3. Restart the stack (`run.bat` / `./run.sh`, no `--reset` needed). `GET /api/v1/llm/status` (and
   `/admin/llm` in the app) shows which provider is actually serving, and `key_configured` should
   read true.

Free tiers have rate limits; if a call fails or the numbers guard rejects it, the app falls back
to template wording with the same numbers.

## Demo logins

Seeded, synthetic accounts only. With `DEMO_MODE=true` (the `.env.example` default) `/login` shows
one-click chips for these; otherwise sign in with the password set at seed time.

| Role | Email | Notes |
|---|---|---|
| Admin | `admin@agentpulse.demo` | System status, models, users, LLM log, audit log |
| Distributor | `dist.dhaka@agentpulse.demo` | DST-DHK — pairs with the agent below for the demo script |
| Distributor | `dist.chattogram@agentpulse.demo` | DST-CTG |
| Distributor | `dist.sylhet@agentpulse.demo` | DST-SYL |
| Agent | `agent.mirpur@agentpulse.demo` | AGT-0001 — the scripted "cash runs dry at 3:40 PM" scenario |
| Agent | `agent.patiya@agentpulse.demo` | AGT-0002 |
| Agent | `agent.sunamganj@agentpulse.demo` | AGT-0003 |
| Agent | `agent.mirpur11@agentpulse.demo` | AGT-0004, ~1 km from AGT-0001: help-request helper (cash donor) |
| Agent | `agent.mirpur.chowdhury@agentpulse.demo` | AGT-0072, ~1.7 km: help-request helper |
| Agent | `agent.mirpur.sarkar@agentpulse.demo` | AGT-0064, ~1.8 km: help-request helper |
| Agent | `agent.mohammadpur@agentpulse.demo` | AGT-0106, ~4.3 km: help-request helper |

The four helper logins are synthetic shops of the generated data under DST-DHK, near AGT-0001.
They use the agent password (no one-click chip) and are created after the data load, on every
start if missing (`python bootstrap.py seed-helpers`), so an existing database gets them too.

## Replay and template answers

Every AI-written sentence in the app is labelled with where it came from, right next to the
"Model prediction" numbers it's explaining (never mixed together):

| Chip | Means |
|---|---|
| **AI-generated wording** | A live LLM call just answered, under the numbers guard (docs/LLM_SPEC.md §4) |
| **AI-generated wording (recorded)** | No live key, `CLOCK_MODE=fixed`: a real LLM answer recorded earlier for this exact scenario (`backend/app/llm/cache/demo_replay.json`), so the demo still sounds natural with zero cost and zero internet |
| **Template wording (no API key)** | No key is set, so the deterministic bn/en sentence is shown (this is what you see on a fresh install on the live clock) |
| **Template wording** | The same deterministic sentence when a key *is* set but the call failed, was rate-limited, or failed the numbers guard; or when `LLM_PROVIDER=template` was chosen on purpose |

Every wording surface carries one of these chips: the "Why?" panel, the agent Copilot, the
distributor briefing and the anomaly narrative. The `generated_by` field in the API (`llm`,
`replay`, `template`) always matches the chip, and `no_api_key` is true on template wording that
is served because no key is set.

`LLM_PROVIDER=auto` (default) picks automatically: key present -> live; no key -> recorded replay
**on the fixed demo clock only** (`CLOCK_MODE=fixed`, where the scripted scenario is the same on
every PC); otherwise template. On the live clock the data changes every hour, so recorded answers
are skipped by design and `/llm/status` (and `/admin/llm`) says so (`replay_skipped:
"live_clock"`). The numbers are identical in every case — only the sentence wording differs.
Full call log, provider status and today's usage: `/admin/llm` in the app.

## Demo mode and public hosting

Opening the app never signs anyone in: `/login` is a normal email + password form (show/hide
password, generic "Email or password is incorrect", lockout after 5 failures per email + IP).

`.env.example` ships with `DEMO_MODE=true` so local and judge runs also get a **Judge demo**
section on `/login` with one-click agent / distributor / admin accounts
(`POST /api/v1/auth/demo-login`: seeded `is_demo` accounts only, rate-limited per IP, every attempt
(success, denied, rate-limited) in `audit_log`). The section is shown only while the public
`GET /api/v1/system/status` reports `demo_mode: true`, and the backend logs a startup warning while
it is on.

**For any public hosting set `DEMO_MODE=false` in `.env`.** The demo-login endpoint is then not
registered at all, the Judge demo section disappears and every sign-in needs a password. Also set
your own `JWT_SECRET` and demo passwords.

### Sign-up and approval

`/signup` (name, email, password >= 8 characters, confirm) creates an account that is **pending**:
always the least-privileged role (agent), inactive, not linked to any agent counter. The client
cannot choose the role (unknown fields are rejected). Sign-up is rate-limited per IP
(`SIGNUP_PER_HOUR`, default 5) and audited (`auth.signup`); a taken email gets a generic refusal.
A pending account cannot sign in until an admin opens **Admin > Users**, filters by *Pending
approval*, picks the agent (or another role and link) and presses **Approve and activate**
(`PATCH /api/v1/admin/users/{id}` with `is_active: true`, audited as `user.approve`), or presses
**Reject** and confirms (`POST /api/v1/admin/users/{id}/reject`, audited as `user.reject`). A
rejected account is kept (never deleted) but can never sign in: it gets the same "email or
password is incorrect" answer as a wrong password, and signing up again with that email gets the
same refusal as any taken email, so the status is never revealed.

### Forgot / reset password (development mailer)

`/forgot-password` always answers the same, whether or not the email has an account. For an active
account it issues a single-use reset link valid for 30 minutes (`RESET_TOKEN_TTL_MIN`); only a
SHA-256 hash of the token is stored, a newer link cancels older ones, and requests are
rate-limited per IP (`RESET_REQUEST_PER_HOUR`) and per account (`RESET_PER_ACCOUNT_PER_HOUR`).
Resetting signs the user out everywhere (all refresh tokens revoked). Requests and resets are
audited (`auth.password_reset_request`, `auth.password_reset`); passwords are never logged.

There is no email server. `MAILER=dev_log` (the only mailer today) is **for development only**: it
writes the reset link to the backend log, marked `[DEV ONLY MAILER - no email sent]`:

```
docker compose logs backend | findstr "DEV ONLY MAILER"     (Linux/Mac: grep "DEV ONLY MAILER")
```

The link points at `PUBLIC_BASE_URL` (default `http://localhost:5173`) and carries the token in the
URL fragment (`/reset-password#token=...`), so it never reaches a server access log. To send real
email, add an SMTP class next to `DevLogMailer` in `backend/app/services/mailer.py`.

## More for judges / reviewers

- [docs/JUDGING_MAP.md](docs/JUDGING_MAP.md) — rubric criteria mapped to concrete evidence (files, routes, numbers)
- [docs/PATH_TO_PRODUCTION.md](docs/PATH_TO_PRODUCTION.md) — from this prototype to a real upay pilot
- [docs/RESPONSIBLE_AI_CHECKLIST.md](docs/RESPONSIBLE_AI_CHECKLIST.md) — governance, fairness, safety, privacy
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/METHODS.md](docs/METHODS.md), [docs/LLM_SPEC.md](docs/LLM_SPEC.md) — how it's built and how every number is produced
