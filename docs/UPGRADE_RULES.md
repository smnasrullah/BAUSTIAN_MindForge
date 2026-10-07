# Upgrade Rules (read by every fix / van prompt)

Every session follows these rules. They extend CLAUDE.md and never relax it.

## Safety
- No `git add`, `commit`, `stash`, `reset`, `checkout`, `switch`, `clean`, `restore` or `push`. Leave all changes uncommitted.
- Never open, print or log `.env` or any key. Never call a live LLM; tests use mocked providers and the template path.
- Never run `run.bat --reset`. Only stop processes you started, by exact PID. Never delete Docker volumes, the main database or local data.
- Anything that mutates data, trains, regenerates, or generates load runs ONLY on the isolated compose project `agentpulse-verify` (docker-compose.verify.yml, ports 18000/15173). Every compose command that can remove anything uses `-p agentpulse-verify`. Run check.ps1 with `$env:COMPOSE_PROJECT_NAME='agentpulse-verify'`. Against the main stack only read-only checks are allowed.
- Training that writes `backend/ml/artifacts`: first copy the current artifacts to `D:\Backup\agentpulse_artifacts_<phase>` and report the path.

## Quality
- Never weaken, skip, delete or loosen a test or a gate. API changes are additive only (new fields or endpoints).
- No tuning on the blind test period. Thresholds, contamination and cuts are chosen on train/validation only, and the blind test is scored once at the end.
- If a change makes a metric worse, keep the old behaviour as default and report it. Never invent a number. All results are labelled "synthetic data".
- Rules in `app/rules`, ML in `ml/`, LLM in `app/llm`. The LLM writes language only.
- New dependency only if truly needed: justify it in docs/DECISIONS.md and pin the version.

## Efficiency (token saving)
- Before using a file name from a report or prompt, verify that it exists (Glob/Grep). Do not read whole large files; use targeted views.
- Long commands run in the background with a log file. Do not poll in a loop; wait for the notification.
- Run only the checks for the files you touched while working. Run `-Slow` and `-Up -E2E` at most once, at the end of the phase.
- After 2 failed attempts at the same issue, log it as open in docs/UPGRADE_PROGRESS.md and move on.

## Bookkeeping
- docs/UPGRADE_PROGRESS.md: one section per phase (max 25 lines each) with state todo/doing/done, a one-line result, the duration, and every command over 2 minutes with its time. If the phase is already in progress, continue from the first unfinished item.
- docs/DECISIONS.md: each decision has what, why and the alternative. Use the next free ID in the series (F for fixes, V for van).

## FINAL REPORT (simple English, for a beginner)
1. Status per item: ALL OK / PARTLY / NOT OK, one line each.
2. Before/after table of the measured numbers (only measured ones).
3. Changed and new files (from `git status --short`; nothing committed) and any backup path.
4. NOT FIXED AND REMAINING PROBLEMS: numbered, each with severity (high/medium/low), how to see it, and what to do next. If none, write "No remaining problems". Do not soften.
5. Decisions made for me.
6. What was verified, and what I must check by hand in the browser.
