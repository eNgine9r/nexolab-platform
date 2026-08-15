#!/usr/bin/env bash

nexolab_capacity_uint() {
  local name=$1
  local value=$2
  local default_value=$3
  if [[ -z "$value" ]]; then
    value=$default_value
  fi
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    printf 'ERROR: %s must be a non-negative integer, got %q\n' "$name" "$value" >&2
    return 64
  fi
  printf '%s\n' "$value"
}

nexolab_capacity_path_bytes() {
  local path=$1
  if [[ ! -e "$path" ]]; then
    printf '0\n'
    return 0
  fi
  du -sb -- "$path" | awk '{print $1}'
}

nexolab_capacity_free_bytes() {
  local path=$1
  df -PB1 -- "$path" | awk 'NR == 2 {print $4}'
}

nexolab_capacity_scaled_bytes() {
  local bytes=$1
  local percent=$2
  local fixed_overhead=$3
  printf '%s\n' "$(( (bytes * percent + 99) / 100 + fixed_overhead ))"
}

nexolab_capacity_deployment_bytes() {
  local deployments_dir=$1
  local total=0
  local dir base bytes
  [[ -d "$deployments_dir" ]] || {
    printf '0\n'
    return 0
  }
  while IFS= read -r dir; do
    base="$(basename "$dir")"
    [[ "$base" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || continue
    [[ ! -L "$dir" ]] || continue
    bytes="$(nexolab_capacity_path_bytes "$dir")"
    total=$((total + bytes))
  done < <(find "$deployments_dir" -mindepth 1 -maxdepth 1 -type d -print | LC_ALL=C sort)
  printf '%s\n' "$total"
}

nexolab_prune_deployment_evidence() {
  local deployments_dir=$1
  local current_audit_dir=$2
  local protected_count max_count max_age_days max_bytes
  protected_count="$(nexolab_capacity_uint NEXOLAB_DEPLOY_EVIDENCE_PROTECTED_COUNT "${NEXOLAB_DEPLOY_EVIDENCE_PROTECTED_COUNT:-}" 3)" || return $?
  max_count="$(nexolab_capacity_uint NEXOLAB_DEPLOY_EVIDENCE_MAX_COUNT "${NEXOLAB_DEPLOY_EVIDENCE_MAX_COUNT:-}" 12)" || return $?
  max_age_days="$(nexolab_capacity_uint NEXOLAB_DEPLOY_EVIDENCE_MAX_AGE_DAYS "${NEXOLAB_DEPLOY_EVIDENCE_MAX_AGE_DAYS:-}" 30)" || return $?
  max_bytes="$(nexolab_capacity_uint NEXOLAB_DEPLOY_EVIDENCE_MAX_BYTES "${NEXOLAB_DEPLOY_EVIDENCE_MAX_BYTES:-}" 3221225472)" || return $?

  (( max_count >= protected_count )) || {
    printf 'ERROR: deployment evidence max count must be >= protected count\n' >&2
    return 64
  }
  [[ -d "$deployments_dir" ]] || return 0

  local -a dirs=()
  local dir base
  while IFS= read -r dir; do
    base="$(basename "$dir")"
    [[ "$base" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || continue
    [[ ! -L "$dir" ]] || continue
    dirs+=("$dir")
  done < <(find "$deployments_dir" -mindepth 1 -maxdepth 1 -type d -print | LC_ALL=C sort)

  local count=${#dirs[@]}
  (( count > 0 )) || return 0

  local total=0
  local -a sizes=()
  local bytes
  for dir in "${dirs[@]}"; do
    bytes="$(nexolab_capacity_path_bytes "$dir")"
    sizes+=("$bytes")
    total=$((total + bytes))
  done

  local now
  now="$(date +%s)"
  local protected_from=$((count - protected_count))
  (( protected_from < 0 )) && protected_from=0
  local max_count_from=$((count - max_count))
  (( max_count_from < 0 )) && max_count_from=0

  local index mtime age_expired count_expired size_exceeded reason
  for ((index = 0; index < count; index += 1)); do
    dir="${dirs[$index]}"
    [[ "$dir" != "$current_audit_dir" ]] || continue
    [[ ! -e "$dir/.nexolab-preserve" ]] || continue
    (( index < protected_from )) || continue

    mtime="$(stat -c %Y -- "$dir")"
    age_expired=false
    count_expired=false
    size_exceeded=false
    if (( max_age_days > 0 && now - mtime > max_age_days * 86400 )); then
      age_expired=true
    fi
    if (( max_count > 0 && index < max_count_from )); then
      count_expired=true
    fi
    if (( max_bytes > 0 && total > max_bytes )); then
      size_exceeded=true
    fi
    if [[ "$age_expired" != true && "$count_expired" != true && "$size_exceeded" != true ]]; then
      continue
    fi

    base="$(basename "$dir")"
    [[ "$base" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
      printf 'ERROR: refusing to prune non-deployment path: %s\n' "$dir" >&2
      return 70
    }
    [[ "$(dirname "$dir")" == "$deployments_dir" ]] || {
      printf 'ERROR: refusing to prune path outside deployment evidence root: %s\n' "$dir" >&2
      return 70
    }

    reason=""
    [[ "$age_expired" == true ]] && reason="${reason}age,"
    [[ "$count_expired" == true ]] && reason="${reason}count,"
    [[ "$size_exceeded" == true ]] && reason="${reason}size,"
    reason="${reason%,}"
    bytes="${sizes[$index]}"
    if ! rm -rf -- "$dir"; then
      printf 'ERROR: failed to prune classified deployment evidence: %s\n' "$dir" >&2
      return 70
    fi
    if [[ -e "$dir" ]]; then
      printf 'ERROR: classified deployment evidence still exists after prune: %s\n' "$dir" >&2
      return 70
    fi
    total=$((total - bytes))
    printf 'Pruned deployment evidence: %s bytes=%s reason=%s\n' "$dir" "$bytes" "$reason"
  done
}

NEXOLAB_CAPACITY_PG_SOURCE=none
NEXOLAB_CAPACITY_PG_BYTES=0

nexolab_capacity_measure_postgres() {
  local pg_container=$1
  NEXOLAB_CAPACITY_PG_SOURCE=none
  NEXOLAB_CAPACITY_PG_BYTES=0
  [[ -n "$pg_container" ]] || return 0

  local measured
  measured="$(docker exec "$pg_container" sh -ec \
    'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_database_size(current_database());"' \
    2>/dev/null || true)"
  measured="${measured//$'\r'/}"
  measured="${measured//$'\n'/}"
  if [[ "$measured" =~ ^[0-9]+$ ]]; then
    NEXOLAB_CAPACITY_PG_SOURCE=live
    NEXOLAB_CAPACITY_PG_BYTES=$measured
  else
    NEXOLAB_CAPACITY_PG_SOURCE=unavailable
    NEXOLAB_CAPACITY_PG_BYTES=0
  fi
}

nexolab_capacity_preflight() {
  local repo=$1
  local audit_dir=$2
  local pg_container=${3:-}
  local report=$4

  local reserve_bytes build_headroom_bytes metadata_headroom_bytes
  local archive_percent archive_fixed_bytes pg_percent pg_fixed_bytes
  reserve_bytes="$(nexolab_capacity_uint NEXOLAB_DEPLOY_MIN_FREE_RESERVE_BYTES "${NEXOLAB_DEPLOY_MIN_FREE_RESERVE_BYTES:-}" 2147483648)" || return $?
  build_headroom_bytes="$(nexolab_capacity_uint NEXOLAB_DEPLOY_BUILD_HEADROOM_BYTES "${NEXOLAB_DEPLOY_BUILD_HEADROOM_BYTES:-}" 4294967296)" || return $?
  metadata_headroom_bytes="$(nexolab_capacity_uint NEXOLAB_DEPLOY_METADATA_HEADROOM_BYTES "${NEXOLAB_DEPLOY_METADATA_HEADROOM_BYTES:-}" 268435456)" || return $?
  archive_percent="$(nexolab_capacity_uint NEXOLAB_DEPLOY_ARCHIVE_ESTIMATE_PERCENT "${NEXOLAB_DEPLOY_ARCHIVE_ESTIMATE_PERCENT:-}" 110)" || return $?
  archive_fixed_bytes="$(nexolab_capacity_uint NEXOLAB_DEPLOY_ARCHIVE_FIXED_OVERHEAD_BYTES "${NEXOLAB_DEPLOY_ARCHIVE_FIXED_OVERHEAD_BYTES:-}" 67108864)" || return $?
  pg_percent="$(nexolab_capacity_uint NEXOLAB_DEPLOY_POSTGRES_ESTIMATE_PERCENT "${NEXOLAB_DEPLOY_POSTGRES_ESTIMATE_PERCENT:-}" 110)" || return $?
  pg_fixed_bytes="$(nexolab_capacity_uint NEXOLAB_DEPLOY_POSTGRES_FIXED_OVERHEAD_BYTES "${NEXOLAB_DEPLOY_POSTGRES_FIXED_OVERHEAD_BYTES:-}" 67108864)" || return $?

  local evidence_bytes=0 archive_estimate=0
  if [[ -d "$repo/runtime/evidence" ]]; then
    evidence_bytes="$(nexolab_capacity_path_bytes "$repo/runtime/evidence")"
    archive_estimate="$(nexolab_capacity_scaled_bytes "$evidence_bytes" "$archive_percent" "$archive_fixed_bytes")"
  fi

  nexolab_capacity_measure_postgres "$pg_container"
  local pg_estimate=0 pg_measurement_failed=false
  [[ "$NEXOLAB_CAPACITY_PG_SOURCE" != unavailable ]] || pg_measurement_failed=true
  if (( NEXOLAB_CAPACITY_PG_BYTES > 0 )); then
    pg_estimate="$(nexolab_capacity_scaled_bytes "$NEXOLAB_CAPACITY_PG_BYTES" "$pg_percent" "$pg_fixed_bytes")"
  fi

  local free_bytes required_bytes deployment_bytes npm_cache_bytes=0 npm_cache_path=""
  free_bytes="$(nexolab_capacity_free_bytes "$repo")"
  [[ "$free_bytes" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: could not determine free bytes for %s\n' "$repo" >&2
    return 70
  }
  required_bytes=$((reserve_bytes + build_headroom_bytes + metadata_headroom_bytes + archive_estimate + pg_estimate))
  deployment_bytes="$(nexolab_capacity_deployment_bytes "$repo/runtime/deployments")"

  if command -v npm >/dev/null 2>&1; then
    npm_cache_path="$(npm config get cache 2>/dev/null || true)"
    if [[ -n "$npm_cache_path" && -d "$npm_cache_path" ]]; then
      npm_cache_bytes="$(nexolab_capacity_path_bytes "$npm_cache_path")"
    fi
  fi

  local status=PASS required_bytes_is_complete=true error_code=""
  (( free_bytes >= required_bytes )) || status=FAIL
  if [[ "$pg_measurement_failed" == true ]]; then
    status=FAIL
    required_bytes_is_complete=false
    error_code=postgresql-size-unavailable
  fi
  mkdir -p "$(dirname "$report")"
  {
    printf 'status=%s\n' "$status"
    printf 'free_bytes=%s\n' "$free_bytes"
    printf 'required_bytes=%s\n' "$required_bytes"
    printf 'required_bytes_is_complete=%s\n' "$required_bytes_is_complete"
    printf 'error=%s\n' "$error_code"
    printf 'reserve_bytes=%s\n' "$reserve_bytes"
    printf 'build_headroom_bytes=%s\n' "$build_headroom_bytes"
    printf 'metadata_headroom_bytes=%s\n' "$metadata_headroom_bytes"
    printf 'runtime_evidence_bytes=%s\n' "$evidence_bytes"
    printf 'runtime_evidence_archive_estimate_bytes=%s\n' "$archive_estimate"
    printf 'postgresql_estimate_source=%s\n' "$NEXOLAB_CAPACITY_PG_SOURCE"
    printf 'postgresql_database_bytes=%s\n' "$NEXOLAB_CAPACITY_PG_BYTES"
    printf 'postgresql_backup_estimate_bytes=%s\n' "$pg_estimate"
    printf 'deployment_evidence_bytes=%s\n' "$deployment_bytes"
    printf 'npm_cache_bytes=%s\n' "$npm_cache_bytes"
    printf 'npm_cache_path=%s\n' "$npm_cache_path"
    printf 'automatic_cleanup=runtime/deployments/<timestamp> only\n'
    printf 'protected=runtime/evidence,PostgreSQL,edge-SQLite,MQTT,MinIO,Docker-named-volumes,current-deployment,newest-deployments,.nexolab-preserve\n'
    printf 'manual_review_cache=docker-build-cache,npm-cache\n'
  } > "$report"

  if [[ "$status" != PASS ]]; then
    if [[ "$pg_measurement_failed" == true ]]; then
      printf 'ERROR: PostgreSQL size unavailable; refusing deployment: free_bytes=%s required_without_postgresql_bytes=%s reserve_bytes=%s report=%s\n' \
        "$free_bytes" "$required_bytes" "$reserve_bytes" "$report" >&2
      return 70
    fi
    printf 'ERROR: insufficient deployment capacity: free_bytes=%s required_bytes=%s reserve_bytes=%s report=%s\n' \
      "$free_bytes" "$required_bytes" "$reserve_bytes" "$report" >&2
    return 75
  fi
  printf 'Capacity preflight PASS: free_bytes=%s required_bytes=%s reserve_bytes=%s\n' \
    "$free_bytes" "$required_bytes" "$reserve_bytes"
}

nexolab_capacity_guard_main() {
  set -Eeuo pipefail
  local repo="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
  local audit_dir=""
  local report=""
  local do_prune=false
  while (($# > 0)); do
    case "$1" in
      --repo)
        repo=$2
        shift 2
        ;;
      --audit-dir)
        audit_dir=$2
        shift 2
        ;;
      --report)
        report=$2
        shift 2
        ;;
      --prune)
        do_prune=true
        shift
        ;;
      --help|-h)
        cat <<'EOF_USAGE'
Usage: deploy-capacity-guard.sh --repo PATH --audit-dir PATH [--report PATH] [--prune]
Performs read-only capacity estimation and optional bounded cleanup of old deployment-generated evidence only.
EOF_USAGE
        return 0
        ;;
      *)
        printf 'ERROR: unknown argument: %s\n' "$1" >&2
        return 64
        ;;
    esac
  done
  [[ -n "$audit_dir" ]] || {
    printf 'ERROR: --audit-dir is required\n' >&2
    return 64
  }
  mkdir -p "$audit_dir"
  [[ -n "$report" ]] || report="$audit_dir/capacity-preflight.txt"
  if [[ "$do_prune" == true ]]; then
    nexolab_prune_deployment_evidence "$repo/runtime/deployments" "$audit_dir"
  fi
  local pg_container=""
  if command -v docker >/dev/null 2>&1; then
    pg_container="$(docker ps -q \
      --filter label=com.docker.compose.project=nexolab-central \
      --filter label=com.docker.compose.service=postgres \
      | head -n 1 || true)"
  fi
  nexolab_capacity_preflight "$repo" "$audit_dir" "$pg_container" "$report"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  nexolab_capacity_guard_main "$@"
fi
