#!/bin/sh
# OpenAPI fuzzing with Schemathesis against the VERIFY stack only (it creates and changes data).
#   sh scripts/perf/fuzz.sh [max-examples]     -> scripts/perf/out/fuzz_<role>.txt
# One run per role with that role's token. Excluded: operations that would end the test
# sessions or lock the demo accounts (logout, password change, refresh, logins, admin user edits)
# and the hourly-limited public forms (signup, password reset): those have their own tests.
set -u
N=${1:-25}
NET=agentpulse-verify_default
OUT=scripts/perf/out
mkdir -p "$OUT"
EXCLUDE='/auth/(logout|change-password|refresh|login|demo-login|signup|forgot-password|reset-password)|/admin/users/\{user_id\}'
CHECKS=not_a_server_error,response_schema_conformance,status_code_conformance,content_type_conformance,response_headers_conformance

for role in ${ROLES:-agent distributor admin}; do
  token=$(curl -s -X POST localhost:18000/api/v1/auth/demo-login -H 'content-type: application/json' \
    -d "{\"role\":\"$role\"}" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
  MSYS_NO_PATHCONV=1 docker run --rm --network "$NET" schemathesis/schemathesis:stable run \
    http://backend:8000/openapi.json --url http://backend:8000 \
    -H "Authorization: Bearer $token" --checks "$CHECKS" -n "$N" -w 4 \
    --exclude-path-regex "$EXCLUDE" --request-timeout 10 --generation-deterministic \
    > "$OUT/fuzz_$role.txt" 2>&1
  echo "$role exit $? -> $OUT/fuzz_$role.txt"
done
