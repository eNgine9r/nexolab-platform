#!/usr/bin/env bash
# One exclusive lock across migration, canonical deployment and host recovery.
nexolab_acquire_deployment_lock() {
  local lock_file="$1"
  if [[ -n "${NEXOLAB_INHERITED_DEPLOYMENT_LOCK_FD:-}" ]]; then
    if [[ "$NEXOLAB_INHERITED_DEPLOYMENT_LOCK_FD" != 9 \
      || ! "/proc/$$/fd/9" -ef "$lock_file" ]]; then
      echo 'ERROR: inherited deployment lock descriptor does not match the canonical lock file.' >&2
      return 64
    fi
  else
    exec 9>"$lock_file"
  fi
  if ! flock -n 9; then
    echo 'ERROR: another NEXOLAB deployment, migration or recovery operation is running.' >&2
    return 75
  fi
}
