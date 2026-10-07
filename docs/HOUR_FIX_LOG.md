# Hour fix log
Start: 2026-10-06T15:39:48
- 15:46 FIX1 /login first-load JS: LoginForm no longer imports zod/zodResolver (hand-written resolver, same message keys and email regex) -> files: frontend/src/features/auth/LoginForm.tsx, loginResolver.ts (new), loginResolver.test.ts (new). Login route extra 73.1 -> 49.6 KB gz; /login total about 256,013 B -> about 231,500 B (initial 176.5 KB unchanged). Backup: %TEMP%\hourfix_backup.
- 15:54 FIX2 ruff: `ruff check .` already clean (ml_benchmark.py import order fixed earlier); no change.
- 15:54 FIX3 API types regenerated with scripts/gen-api.ps1 (frontend/openapi.json, src/api/schema.d.ts); tsc clean, no hand edits. Large diff = schema was stale vs backend work.
- 16:01 FIX4 /admin/overview 18 -> 13 SQL queries: 6 per-role count queries replaced by one GROUP BY (backend/app/services/admin_overview.py; test_admin_api.py::test_overview gained 2 asserts). test passes.
- 16:00 MEASURED forced tick (24 s, all caches invalidated, verify stack): 4 read endpoints p95 during 150 s = 13-39 ms, max 190 ms, 0 errors -> no tick isolation needed.
- 16:14 VERIFY: check.ps1 -Frontend pass (tsc, eslint, vitest); verify stack rebuilt once; security.spec + sweep.spec 16/16 pass; /login 231,922 B, / 229,818 B (Playwright, gzip per response); bench after: 64 endpoints, 0 over budget, max 15 queries; backend log 0 errors.

## Problem-relevance upgrade
Start: 2026-10-07T09:17:07
- 09:27 PHASE2 done: stress knob BUFFER_FACTOR (backend/scripts/incidence_sensitivity.py), levels 0.32/1.03/2.99% measured on agentpulse-verify fixed-clock volume; AI 75h/219h/697h; JSON saved. Phase 1 docs next.
- 09:26 PHASE1 done: PROBLEM_EVIDENCE(.md/_BN.md), data/field csvs, opportunity_sizing.py, links in IDEA_CHAIN/JUDGING_MAP/README/DEMO_SCRIPT.
- 09:29 PHASE3a done: GET /evidence/pain-points (+schemas, service, 11 tests pass, ruff clean), compose mounts data/field read-only.
- 09:44 PHASE3b+4 done: /distributor/discovery page, route, e2e/routes.ts, bn/en, vitest; check.ps1 -Frontend pass; ruff + test_evidence_api (11) pass. Not run: e2e, -Full, -Slow.
