#!/bin/sh
# Bootstrap runs in the background so /api/v1/system/status can report progress.
set -eu

# API worker processes: one per CPU, at least 2, at most 4 (override with WEB_CONCURRENCY).
# Handlers are CPU-bound Python, so one process serves one request at a time per core.
# A container CPU limit (cgroup v2 cpu.max "quota period") counts, not just the host's CPUs.
if [ -z "${WEB_CONCURRENCY:-}" ]; then
  cpus=$(nproc 2>/dev/null || echo 2)
  if [ -r /sys/fs/cgroup/cpu.max ]; then
    read -r quota period < /sys/fs/cgroup/cpu.max || true
    if [ "${quota:-max}" != "max" ] && [ "${period:-0}" -gt 0 ]; then
      limit=$(( (quota + period - 1) / period ))
      if [ "$limit" -lt "$cpus" ]; then cpus=$limit; fi
    fi
  fi
  WEB_CONCURRENCY=$(( cpus < 2 ? 2 : (cpus > 4 ? 4 : cpus) ))
fi
export WEB_CONCURRENCY

./scripts/bootstrap.sh &
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "$WEB_CONCURRENCY" \
  --timeout-graceful-shutdown 10
