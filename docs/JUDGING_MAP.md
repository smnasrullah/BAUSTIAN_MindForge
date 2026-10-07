# Judging Map

Maps the stated rubric (relevance 20, AI/ML depth 20, impact 20, prototype 15, innovation 10,
scalability 10, responsible AI 5) to concrete, checkable evidence in this repo — file paths,
routes, and the numbers behind them. Every number here is also in docs/METHODS.md or
docs/IDEA_CHAIN.md; nothing below is restated with different figures.

## Relevance — 20

Track 05, Merchant & Agent Intelligence: MFS agents running out of cash or e-money turn customers
away; today's response is reactive fixed-threshold alerts and ad-hoc van trips.

- Problem statement and framing: docs/IDEA_CHAIN.md (steps 1-3).
- Problem relevance evidence: docs/PROBLEM_EVIDENCE.md (public agent and MFS figures with years and caveats, replenishment channels marked ASSUMPTION, opportunity sizing), docs/INCIDENCE_SENSITIVITY.md (results at 0.32 / 1.03 / 2.99% baseline incidence), data/field/ (interview template; 0 interviews done yet).
- The product answers the guideline's own "good project test" directly: *what happened* (stockout
  predicted for 3:40 PM), *why risky* (salary day, 2.3x cash-out), *what next* (swap with a nearby
  agent, distributor approves) — docs/IDEA_CHAIN.md, last line; live in docs/DEMO_SCRIPT.md.
- Two real users served, not one: the agent app (forecast, countdown, what-if, copilot) and the
  distributor control-room (map, swap queue, anomalies, impact) — docs/ARCHITECTURE.md §1.

## AI/ML depth — 20

Five distinct, purpose-fit methods, not one model wearing different hats:

| Method | Used for | Why this method | Code |
|---|---|---|---|
| LightGBM quantile regression (6 boosters: cash/e-money x q10/q50/q90) | Demand forecast (F1) | Fast on CPU, native quantile loss gives an uncertainty band for free, pairs with exact TreeSHAP | `backend/ml/training/train.py` |
| Monte Carlo over the quantile paths (2,000 paths, Gaussian copula ρ=0.6) | Time-to-stockout + confidence (F2) | A point forecast can't answer "when," a band needs simulation to get a distribution of first-passage times | `backend/ml/inference/stockout.py` |
| Exact TreeSHAP (`pred_contrib`) | "Why?" explanation (F7) | Same values as `shap.TreeExplainer` with no extra dependency; grouped into named factors (salary, eid, rain, ...) | `backend/ml/explain/` |
| `scipy.optimize.linear_sum_assignment` | Agent-to-agent swap matching (F5) | Swap matching is a bipartite assignment problem (minimise total distance over feasible donor/receiver pairs); an optimiser is the correct tool, not a heuristic | `backend/app/rules/swap_rules.py` |
| Isolation Forest, one per peer group + one global, on peer-relative robust-z features | Agent risk / anomaly detection (F9) | Unsupervised, no labelled fraud data needed; peer-relative features cancel market-wide shifts (Eid, salary) so flags are agent-specific, not calendar noise | `backend/ml/training/anomaly.py` |
| OR-Tools capacitated routing, soft deadlines, optional stops (BDT objective) + fairness guard | Van route plan (F14) | Which agents get cash by van, in what order, by which van: a vehicle-routing problem; the forecast supplies amount, deadline and stockout curve, the rules decide, a human approves | `backend/app/rules/van_routing/` |
| LLM + TF-IDF RAG (provider-agnostic) | Wording only: copilot, explanations, briefings, anomaly narrative | Deliberately the smallest role an LLM can have: it never computes a number or makes a decision (docs/LLM_SPEC.md) | `backend/app/llm/` |

Held out and measured, not asserted:
- Forecast beats the same-hour-last-week baseline on both targets (MAE skill 26-28%) — gated by a
  test, not just reported (docs/METHODS.md §2).
- Anomaly detector evaluated against injected labelled anomalies on the holdout: precision 0.96,
  recall 0.73 (agent-level 0.80/0.80) — docs/METHODS.md §3.
- Fairness measured, not assumed: nMAE and stockout recall by urban/rural, tier, region
  (docs/METHODS.md §6) — recall gap only 1.3-1.4 points across groups.

## Impact — 20

14-day held-out backtest, 300 synthetic agents, counterfactual replay (docs/METHODS.md §3,
`GET /impact/summary`):

| Scenario | Stockout hours | Value turned away | Van trips |
|---|---|---|---|
| Fixed 20%-of-capacity alert (baseline) | 322 | 2,813,340 BDT | 786 |
| AI: forecast + recommendation + swaps | **76 (-76%)** | 761,050 BDT (**2.05M BDT saved**) | 1,065 |

Honestly reported trade-off, not hidden: the AI uses +279 more van trips for that service level;
at the AI's own van budget the fixed rule would still have ~207 stockout hours (131 more than the
AI's 76) — the "equal van budget" comparison in docs/METHODS.md §3, so the gain isn't just "more
vans."

Van route optimizer (F14), 5 synthetic seeds, held-out days, routing quality only
(docs/METHODS.md "Van evaluation V3", `GET /impact/van-comparison`): the full model costs
13.97 M BDT less per seed than hard-deadline OR-Tools (lower on 5 of 5 seeds), but more than
one separate trip per agent (+6.35 M BDT), because that baseline has no fleet limit while the
plan has 2 vans and drops about 99 agents per seed for capacity. Reported, not hidden.

## Prototype — 15

Not a slide deck: a working 3-tier app, one command, no manual setup.

- `run.bat` / `./run.sh` -> Docker Desktop only, builds, migrates, seeds, trains/verifies ML
  artifacts, precomputes, and opens the app — docs/ARCHITECTURE.md §5 (bootstrap flow).
- All 12 features + the LLM layer implemented end to end (forecast through to the responsible-AI
  page) — docs/ARCHITECTURE.md §1 sitemap, docs/PRODUCT_CHECKLIST.md.
- Automated gates: `scripts/check.ps1` (ruff, pytest, tsc, eslint, vitest) and `-E2E` (Playwright:
  route smoke, axe accessibility, mobile + desktop layout, bundle budget) — docs/COMMANDS.md.
- Degrades gracefully with zero internet/API key after the first build: LLM falls back
  replay -> template; the demo is identical either way (docs/DEMO_SCRIPT.md).

## Innovation — 10

- Agent-to-agent swap matching as a first-class recommendation channel, not just "ask the
  distributor for more cash" — ranked against top-up, van, self-fetch and urgent-manual by cost
  and ETA, with a human handshake on both sides (docs/METHODS.md §3, `backend/app/rules/channel_rules.py`).
- Deterministic, pre-LLM intent routing for the copilot (`backend/app/llm/copilot/intents.py`):
  prompt-injection and cross-agent requests are refused by regex before any model call, so a
  jailbroken LLM response is structurally impossible for those cases, not just discouraged by a
  system prompt.
- Replay-mode LLM wording: a pre-recorded cache keyed by the evidence-pack hash
  (`backend/app/llm/cache/demo_replay.json`) means judges without an API key still hear real,
  previously-live LLM wording for the demo scenario instead of generic canned text.
- Peer-relative (not population-relative) anomaly features, so a market-wide shift like a salary
  day or Eid doesn't itself look like fraud (docs/METHODS.md §3).

## Scalability — 10

- Modular monolith with clean seams (`backend/app/rules` vs `backend/ml` vs `backend/app/llm`,
  never mixed — CLAUDE.md "Hard rules"); each can become its own service without a rewrite.
- Named path to real data: "same API contract can ingest upay data via an adapter; shadow mode;
  governed anonymised data; retrain + drift monitoring; human approval retained" — docs/IDEA_CHAIN.md
  step 9, expanded in docs/PATH_TO_PRODUCTION.md.
- Model serving is already decoupled from training: precomputed caches, versioned artifacts
  (`backend/ml/artifacts/manifest.json`, sha256-checked), the API only ever reads a cache — scales
  by adding precompute workers, not by making requests slower.
- LLM cost control built in from day one: daily call cap, per-user rate limit, response cache
  keyed by evidence-pack hash, timeout + 1 retry then template — docs/LLM_SPEC.md §4.

## Responsible AI — 5

- Advisory only, enforced structurally: no endpoint moves money; every swap, recommendation
  request and anomaly review needs a human decision with a required note, written to `audit_log`
  — docs/METHODS.md §3, `backend/app/services/`.
- `HoldToApprove`: a 1-second deliberate press-and-hold for every approval, not a single click
  (`frontend/src/components/signature/HoldToApprove.tsx`) — releasing early shakes and approves
  nothing.
- Every number traced to its source on screen: "Model prediction" / "AI-generated wording" /
  "Template wording" chips kept visually apart (docs/PRODUCT_CHECKLIST.md §4,
  `frontend/src/components/signature/WhyStones.tsx`).
- Fairness, limitations and the model card are a page in the running app, not a PDF appendix:
  `/responsible-ai` (`GET /responsible-ai/fairness`, `GET /responsible-ai/model-card`) — F12.
- Full checklist with implementation pointers: docs/RESPONSIBLE_AI_CHECKLIST.md.
