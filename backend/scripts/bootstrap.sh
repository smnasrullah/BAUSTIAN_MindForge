#!/bin/sh
# wait for db -> migrate -> seed if needed -> train if artifacts missing/invalid
# -> register model + precompute forecast cache -> ready.
# Progress is written to $BOOTSTRAP_STATE_FILE and reported by /api/v1/system/status.
set -u

STATE_FILE="${BOOTSTRAP_STATE_FILE:-/tmp/agentpulse_bootstrap_state}"

state() {
  echo "$1" > "$STATE_FILE"
  echo "[bootstrap] state=$1"
}

step() {
  name="$1"
  shift
  state "$name"
  started=$(date +%s)
  if ! "$@"; then
    state failed
    exit 1
  fi
  echo "[bootstrap] $name took $(( $(date +%s) - started ))s"
}

cd "$(dirname "$0")/.." || exit 1

state starting
step waiting_for_db python bootstrap.py wait-db
step migrating alembic upgrade head

if python bootstrap.py needs-seed; then
  step seeding python bootstrap.py seed
fi

# Create-only: demo helper logins for agents of the synthetic data (also on an existing DB).
python bootstrap.py seed-helpers || echo "[bootstrap] warning: helper logins not created"

# Live clock: append the hours missed while stopped (no-op on the fixed clock).
step seeding python bootstrap.py catch-up

if python bootstrap.py needs-train; then
  step training python bootstrap.py train
fi

step precomputing python bootstrap.py precompute

step finalizing python bootstrap.py mark-ready
state ready
