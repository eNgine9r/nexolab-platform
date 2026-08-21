#!/usr/bin/env bash

nexolab_frontend_candidate_group_has_live_processes() {
  local pgid=$1
  local process_table

  if ! process_table="$(ps -eo pgid=,stat= 2>/dev/null)"; then
    return 0
  fi

  awk -v pgid="$pgid" '
    $1 == pgid && $2 !~ /^Z/ { live = 1 }
    END { exit live ? 0 : 1 }
  ' <<<"$process_table"
}

# The deployment script only waits for the tracked candidate child. Keep that
# reap bounded so a child stuck in uninterruptible I/O cannot hang cleanup after
# the TERM -> KILL escalation window. Other wait forms retain Bash semantics.
wait() {
  local pid=${1:-}
  local attempt

  if (($# != 1)) || [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    builtin wait "$@"
    return $?
  fi

  for attempt in $(seq 1 10); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      builtin wait "$pid"
      return $?
    fi
    sleep 0.1
  done

  return 124
}
