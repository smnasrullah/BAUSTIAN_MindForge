# Van Route Optimizer (F14): Spec

Single source of truth for the van phases (V1-V3). Repo conventions win over this file: if a path or name here conflicts with the code, follow the code and record the change in docs/DECISIONS.md.

## 1. Goal
For each distributor, produce a plan that the distributor approves or rejects. The plan decides which agents get cash by van, in what order and by which van, and minimises the total cost in BDT while respecting capacity, deadlines, fairness and safety. Nothing moves money. Approve/reject needs a mandatory note, which goes to audit_log.

## 2. Principles
- The optimizer is a pure, deterministic function under `app/rules/van_routing/` (same rule as swap matching). ML only supplies inputs. The LLM only words the explanation.
- It uses the clock service (`app/core/clock.py`), never SIM_NOW directly. It is solved on demand with a time limit and cached by input hash. It NEVER runs inside the hourly tick.
- Every number is traceable: each stop stores why it was included, dropped or delayed. The distance source is always labelled (`road_cache` or `estimate`).

## 3. Inputs
- Depot: the existing `distributors.hub_lat/hub_lng` (backend/app/models/org.py). Do not add a new depot column unless the hub is missing.
- Each agent that needs cash: amount (red risk: q90 shortfall, amber: q50), deadline (the time the stockout probability crosses a configurable limit), lost value per stockout hour (from the impact model), group (urban/rural, tier), and status. Agents covered by an approved or pending swap are excluded.
- Vehicles: count, cash capacity, max shift hours, cost per km, fixed trip cost, minutes per stop. All of these are configurable and documented in SYNTHETIC_ASSUMPTIONS.md.
- Travel matrix with time multipliers for Eid, rain and hat-bazar days (from the existing events and weather tables).

## 4. Method
- Swap first: exclude agents already served by a swap.
- Objective (BDT): van cost (fixed + km + minutes), plus a lost-value penalty for lateness (soft time windows), plus a skip penalty (disjunction). A stop is dropped only if serving it costs more than its value, and it gets a reason: `swap_suggested`, `cost_gt_value` or `capacity`.
- Solver: OR-Tools capacitated routing with soft windows and optional stops, fixed seed, time limit (default 10 s). Fallback: nearest-neighbour + 2-opt when OR-Tools is unavailable or times out, flagged `solver: fallback` in the result. OR-Tools is a new dependency: pin it, justify it in DECISIONS.md, and make sure the image still builds offline after the first build.
- Robustness: the ETA is shown as a range. After solving, compute the probability that each agent stocks out before the van arrives, and flag the stops above the limit.
- Fairness guard: per-group bounds on maximum wait and minimum service rate. Report the service rate by group.
- Safety: a per-van cash cap. Pick randomly (seeded) among near-optimal routes within 3% of the best cost. Route details are visible only to the distributor; agents see only their time window.
- Stability: stops departing within the freeze window are frozen. The distributor can lock, force-include or exclude a stop. Re-plan only on a meaningful input change (input hash).
- Stretch (V-later, only after core passes): pickup-and-delivery, mixed vehicles, joint swap + van, driver view.

## 5. Road distance
`backend/scripts/build_road_cache.py` is dev only and needs internet. It snaps synthetic coordinates to the nearest road with public OSRM, builds the time/distance matrix plus polylines for the depot-agent legs, and saves small committed JSON in `backend/data/road_cache/` (keep it under 5 MB). At runtime it never calls the internet. A missing pair falls back to haversine x road factor (default 1.35), labelled `estimate`. If no internet is available when the script runs, ship the fallback only and say so.

## 6. API (role: distributor, own agents only; agents get no route details)
- `POST /api/v1/distributor/van-plans` (horizon_h, vehicles, options) -> plan
- `GET /api/v1/distributor/van-plans/{id}`, `GET /api/v1/distributor/van-plans?status=`
- `POST .../van-plans/{id}/decision` (approve|reject, note required) -> audit_log
- `POST .../van-plans/{id}/stops/{stop_id}/lock|include|exclude`
- `POST .../van-plans/{id}/stops/{stop_id}/delivered` (plan-vs-actual feedback)
- `GET .../van-plans/{id}/narrative?lang=bn|en`: LLM wording from an evidence pack, template fallback, numbers guard, generated_by label
- `GET /api/v1/impact/van-comparison`
Every response carries model_version, generated_at and distance_source.

## 7. Database (next free migration number, linear chain)
- `van_plans`: distributor_id, clock_origin, params JSON, objective breakdown JSON, status, input_hash, distance_source, solver, model_version, created_by, timestamps.
- `van_routes`: plan_id, vehicle_no, km, minutes, cash_load, cost_bdt.
- `van_stops`: route_id, seq, agent_id, amount, eta_lo, eta_hi, deadline, penalty_bdt, source_quantile, stockout_before_arrival_p, status, reason.
Decisions use the existing audit_log.

## 8. Files (follow the existing layout)
```text
backend/app/rules/van_routing/  models.py cost.py matrix.py solver.py heuristics.py fairness.py safety.py stability.py
backend/app/services/           van_plan.py van_geometry.py
backend/app/api/v1/van_plans.py  backend/app/schemas/van_plan.py  backend/app/models/van_plan.py
backend/app/llm/                van narrative template + evidence pack (existing templates/packs pattern)
backend/ml/van/                 backtest.py baselines.py sensitivity.py
backend/data/road_cache/        matrix + geometry JSON (committed)
backend/scripts/build_road_cache.py
backend/tests/                  test_van_rules_*.py test_van_plans_api.py test_van_eval.py (slow)
frontend/src/features/distributor/vanRoutes/  VanRoutesPage PlanControls RouteMap StopList SavingsPanel FairnessPanel ApproveDialog BeforeAfterToggle (+ *.test.tsx)
frontend/src/api/vanPlans.ts    i18n bn/en keys vanRoutes.*
e2e/routes.ts (+ /distributor/van-routes)  e2e/tests/van-routes.spec.ts
docs/METHODS.md, SYNTHETIC_ASSUMPTIONS.md, DECISIONS.md, UPGRADE_PROGRESS.md, JUDGING_MAP.md
```

## 9. Frontend `/distributor/van-routes` (docs/DESIGN.md)
A MapLibre map (the existing offline setup used by the control room) with numbered stops and route lines in route colours, not risk colours. It also has: a before/after toggle (separate trips vs optimised); controls for vans, capacity and cash cap that re-solve on change; a stop list with ETA range and reason; a savings panel (km, trips, BDT, stockout hours); a fairness panel; a "why this order?" narrative; and an approve/reject dialog with a mandatory note. Skeleton, empty and error-with-retry states; bn/en; reduced motion; 390 px works (map above the list).

## 10. Evaluation (held-out period, synthetic data)
Compare four policies: A) a separate trip for every agent, B) nearest-neighbour, C) hard-deadline OR-Tools, D) the full model. Metrics: km, trips, total BDT cost, stockout hours, lost value, deadline hit rate, service rate by group, and solve time. Use at least 5 seeds with intervals, plus sensitivity on road factor, fuel cost and delivery reliability. Do not claim a saving before it is measured; if D is not better than C, say so.

## 11. Tests
- Every required stop is served or has a drop reason.
- Capacity and the cash cap are never exceeded.
- Optimised cost <= the separate-trips cost.
- The soft-window penalty is applied.
- The result is deterministic for a fixed seed.
- Empty, single-agent and infeasible cases work.
- The fairness bounds hold.
- Role scoping holds, and the decision writes audit_log.
- A cache miss is labelled `estimate`.
- The narrative falls back to the template.
- The solve finishes under the time limit.
- The hourly tick does not include van solving.
