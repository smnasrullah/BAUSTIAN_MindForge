# Architecture (AgentPulse AI)

Modular monolith: React SPA -> FastAPI `/api/v1` -> PostgreSQL 16. ML artifacts are committed joblib files. LLM provider is optional (`auto` -> replay -> template).
Role codes: **A** agent, **D** distributor, **Ad** admin, **P** public. Scoping: A sees own agent_id only, D sees own agents only, Ad sees all.

## 1. Sitemap

| Route | Role | Page | Main components / features |
|---|---|---|---|
| `/login` | P | Email + password sign in; Judge demo chips only when DEMO_MODE | - |
| `/signup` | P | Self-signup (name, email, password); account waits for admin approval | - |
| `/forgot-password` | P | Request a single-use reset link (same answer for any email) | - |
| `/reset-password` | P | New password from `#token=...` link | - |
| `/agent` | A | Home (story view) | PulseLine, CountdownCard, 2 VesselGauge, Why, primary action (F1-F4, F7) |
| `/agent/forecast` | A | 72h forecast + what-if | RunwayStrip, event ribbons, what-if slider (F1, F2, F6, F8) |
| `/agent/swap` | A | Swap offers + recommendation status | SwapFlow card (read-only, D approves) (F4, F5) |
| `/agent/copilot` | A | Ask (chat + voice) | CopilotSheet, mini-card answers, AI-generated chip (LLM) |
| `/agent/settings` | A | Language, digits, theme | - |
| `/distributor` | D | Control room map | Filters/list, map (risk dots, swap droplets), inspector, RunwayStrip, Ctrl+K (F3, F10) |
| `/distributor/agents/:id` | D | Agent detail | Forecast, risk, Why, recommendation (F1-F4, F7) |
| `/distributor/swaps` | D | Swap queue | Handshake approve/reject + note (F5) |
| `/distributor/anomalies` | D | Anomaly list | Isolation Forest scores (F9) |
| `/distributor/anomalies/:id` | D | Investigation | Evidence + LLM narrative, review + note (F9, LLM) |
| `/distributor/impact` | D | Impact calculator | Model vs rule baseline (F11) |
| `/distributor/briefing` | D | Daily briefing | LLM briefing grounded in evidence pack (LLM) |
| `/admin` | Ad | System status | `/system/status`, LLM mode, artifacts |
| `/admin/users` | Ad | Users + roles | - |
| `/admin/models` | Ad | Model registry + metrics | Pinball/MAE, stockout recall, drift |
| `/admin/llm` | Ad | LLM call log | provider, tokens, latency, guard_result |
| `/admin/audit` | Ad | Audit log | Human decisions |
| `/responsible-ai` | A, D, Ad | Responsible AI panel | Model cards, fairness, limitations, data notice (F12) |

## 2. REST endpoints (prefix `/api/v1`)

All prediction responses include `model_version` + `generated_at`. All LLM responses include `generated_by: llm|template|replay`.

| Module | Method | Route | Purpose | Role |
|---|---|---|---|---|
| admin | GET | `/admin/audit-log` | Human decisions and admin changes, newest first, with the action / entity facets. | Ad |
| admin | GET | `/admin/audit-log/export.csv` | Every human decision (swap, anomaly, request, admin change), newest first; same filters as the list. | Ad |
| admin | GET | `/admin/clock` | Data clock card: mode, now, data hour, last tick (seconds per stage), next tick, catch-up, demo story. | Ad |
| admin | POST | `/admin/clock/tick` | Live clock only (409 `clock_fixed`): ask the leader to tick now; audited `data_clock.tick`. | Ad |
| admin | GET | `/admin/data` | Seed, data version, period (holdout, forecast origin) and row counts of the synthetic dataset. | Ad |
| admin | GET | `/admin/data/assumptions` | docs/SYNTHETIC_ASSUMPTIONS.md as Markdown text. | Ad |
| admin | GET | `/admin/drift` | Forecast-error drift: cached forecast vs logged demand, against the holdout MAE. | Ad |
| admin | GET | `/admin/jobs` | The 20 most recent jobs and the one running, if any. | Ad |
| admin | POST | `/admin/jobs` | Start generate_data, retrain_forecast, retrain_anomaly or help_trigger (one tick of the liquidity help trigger, same as the background loop) in the background; poll GET /admin/jobs/{id} for progress. One job at a time (409 job_running). Retrained models are recorded inactive; serving keeps the committed model. | Ad |
| admin | GET | `/admin/jobs/{job_id}` | get_job | Ad |
| admin | GET | `/admin/llm/logs` | llm_call_log newest first: tokens, latency, generated_by, cache hit, guard result. | Ad |
| admin | GET | `/admin/llm/usage` | Calls per UTC day by outcome, tokens, latency, cache hit rate and today's cap usage. | Ad |
| admin | GET | `/admin/models` | Every registered model version (active first) with its stored holdout metrics. | Ad |
| admin | GET | `/admin/org` | Distributors and agents (id, code, name) for linking users. | Ad |
| admin | GET | `/admin/overview` | Counts by role, open work queues, active models, LLM calls vs cap, latest job, audit. | Ad |
| admin | GET | `/admin/users` | Users by role then e-mail; `q` matches e-mail or name. | Ad |
| admin | POST | `/admin/users` | Create a user linked to an agent (agent) or distributor (distributor). audit_log. | Ad |
| admin | PATCH | `/admin/users/{user_id}` | Name, role + link, or active flag. Disabling revokes every session. audit_log. | Ad |
| admin | POST | `/admin/users/{user_id}/reject` | Reject a pending self-signup (kept, never deleted; it can never sign in). 409 when the account is not pending. audit_log user.reject. | Ad |
| agents | GET | `/agents` | list_agents | D, Ad |
| agents | GET | `/agents/{agent_id}` | get_agent | A, D, Ad |
| anomalies | GET | `/anomalies` | Isolation Forest flags in scope (distributor: own agents; admin: all), open first. | D, Ad |
| anomalies | GET | `/anomalies/{anomaly_id}` | One flag with its peer-group distribution per feature and the top reasons. | D, Ad |
| anomalies | POST | `/anomalies/{anomaly_id}/review` | Human review: confirmed or dismissed with a note (audit_log). Nothing else happens. | D, Ad |
| auth | POST | `/auth/change-password` | change_password | A, D, Ad |
| auth | POST | `/auth/demo-login` | One-click sign-in as a seeded is_demo account (DEMO_MODE only, rate-limited per IP, audited). Never enable DEMO_MODE on a public deployment. | P |
| auth | POST | `/auth/forgot-password` | Same 202 whether or not the e-mail has an account. A single-use link (30 min) goes out through the mailer; the development mailer writes it to the server log. Audited. | P |
| auth | POST | `/auth/login` | login | P |
| auth | POST | `/auth/logout` | Works with an expired access token: the cookie alone identifies the session. | P |
| auth | GET | `/auth/me` | me | A, D, Ad |
| auth | POST | `/auth/refresh` | refresh | P |
| auth | POST | `/auth/reset-password` | Spend a reset token: new password, every session of the user signed out. Unknown, used and expired tokens all get 400 `invalid_reset_token`. Audited. | P |
| auth | POST | `/auth/signup` | Self-signup. Always a pending agent account with no agent link (the role is not taken from the client); it cannot sign in until an admin approves it. Rate-limited per IP, audited (auth.signup). A taken e-mail gets the generic 400 `signup_rejected`. | P |
| copilot | POST | `/copilot/chat` | Agent Copilot (bn/en): grounded, role-scoped, advisory. Off-topic and injection attempts are refused without an LLM call; every answer is labelled generated_by llm\|replay\|template. | A, D, Ad |
| copilot | GET | `/copilot/suggestions` | Suggested questions for `lang` (bn \| en). Missing or unsupported `lang` falls back to the user's language. Replay matches exact question text, so these are the prompts that show recorded LLM wording without a key. | A, D, Ad |
| events | GET | `/events` | Events overlapping [from, to), by start time; `district` keeps nationwide events too. | A, D, Ad |
| events | POST | `/events` | Add an event (audit_log). Forecasts use it from the next precompute. | Ad |
| events | DELETE | `/events/{event_id}` | Delete an event (audit_log keeps the deleted row). | Ad |
| events | PUT | `/events/{event_id}` | Replace an event (audit_log keeps before/after). | Ad |
| explanations | GET | `/agents/{agent_id}/explanations` | Top SHAP drivers of the next 24 h demand on one float, as bn/en template sentences. | A, D, Ad |
| forecast | GET | `/agents/{agent_id}/forecast` | Hourly low/expected/high (q10/q50/q90) demand per float, from the bootstrap cache. | A, D, Ad |
| impact | GET | `/impact/comparison` | Day-by-day AI vs baseline inside [from, to] (clipped to the holdout) + range totals. | D, Ad |
| impact | GET | `/impact/summary` | AI vs fixed-threshold baseline over the 14 held-out days (own agents for a distributor). | D, Ad |
| liquidity-requests | GET | `/admin/liquidity-requests` | Every help request, newest first. | Ad |
| liquidity-requests | GET | `/admin/liquidity-requests/demo` | What DEMO_MODE changes for help requests: demo defaults in force, the automatic-request cap, the fresh-bootstrap start delay and the last demo reset. Read-only. | Ad |
| liquidity-requests | POST | `/admin/liquidity-requests/demo-reset` | DEMO_MODE only. Cancels the demo agents' open or claimed requests (kept and audited, nobody notified), ends a simulated shortage and restarts their cooldown, daily cap and demo auto cap from now. Audit logged (help_demo.reset). | Ad |
| liquidity-requests | POST | `/admin/liquidity-requests/dry-run` | Shows which agents WOULD get a request and who WOULD be asked. Writes nothing, sends nothing, whatever the kill switch and dry-run settings say. | Ad |
| liquidity-requests | POST | `/admin/liquidity-requests/run-trigger` | One tick now, the same as the background scheduler: sweep timeouts, advance waves, run the trigger. Under dry run or the kill switch nothing is created or sent and the response lists what WOULD have been. | Ad |
| liquidity-requests | GET | `/admin/liquidity-requests/settings` | Kill switch, dry run, claim timeout, cooldown, daily cap, recipients per wave. | Ad |
| liquidity-requests | PUT | `/admin/liquidity-requests/settings` | Change any subset of the switches (audit_log keeps old and new values). | Ad |
| liquidity-requests | POST | `/admin/liquidity-requests/simulate-shortage` | DEMO_MODE only. Forces one agent into a shortage for 30 minutes and runs the trigger for that agent now. Audit logged; every request it makes is marked simulated. Under dry run or the kill switch nothing is sent and would_create says what would have been. | Ad |
| liquidity-requests | POST | `/admin/liquidity-requests/sweep` | Reopen timed-out claims and expire overdue requests now. Safe to repeat. | Ad |
| liquidity-requests | GET | `/admin/liquidity-requests/trigger-settings` | Horizon, buffer, minimum shortfall, cap, lead margin, radius, waves, timeout, deadline floor, urgent wave multiplier. | Ad |
| liquidity-requests | PUT | `/admin/liquidity-requests/trigger-settings` | Change any subset (audit_log keeps old and new values). Bounds checked by the schema. | Ad |
| liquidity-requests | GET | `/liquidity-requests/inbox` | Requests the caller was asked to help with (amount, area and deadline; no balances). | A, D |
| liquidity-requests | GET | `/liquidity-requests/mine` | As requester: an agent's own requests; a distributor's agents' requests. Newest first. | A, D |
| liquidity-requests | GET | `/liquidity-requests/opt-out` | The caller's own choice. opted_out: true = never asked to help others. | A |
| liquidity-requests | POST | `/liquidity-requests/opt-out` | Same as PUT /opt-out (kept for older clients). (deprecated) | A |
| liquidity-requests | PUT | `/liquidity-requests/opt-out` | Change the caller's own choice (only their own agent; audited). Opted-out agents are never ranked as helpers. | A |
| liquidity-requests | GET | `/liquidity-requests/{request_id}` | One request. Unknown ids and ids outside the caller's reach are both 403. | A, D, Ad |
| liquidity-requests | POST | `/liquidity-requests/{request_id}/cancel` | The requester agent, their own distributor or an admin cancels an open or claimed request. Anyone else is 403. Audited (actor, old and new status). | A, D, Ad |
| liquidity-requests | POST | `/liquidity-requests/{request_id}/claim` | A listed recipient accepts. Exactly one wins; the others get 409 already_taken. | A, D |
| liquidity-requests | POST | `/liquidity-requests/{request_id}/confirm` | The requester agent or their distributor confirms receipt. | A, D |
| liquidity-requests | POST | `/liquidity-requests/{request_id}/confirm-late` | The requester agent or their distributor confirms that the helper whose claim timed out delivered after all. Only on a reopened request that had such a claim (409 no_lapsed_claim otherwise). | A, D |
| liquidity-requests | POST | `/liquidity-requests/{request_id}/decline` | A listed recipient says no; nobody else is affected. | A, D |
| liquidity-requests | POST | `/liquidity-requests/{request_id}/withdraw` | The helper who claimed it backs out before confirmation; the request reopens. | A, D |
| llm | GET | `/agents/{agent_id}/briefing` | Morning briefing for one agent: risk, main reason, suggested action (advisory). | A, D, Ad |
| llm | GET | `/anomalies/{anomaly_id}/narrative` | Neutral investigation note for one flag, from its peer evidence only. | D, Ad |
| llm | GET | `/distributor/briefing` | Daily briefing over the caller's agents (distributor: own; admin: all). | D, Ad |
| llm | POST | `/explanations/narrate` | SHAP template reasons for one float, reworded by the LLM (template on any failure). | A, D, Ad |
| llm | GET | `/llm/status` | Configured and effective provider, today's live calls vs the cap, last error code. | A, D, Ad |
| map | GET | `/map/agents` | Scoped agents' lat/lng + risk level at `at_hour` (0..72) + current swaps (time scrubber). | D, Ad |
| notifications | GET | `/notifications` | The caller's own notifications, newest first, with the unread count for the bell. `entity_type=liquidity_request&unread=true&page_size=1` is the cheap help-badge poll. | A, D, Ad |
| notifications | POST | `/notifications/read-all` | read_all | A, D, Ad |
| notifications | POST | `/notifications/{notification_id}/read` | read_one | A, D, Ad |
| recommendation-requests | GET | `/recommendation-requests` | Requests in scope (agent: own; distributor: own agents; admin: all), newest first. | A, D, Ad |
| recommendation-requests | POST | `/recommendation-requests/{request_id}/cancel` | Agent withdraws own request while it is still awaiting a decision (audit_log). | A |
| recommendation-requests | POST | `/recommendation-requests/{request_id}/decision` | Distributor approves or declines a requested item with a note (audit_log). | D |
| recommendation-requests | POST | `/recommendation-requests/{request_id}/fulfil` | Distributor records that an approved request was delivered (audit_log). | D |
| recommendation-requests | POST | `/recommendations/{recommendation_id}/request` | Agent asks the distributor to act on own recommendation. A repeat call returns the existing request (200). | A |
| recommendations | GET | `/agents/{agent_id}/recommendation` | Top-up amount and deadline per float that will not cover the next hours (advisory). | A, D, Ad |
| responsible-ai | GET | `/responsible-ai/fairness` | Held-out forecast MAE and stockout recall per agent group, with the gap between groups. | A, D, Ad |
| responsible-ai | GET | `/responsible-ai/model-card` | Active models, held-out metrics, data, intended use, limits; advisory only. | A, D, Ad |
| risk | GET | `/agents/risk` | Risk of the caller's agents at one horizon (agent: self; distributor: own agents). | A, D, Ad |
| risk | GET | `/agents/risk/export.csv` | The risk list (same filters, all pages) as CSV; scoped like GET /agents/risk. | A, D, Ad |
| risk | GET | `/agents/{agent_id}/risk` | Stockout probability and green/amber/red level at 6 / 24 / 72 h per float. | A, D, Ad |
| risk | GET | `/agents/{agent_id}/stockout` | Time-to-stockout + confidence per float (no refills assumed). | A, D, Ad |
| risk | GET | `/agents/{agent_id}/summary` | Profile, balances, time-to-stockout and risk levels in one call. | A, D, Ad |
| search | GET | `/search` | Command palette: agents in the caller's scope (code / name / region) + role pages, max 8. | A, D, Ad |
| swaps | GET | `/swaps` | Swap suggestions in scope (agent: own as donor or receiver; distributor: own agents). | A, D, Ad |
| swaps | GET | `/swaps/export.csv` | The swap queue in scope as CSV (notes are user text: formula-escaped). | A, D, Ad |
| swaps | POST | `/swaps/{swap_id}/decision` | Distributor approves or rejects with a note (audit_log). Advisory: no money moves. | D |
| swaps | POST | `/swaps/{swap_id}/respond` | Donor or receiver agent accepts or declines (audit_log); the distributor still decides. | A |
| system | GET | `/health` | health | P |
| system | GET | `/system/freshness` | Last forecast time, active model version, synthetic data period and LLM mode. | A, D, Ad |
| system | GET | `/system/health` | health | P |
| system | GET | `/system/status` | system_status | P |
| users | PATCH | `/users/me/preferences` | Language, theme, digits, in-app notifications, onboarding tour; only sent fields change. | A, D, Ad |
| users | GET | `/users/me/profile` | get_profile | A, D, Ad |
| users | PATCH | `/users/me/profile` | Display name (no e-mail / phone numbers) and avatar colour token. | A, D, Ad |
| whatif | POST | `/agents/{agent_id}/whatif` | Stockout + risk if `delta_amount` BDT were added to one float now (advisory, no money moves). | A, D |

Generated from the live OpenAPI app (`app.main.app`): purpose = first docstring paragraph, role =
the route's `require_roles` (A, D, Ad; "A, D, Ad" = any signed-in user; P = public). Roles are
checked server-side on every call; scoping (own agent / own agents) is in the services.

### Swap lifecycle (F5)

1. **Proposed**: the nightly precompute's matcher (rules in `app/rules/swap_rules.py` + scipy
   assignment) pairs a donor with surplus and a receiver short of the same float, same
   distributor, within `SWAP_RADIUS_KM`. Status `pending`.
2. **Agents answer** (`POST /swaps/{id}/respond`, accept / decline + note): each side may change
   its answer while the swap is `pending`. Audited (`swap.accept` / `swap.decline`).
3. **Distributor decides** (`POST /swaps/{id}/decision`, approve / reject + required note):
   `approved` or `rejected`, then locked (409 `already_decided`). Approval is refused while an
   agent has declined (409 `swap_declined`). Audited with user id and note; both agents notified.
4. Nothing moves money: an approved swap is a recorded agreement the two agents carry out.

### Help-request lifecycle (liquidity help)

States `open -> claimed -> fulfilled`; `claimed -> open` (helper withdraws, or the claim times
out: reopened); `open -> expired` (deadline passed or every wave failed); `open | claimed ->
cancelled`; `open | expired -> fulfilled` (late confirm by the requester side after a timed-out
claim, within the grace window). All moves are compare-and-set (`app/rules/help_request_rules.py`
TRANSITIONS); anything else is 409.

1. **Created** by the background trigger (forecast: projected balance below the agent's buffer,
   risk red) or, in DEMO_MODE, by the admin's **simulate shortage** (marked simulated). Limits:
   one active request per agent and float, cooldown, rolling daily cap, at most N new per tick;
   in DEMO_MODE at most one automatic request per agent and float per day.
2. **Wave 1**: the requester's distributor plus the best-ranked nearby agents (same distributor,
   within radius, enough surplus, not opted out, fairness rotation); urgent requests ask more.
   Each later wave goes out after `wave_timeout_min` without a claim; after the last wave the
   request expires and the distributor and admins are told.
3. **Claim**: the first helper to accept wins (`/claim`); everyone else is told it is covered.
   The winner may withdraw; an unfinished claim reopens after `claim_timeout_min`.
4. **Confirm**: the requester (or their distributor) confirms the money arrived (`/confirm`, or
   `/confirm-late`), or calls it off (`/cancel`, confirm dialog; distributor only for its own
   agents). Every step is audited and notified; helpers only see a coarse reason category.
5. The scheduler runs this every minute in one leader process (Postgres advisory lock); admins
   see its status, can run one check now, use dry run, and in DEMO_MODE reset the demo state.

### Live clock (CLOCK_MODE=live, default)

```
 app/core/clock.py  -- now() (Asia/Dhaka), target_hour(), data_now() = system_meta.sim_now
        |
 data_scheduler (leader, every 30 s) --new hour?--> tick_guard (a tick still running: skip + log)
        |                                             '-> data_clock.tick()
        |                                             |-- live_load.append(): hours since the data hour
        |                                             |   (24 h batches, advisory write lock, no future rows)
        |                                             |-- ensure_story() (DEMO_MODE)
        |                                             '-- pipeline.precompute(backtest_too=False):
        |                                                 forecast+SHAP, risk, rebalance+swaps, anomalies
        |--> help_scheduler.wake(): the help trigger reads the fresh caches
        '--> backtest_job.wake()
 backtest_job (own leader, every 60 s + wake; not during a tick) --holdout key changed (new day)?-->
        backtest.precompute(): impact + fairness, own 180 s budget; status on the admin Data clock card
```

Fixed clock (tests, benchmarks): no scheduler; bootstrap precomputes once at SIM_NOW.

## 3. Database tables (PostgreSQL 16)

Money = `NUMERIC(14,2)` BDT. Times = `TIMESTAMPTZ` (Asia/Dhaka on display). Enums as PG enums.

| Table | Columns (type) | Keys | Indexes |
|---|---|---|---|
| users | id uuid, email text, full_name text, password_hash text, role enum(agent,distributor,admin), agent_id int null, distributor_id int null, lang enum(bn,en), theme enum(light,dark,system), is_active bool, last_login_at null, created_at | PK id; FK agent_id, distributor_id; CHECK role scope | UQ email |
| refresh_tokens | id uuid, user_id uuid, token_hash text, expires_at, revoked_at null, replaced_by uuid null, user_agent text null, created_at | PK id; FK user_id, replaced_by -> refresh_tokens | UQ token_hash; (user_id) |
| login_failures | id, email text, ip text, created_at | PK id | (email, ip, created_at) |
| distributors | id int, code text, name text, region text, district text, hub_lat float8, hub_lng float8, created_at | PK id | UQ code |
| agents | id int, code text, name text, distributor_id int, region text, district text, upazila text null, urban_rural enum(urban,peri_urban,rural), tier smallint(1-3), lat float8, lng float8, cash_capacity numeric, emoney_capacity numeric, opened_on date null, is_active bool, created_at | PK id; FK distributor_id | UQ code; (distributor_id); (region, district) |
| float_snapshots | id bigint, agent_id int, ts, cash_balance numeric, emoney_balance numeric, is_holdout bool | PK id; FK agent_id | UQ (agent_id, ts); (ts) |
| transactions | id bigint, agent_id int, ts, txn_type enum(cash_in,cash_out), amount_bdt numeric, txn_count int, is_holdout bool | PK id; FK agent_id | (agent_id, ts); (ts) |
| events | id int, type enum(salary,eid,hat_bazar,weather,holiday), name_en text, name_bn text, starts_at, ends_at, district text null, intensity numeric | PK id | (starts_at, ends_at); (district) |
| weather_daily | district text, date date, rain_mm numeric, temp_c numeric, severe bool | PK (district, date) | - |
| model_versions | id int, model_name text, version text, trained_at, artifact_sha256 text, metrics jsonb, is_active bool, created_at | PK id | UQ (model_name, version); (is_active) |
| forecasts | id bigint, model_version_id int, agent_id int, float_type enum(cash,emoney), ts (target), horizon_h smallint, q_low, q_mid, q_high numeric, generated_at | PK id; FK model_version_id, agent_id | (agent_id, ts); (agent_id, float_type, ts) |
| forecast_explanations | id bigint, model_version_id int, agent_id int, float_type enum, ts (as-of), window_h smallint, usual_bdt numeric, drivers jsonb ([{factor, impact_bdt, share, facts}], all factors, largest first), generated_at | PK id; FK model_version_id, agent_id | (agent_id, ts) |
| stockout_predictions | id bigint, model_version_id int, agent_id int, float_type enum, ts (as-of), stockout_at null, hours_to_stockout numeric null, confidence numeric, generated_at | PK id; FK model_version_id, agent_id | (agent_id, ts) |
| risk_levels | id bigint, model_version_id int, agent_id int, float_type enum, ts (as-of), horizon_h smallint(6/24/72), level enum(green,amber,red), probability numeric, confidence numeric, shap_top jsonb, generated_at | PK id; FK model_version_id, agent_id | (agent_id, ts); (level) |
| recommendations | id bigint, agent_id int, model_version_id int null, kind enum(add_cash,add_emoney,swap,van), channel enum(swap,top_up,van,self_fetch,urgent_manual) null, van_route_id text null, float_type enum, amount_bdt numeric, deadline_at, rationale jsonb, status enum(open,requested,done,expired), created_at | PK id; FK agent_id, model_version_id | (agent_id, created_at); (agent_id, status) |
| recommendation_requests | id bigint, recommendation_id bigint, requested_by uuid, channel enum null, amount_bdt numeric, status enum(requested,approved,declined,fulfilled,cancelled), decided_by uuid null, note text null, created_at, decided_at null | PK id; FK recommendation_id, requested_by/decided_by -> users | (status); UQ (recommendation_id) WHERE status in (requested,approved,fulfilled) |
| swap_suggestions | id bigint, model_version_id int null, donor_agent_id int, receiver_agent_id int, float_type enum, amount_bdt numeric, distance_km numeric, van_trip_saved bool, score numeric, status enum(pending,approved,rejected), decided_by uuid null, decided_at null, note text null, created_at | PK id; FK model_version_id, donor/receiver -> agents, decided_by -> users; CHECK donor <> receiver | (status); (donor_agent_id); (receiver_agent_id) |
| anomalies | id bigint, model_version_id int, agent_id int, window_start, window_end, score numeric, features jsonb, status enum(open,confirmed,dismissed), reviewed_by uuid null, reviewed_at null, note text null, created_at | PK id; FK model_version_id, agent_id, reviewed_by | (agent_id, window_start); (status, score) |
| impact_results | id int, model_version_id int, scenario enum(model,baseline), distributor_id int null, window_start, window_end (one local day), stockout_hours numeric, value_lost_bdt numeric, value_saved_bdt numeric (baseline lost - this; 0 on baseline), van_trips int, params jsonb (per-float stockout h, turned-away cash-out / cash-in, actions by channel, delivered, n_agents), created_at | PK id; FK model_version_id, distributor_id | (model_version_id, scenario) |
| audit_log | id bigint, user_id uuid, action text, entity_type text, entity_id text, note text, payload jsonb, created_at | PK id; FK user_id | (entity_type, entity_id); (created_at) |
| llm_call_log | id bigint, user_id uuid null, intent enum(copilot,narrate,agent_briefing,distributor_briefing,anomaly_narrative), provider text, model text, lang text, evidence_hash text, prompt_tokens int, completion_tokens int, latency_ms int, generated_by enum(llm,template,replay), guard_result enum(pass,numbers_fail,injection,schema_fail,timeout,error), error text null, created_at | PK id; FK user_id | (created_at desc); (intent, generated_by) |
| llm_cache | key text (sha256 pack+intent+lang), intent enum, response jsonb, provider text, created_at, expires_at | PK key | (expires_at) |
| copilot_messages | id bigint, user_id uuid, agent_id int, role enum(user,assistant), text text, lang text, generated_by enum null, llm_call_id bigint null, created_at | PK id; FK user_id, agent_id, llm_call_id | (user_id, created_at desc) |
| knowledge_docs | id int, slug text, title text, lang enum(bn,en), chunk_idx int, body text, source_path text, checksum text, updated_at | PK id | UQ (slug, lang, chunk_idx) |
| system_meta | key text, value jsonb, updated_at | PK key | - (seed, data_version, clock_mode, sim_now = forecast origin, data_clock, data_clock_status, demo_story, bootstrap_state) |

TF-IDF index for RAG is built in memory at startup from knowledge_docs (no extra service).

## 4. Folder tree

| Path | Contents |
|---|---|
| `run.bat`, `run.sh` | One-command start for judges |
| `docker-compose.yml`, `.env.example` | db, backend, frontend services; env template (no secrets) |
| `docs/` | ARCHITECTURE, LLM_SPEC, DESIGN, IDEA_CHAIN, METHODS, SYNTHETIC_ASSUMPTIONS |
| `scripts/` | Dev helpers (record replay cache, reset db) |
| `backend/Dockerfile`, `backend/entrypoint.sh` | Image + bootstrap entrypoint (LF) |
| `backend/app/main.py` | FastAPI app, router mount, startup checks |
| `backend/app/api/v1/` | One router per module (auth, agents, forecast, ..., copilot, briefing, llm, admin, system) |
| `backend/app/services/` | Orchestration: evidence pack, forecast/risk/swap/impact services |
| `backend/app/rules/` | Business rules: thresholds, baseline alerts, swap constraints, risk levels |
| `backend/app/models/` | SQLAlchemy 2 ORM |
| `backend/app/schemas/` | Pydantic v2 request/response |
| `backend/app/core/` | config, security (JWT, bcrypt), db session, deps (role scoping), logging |
| `backend/app/llm/providers/` | anthropic, openai_compatible, replay, template |
| `backend/app/llm/guards/` | injection filter, numbers guard, output schema |
| `backend/app/llm/prompts/` | System prompts per intent (bn/en) |
| `backend/app/llm/rag/` | TF-IDF retriever |
| `backend/app/llm/knowledge/` | Liquidity Playbook *.md (bn+en) |
| `backend/app/llm/cache/demo_replay.json` | Pre-recorded demo answers |
| `backend/ml/data_gen/` | Seeded synthetic generator (agents, hourly txns, events, weather) |
| `backend/ml/features/` | Lags, calendar, event, weather features |
| `backend/ml/training/` | LightGBM quantile, Isolation Forest, backtest (14-day holdout) |
| `backend/ml/inference/` | Load artifacts, predict, stockout |
| `backend/ml/explain/` | SHAP -> factor list |
| `backend/ml/artifacts/` | *.joblib + manifest.json (version, sha256) — committed |
| `backend/bootstrap.py` | Idempotent seed/generate/precompute |
| `backend/migrations/` | Alembic |
| `backend/tests/` | pytest (api, rules, ml, llm) |
| `frontend/Dockerfile`, `frontend/nginx.conf` | Build Vite, serve static, proxy `/api` |
| `frontend/src/app/` | Router, providers, auth guard per role |
| `frontend/src/features/{agent,distributor,admin,copilot,shared}/` | Pages + hooks per area |
| `frontend/src/components/signature/` | VesselGauge, RunwayStrip, CountdownCard, PulseLine, WhyStones, SwapFlow, CopilotSheet, CommandPalette |
| `frontend/src/components/ui/` | Restyled primitives (shadcn base) |
| `frontend/src/lib/` | Axios client, query keys, zod schemas, stores (Zustand) |
| `frontend/src/i18n/{bn,en}.json` | Strings |
| `frontend/src/styles/tokens.css` | DESIGN.md tokens (light + dark) |
| `frontend/public/geo/bd.geojson` | Offline map boundary |

## 5. Fresh-PC bootstrap flow

| # | Step | Where | Action | Success check | On failure |
|---|---|---|---|---|---|
| 1 | run.bat / run.sh | host | Check Docker running; copy `.env.example` -> `.env` if missing | `docker info` ok | Print "Start Docker Desktop" and exit |
| 2 | Build + up | compose | `docker compose up --build -d` (db, backend, frontend) | containers created | Show compose logs |
| 3 | DB up | db | Postgres 16 with named volume | healthcheck `pg_isready` | backend waits (`depends_on: service_healthy`) |
| 4 | Migrate | backend entrypoint | `alembic upgrade head` | head revision recorded | Exit non-zero, logs shown |
| 5 | Seed / generate | `bootstrap.py` | Live clock: no live window yet, other seed/mode/version, or a gap > 14 days -> generate 120 days ending at the current hour. Fixed clock: if `system_meta.data_version` != code version: generate synthetic data (fixed seed), load agents, hourly, events, weather, demo users, playbook docs | row counts > 0, data_version set | Skipped when already current (idempotent) |
| 6 | Artifacts check | `bootstrap.py` | Verify `ml/artifacts/manifest.json` sha256 + model_version, register in model_runs | all hashes match | Retrain from seed (slow path, logged); fail if still missing |
| 6b | Catch-up | `bootstrap.py catch-up` | Live clock: append the hours missed while stopped (24 h batches), anchor a demo story if none lies ahead (DEMO_MODE) | data hour = current hour | Logged; status failed |
| 7 | Precompute | `bootstrap.py` | At the forecast origin (SIM_NOW on the fixed clock, the current hour on the live clock): forecasts, risk, recommendations, swaps, anomalies, impact | rows for active run | Logged; status shows not ready |
| 8 | LLM mode | backend startup | `LLM_PROVIDER=auto`: key -> live; else replay; miss -> template | `/llm/status` | Always degrades to template, never blocks |
| 9 | Serve | backend + frontend | uvicorn :8000; nginx :8080 proxies `/api` | `GET /api/v1/system/status` -> `ready: true` | run script polls up to 180 s, then prints logs |
| 10 | Ready | host | Open `http://localhost:8080`, print demo logins | browser opens | - |

Reset: `run.bat --reset` -> `docker compose down -v`, then steps 1-10. No internet needed except optional LLM key and optional OSM tiles.
