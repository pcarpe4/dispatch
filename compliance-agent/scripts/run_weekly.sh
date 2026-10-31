#!/usr/bin/env bash
# Weekly compliance run wrapper for cron / OpenShift Job.
set -euo pipefail
INPUT_DIR="${INPUT_DIR:-./data/raw}"
WEEK="${WEEK_ID:-}"
ARGS=(--input-dir "$INPUT_DIR")
if [[ -n "$WEEK" ]]; then
  ARGS+=(--week "$WEEK")
fi
exec python -m agent "${ARGS[@]}"
