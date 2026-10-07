# Hardening progress

Branch `hardening-pass` (from `main` 29f945c). Isolated stack: project `agentpulse-verify`
(`docker-compose.verify.yml`, ports 18000/15173). Numbers: docs/PERFORMANCE.md.
Decisions: docs/DECISIONS.md.

| Phase | State | Result |
|---|---|---|
| 0 Baseline | done | verify stack up (fresh DB ready in 189 s, images cached); 99 API operations, 50 routes |
| 1 Measure | done | API p95 <= 74 ms single client; 50 users: 47 req/s, p95 1.72 s; cold LCP 10 s |
| 2 Fix performance | done | 50 users realistic: all budgets met; aggressive 121 req/s p95 0.60 s; cold LCP 6.4 s; CLS 0.69 -> 0.10 |
| 3 Bug hunt | done | fuzzing clean (3 roles + auth); 13 bugs fixed with tests; sweep + resilience e2e added |
| 4 Resilience | todo | |
| 5 Security | todo | |
| 6 Quality gates | todo | |
| 7 Judge rehearsal | todo | |
| 8 Docs and wrap-up | todo | |

## Bugs found and fixed so far
- Refresh token: reload or dropped connection during a refresh signed the user out (D7).
- Every page load fetched the notification lists 3 times (useHelpUnread baseline).
- Startup "Preparing" screen flashed on every cold load (D6).
- Layout shifts up to 0.69 on phones (footer, freshness chip, copilot chips, landing hero).
- /admin/llm/usage loaded every logged call; slowed down with use (251 ms at 6,500 rows).
- Flaky vitest (HelpOptOut, ~1 in 2 full runs): 1 s async timeout under parallel load.
- Fuzzing: NUL character in a text filter gave 500 (now 422); spec did not match the API.
- Signup approve and reject at the same time both succeeded (row lock; Postgres test).
- Migration 0020 downgrade failed when a rejected signup had audit rows.
- Network blip during the page-load session check signed users out (D10).
- Phones: distributor/admin top bar 515 px wide on 390 px; chip, cards, settings overflow.
- Double-click created duplicates (event/user forms, mark all read) (D12).
- Change-password form, startup screen and session text were English only (now bn/en).
- formatMoney: "−৳0" for tiny negatives; 99,950 shown as "৳100k" instead of "৳1 lakh".

## Open issues
- Budgets missed: cold LCP on Slow 4G, INP ~210 ms (software rendering), route change
  0.4-1.1 s, aggressive load profile p95 0.60 s. Reasons in docs/PERFORMANCE.md.
- First `check.ps1 -Backend` run reported one failed check whose name was cut from my output;
  every later run passed (watching for a flaky backend test).
