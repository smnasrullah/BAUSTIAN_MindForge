#!/bin/sh
# Checks, inside Docker (no local node/python needed). One line per step; failures only.
# Usage: scripts/check.sh [--backend] [--frontend] [--e2e] [--slow] [--full] [--up]
#   (none)      FAST tier: ruff, pytest -m "not slow", tsc, eslint, vitest
#   --backend   ruff + fast pytest        --frontend  tsc + eslint + vitest
#   --slow      pytest -m slow (model training, full synthetic set, ML gate)
#   --e2e       Playwright smoke against the running stack (start it with --up)
#   --up        rebuild app images with the /dev/kit route and start the stack
#   --full      everything: ruff, all pytest, tsc, eslint, vitest, --up, e2e
set -u
cd "$(dirname "$0")/.." || exit 1

BE=0 FE=0 E2E=0 SLOW=0 FULL=0 UP=0
for a in "$@"; do
  case "$a" in
    --backend) BE=1 ;;
    --frontend) FE=1 ;;
    --e2e) E2E=1 ;;
    --slow) SLOW=1 ;;
    --full) FULL=1 ;;
    --up) UP=1 ;;
    *) echo "unknown flag: $a"; exit 2 ;;
  esac
done
if [ $((BE + FE + E2E + SLOW + UP + FULL)) -eq 0 ]; then BE=1; FE=1; fi
if [ "$FULL" -eq 1 ]; then BE=1; FE=1; E2E=1; UP=1; SLOW=0; fi

# --- concurrency lock ------------------------------------------------------------------------
LOCK=scripts/.check.lock
if [ -f "$LOCK" ]; then
  holder=$(head -n 1 "$LOCK" 2>/dev/null)
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null \
     && [ -z "$(find "$LOCK" -mmin +30 2>/dev/null)" ]; then
    echo "BUSY  another check is running (pid $holder). Lock: $LOCK"
    exit 2
  fi
  rm -f "$LOCK" 2>/dev/null
fi
if ! (set -C; echo "$$" >"$LOCK") 2>/dev/null; then
  echo "BUSY  another check just started. Lock: $LOCK"
  exit 2
fi

failed=0
TAG="agentpulse-check-$$"
# Image name prefix = compose project (COMPOSE_PROJECT_NAME=agentpulse-verify: the isolated stack).
PROJ="${COMPOSE_PROJECT_NAME:-agentpulse}"
LOG="$(mktemp)"
trap 'rm -f "$LOG" "$LOCK"' EXIT
trap 'exit 130' INT TERM

remove_stale() {
  docker ps -a --filter name=agentpulse-check- --format '{{.Names}}|{{.RunningFor}}' 2>/dev/null |
    while IFS='|' read -r name for; do
      case "$for" in
        *hour*|*day*|*week*|*month*|*year*) old=1 ;;
        *minutes*) n=${for%% *}; [ "$n" -ge 15 ] 2>/dev/null && old=1 || old=0 ;;
        *) old=0 ;;
      esac
      if [ "$old" -eq 1 ]; then
        docker rm -f "$name" >/dev/null 2>&1
        echo "      removed stale $name"
      fi
    done
}

FAIL_RE='^(FAILED|ERROR) |error TS[0-9]+|^ *[0-9]+:[0-9]+ +error|:[0-9]+:[0-9]+: [A-Z]+[0-9]+|'
FAIL_RE="$FAIL_RE"'\bFAIL\b|^ *[x] |^ *[0-9]+\) |Error:|AssertionError|exit code'

# step NAME TIMEOUT_S CONTAINER_OR_- docker-args...
step() {
  name="$1" tmo="$2" cname="$3"
  shift 3
  start=$(date +%s)
  docker "$@" >"$LOG" 2>&1 &
  pid=$!
  ( sleep "$tmo"; kill "$pid" 2>/dev/null && touch "$LOG.timeout" ) &
  wd=$!
  wait "$pid"
  code=$?
  kill "$wd" 2>/dev/null
  t=$(( $(date +%s) - start ))
  if [ -f "$LOG.timeout" ]; then
    rm -f "$LOG.timeout"
    [ "$cname" != "-" ] && docker rm -f "$cname" >/dev/null 2>&1
    why="timeout ${tmo}s"
    code=124
  else
    why="exit $code"
  fi
  if [ "$code" -eq 0 ]; then
    printf 'PASS  %-12s %5ss\n' "$name" "$t"
    return
  fi
  printf 'FAIL  %-12s %5ss  (%s)\n' "$name" "$t" "$why"
  esc=$(printf '\033')
  sed "s/${esc}\[[0-9;]*m//g" "$LOG" | grep -Ev '^ *(Container|Network|Volume) [^ ]+ ' >"$LOG.f"
  if grep -Eq "$FAIL_RE" "$LOG.f"; then
    grep -E "$FAIL_RE" "$LOG.f" | head -n 30 | sed 's/^/      /'
  else
    tail -n 15 "$LOG.f" | sed 's/^/      /'
  fi
  rm -f "$LOG.f"
  failed=$((failed + 1))
}

tool() {
  name="$1" tmo="$2" svc="$3"
  shift 3
  step "$name" "$tmo" "$TAG-$name" compose --profile tools --profile e2e run --rm --no-deps -T \
    --name "$TAG-$name" "$svc" "$@"
}

# images PROFILE SERVICE FILES... : rebuild only when missing or Dockerfile / deps changed.
images() {
  prof="$1" svc="$2"
  shift 2
  sig=$(cat "$@" 2>/dev/null | cksum | tr -d ' ')
  stamp="scripts/.check-build-$svc.sh.stamp"
  if [ -n "$(docker image ls -q "$PROJ-$svc" 2>/dev/null)" ] \
     && [ "$(cat "$stamp" 2>/dev/null)" = "$sig" ]; then
    return
  fi
  step "build:$svc" 900 - compose --profile "$prof" build -q "$svc"
  [ "$failed" -eq 0 ] && printf '%s' "$sig" >"$stamp"
}

# No secret in git: no tracked .env, no known key shapes, and none of this machine's .env secret
# values in any tracked file. Prints file names only, never a value.
SECRET_SHAPES='sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|'
SECRET_SHAPES="$SECRET_SHAPES"'gh[pousr]_[A-Za-z0-9]{36}|xox[abprs]-[A-Za-z0-9-]{10,}|'
SECRET_SHAPES="$SECRET_SHAPES"'-----BEGIN [A-Z ]*PRIVATE KEY-----'
SECRET_KEYS='^[[:space:]]*(JWT_SECRET|LLM_API_KEY|POSTGRES_PASSWORD|DEMO_[A-Z_]+_PASSWORD)='
secrets() {
  start=$(date +%s)
  if ! command -v git >/dev/null 2>&1; then echo "SKIP  secrets      git not found"; return; fi
  bad=$(
    git ls-files | grep -E '(^|/)\.env(\.|$)' | grep -v '\.example$' | sed 's/^/tracked env file: /'
    git grep -I -l -E -e "$SECRET_SHAPES" 2>/dev/null | sed 's/^/key-shaped string: /'
    if [ -f .env ]; then
      grep -E "$SECRET_KEYS" .env | while IFS= read -r line; do
        key=${line%%=*}; key=$(echo "$key" | tr -d '[:space:]')
        value=$(printf '%s' "${line#*=}" | sed -e 's/^[[:space:]"'"'"']*//' -e 's/[[:space:]"'"'"']*$//')
        published=$(grep -E "^[[:space:]]*$key=" .env.example 2>/dev/null | head -n 1 | cut -d= -f2-)
        # Short values and the published .env.example defaults (demo passwords) are not secrets.
        [ "${#value}" -lt 16 ] && continue
        [ "$value" = "$published" ] && continue
        git grep -I -l -F -e "$value" 2>/dev/null | sed "s/^/value of $key: /"
      done
    fi
  )
  t=$(( $(date +%s) - start ))
  if [ -z "$bad" ]; then printf 'PASS  %-12s %5ss\n' secrets "$t"; return; fi
  printf 'FAIL  %-12s %5ss  (exit 1)\n' secrets "$t"
  printf '%s\n' "$bad" | head -n 30 | sed 's/^/      /'
  failed=$((failed + 1))
}

remove_stale
{ [ "$BE" -eq 1 ] || [ "$E2E" -eq 1 ]; } && secrets
if [ "$BE" -eq 1 ] || [ "$SLOW" -eq 1 ]; then
  images tools backend-tools backend/Dockerfile backend/requirements*.txt
fi
[ "$FE" -eq 1 ] && images tools frontend-tools frontend/Dockerfile frontend/package.json \
  frontend/package-lock.json
[ "$E2E" -eq 1 ] && images e2e e2e e2e/Dockerfile e2e/package.json e2e/package-lock.json
[ "$failed" -eq 0 ] || exit 1

if [ "$BE" -eq 1 ]; then
  tool ruff 60 backend-tools ruff check .
  if [ "$FULL" -eq 1 ]; then
    tool pytest-all "${CHECK_PYTEST_TIMEOUT:-1200}" backend-tools pytest -q -p no:cacheprovider --tb=line -rfE
  else
    tool pytest "${CHECK_PYTEST_TIMEOUT:-300}" backend-tools pytest -q -p no:cacheprovider --tb=line -rfE -m "not slow"
  fi
fi
[ "$SLOW" -eq 1 ] && tool pytest-slow "${CHECK_PYTEST_TIMEOUT:-1200}" backend-tools pytest -q -p no:cacheprovider \
  --tb=line -rfE -m slow
if [ "$FE" -eq 1 ]; then
  tool typecheck 180 frontend-tools npm run -s typecheck
  tool eslint 180 frontend-tools npm run -s lint
  tool vitest 240 frontend-tools npm run -s test
fi
if [ "$UP" -eq 1 ]; then
  # App images built from the working tree, with the dev-only /dev/kit route e2e visits.
  VITE_DEV_KIT=true step up 900 - compose up -d --build --wait db backend frontend
fi
if [ "$E2E" -eq 1 ]; then
  port="${FRONTEND_PORT:-5173}"
  kit=$(docker image inspect "$PROJ-frontend" \
    --format '{{ index .Config.Labels "agentpulse.devkit" }}' 2>/dev/null)
  # `up --wait` returns once /health answers; bootstrap (migrate, precompute) may still run.
  is_ready() {
    curl -fsS --max-time 5 "http://localhost:$port/api/v1/system/status" 2>/dev/null |
      grep -q '"ready": *true'
  }
  waited=0
  until is_ready || [ "$waited" -ge 600 ]; do sleep 3; waited=$((waited + 3)); done
  if ! is_ready; then
    echo "FAIL  e2e          stack not ready; start it with: scripts/check.sh --up"
    failed=$((failed + 1))
  elif [ "$kit" != "true" ]; then
    echo "FAIL  e2e          frontend built without /dev/kit; rebuild with: scripts/check.sh --up"
    failed=$((failed + 1))
  else
    # Known state for reruns without a DB reset (bootstrap.py e2e-fixtures: inbox, lockout).
    before=$failed
    step e2e-seed 60 - compose exec -T backend python bootstrap.py e2e-fixtures
    [ "$failed" -eq "$before" ] && tool e2e 420 e2e
  fi
fi

if [ "$failed" -ne 0 ]; then
  echo "$failed check(s) failed"
  exit 1
fi
echo "All checks passed"
