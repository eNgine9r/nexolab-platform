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
