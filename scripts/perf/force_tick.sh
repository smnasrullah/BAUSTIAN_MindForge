#!/usr/bin/env bash
# Verify project only (synthetic data): make the next manual tick recompute every cache, then
# request it, wait for it and print its status. Usage: scripts/perf/force_tick.sh [--midnight]
#   --midnight also clears the impact/fairness keys (what the first tick after midnight sees).
set -euo pipefail
P="docker compose -p agentpulse-verify"
API="${API:-http://localhost:18000/api/v1}"
keys="'forecast_cache','risk_cache','rebalance_cache','anomaly_cache'"
if [ "${1:-}" = "--midnight" ]; then keys="$keys,'impact_cache','fairness_cache'"; fi
sql() { $P exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"$1\""; }
sql "update system_meta set value = '{\\\"invalidated\\\": true}'::json where key in ($keys)"
tok=$(curl -s -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d '{"email":"admin@agentpulse.demo","password":"admin-demo-2026"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
before=$(sql "select value::json->'last_tick'->>'started_at' from system_meta where key='data_clock_status'")
curl -s -X POST "$API/admin/clock/tick" -H "authorization: Bearer $tok" >/dev/null
for _ in $(seq 1 120); do
  now=$(sql "select value::json->'last_tick'->>'started_at' from system_meta where key='data_clock_status'")
  [ "$now" != "$before" ] && break
  sleep 5
done
sql "select value::text from system_meta where key='data_clock_status'"
