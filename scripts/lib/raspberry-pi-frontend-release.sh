#!/usr/bin/env bash

NEXOLAB_FRONTEND_ACTIVE_CONTAINER=""
NEXOLAB_FRONTEND_CANDIDATE_DIR=""
NEXOLAB_FRONTEND_CURRENT_LINK=""
NEXOLAB_FRONTEND_PREVIOUS_TARGET=""
NEXOLAB_FRONTEND_RELEASE_DIR=""
NEXOLAB_FRONTEND_ACTIVATED=0

nexolab_frontend_uint() {
  local name=$1 value=$2 default_value=$3
  [[ -n "$value" ]] || value=$default_value
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    printf 'ERROR: %s must be a non-negative integer, got %q\n' "$name" "$value" >&2
    return 64
  fi
  printf '%s\n' "$value"
}

nexolab_frontend_mem_available_kib() {
  if [[ -n "${NEXOLAB_FRONTEND_MEM_AVAILABLE_KIB_OVERRIDE:-}" ]]; then
    printf '%s\n' "$NEXOLAB_FRONTEND_MEM_AVAILABLE_KIB_OVERRIDE"
    return 0
  fi
  awk '$1 == "MemAvailable:" {print $2; exit}' /proc/meminfo
}

nexolab_frontend_swap_free_kib() {
  if [[ -n "${NEXOLAB_FRONTEND_SWAP_FREE_KIB_OVERRIDE:-}" ]]; then
    printf '%s\n' "$NEXOLAB_FRONTEND_SWAP_FREE_KIB_OVERRIDE"
    return 0
  fi
  awk '$1 == "SwapFree:" {print $2; exit}' /proc/meminfo
}

nexolab_frontend_resource_preflight() {
  local report=$1
  local min_mem min_swap mem_available swap_free status
  min_mem="$(nexolab_frontend_uint NEXOLAB_FRONTEND_MIN_MEM_AVAILABLE_KIB "${NEXOLAB_FRONTEND_MIN_MEM_AVAILABLE_KIB:-}" 1572864)" || return $?
  min_swap="$(nexolab_frontend_uint NEXOLAB_FRONTEND_MIN_SWAP_FREE_KIB "${NEXOLAB_FRONTEND_MIN_SWAP_FREE_KIB:-}" 1048576)" || return $?
  mem_available="$(nexolab_frontend_mem_available_kib)"
  swap_free="$(nexolab_frontend_swap_free_kib)"
  [[ "$mem_available" =~ ^[0-9]+$ && "$swap_free" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: unable to measure frontend build memory/swap headroom\n' >&2
    return 70
  }
  status=PASS
  (( mem_available >= min_mem && swap_free >= min_swap )) || status=FAIL
  {
    printf 'status=%s\n' "$status"
    printf 'mem_available_kib=%s\n' "$mem_available"
    printf 'min_mem_available_kib=%s\n' "$min_mem"
    printf 'swap_free_kib=%s\n' "$swap_free"
    printf 'min_swap_free_kib=%s\n' "$min_swap"
  } > "$report"
  [[ "$status" == PASS ]] || return 75
}

nexolab_frontend_competing_processes() {
  if [[ -n "${NEXOLAB_FRONTEND_PROCESS_SNAPSHOT+x}" ]]; then
    printf '%s\n' "$NEXOLAB_FRONTEND_PROCESS_SNAPSHOT"
    return 0
  fi
  python3 - <<'PY'
from pathlib import Path
patterns = (
    "next build",
    "npm run build",
    "playwright test",
    "run-authenticated-dashboard-acceptance.sh",
    "run-refrigeration-browser-acceptance.sh",
)
for path in sorted(Path("/proc").glob("[0-9]*/cmdline")):
    try:
        raw = path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if raw and any(pattern in raw for pattern in patterns):
        print(f"{path.parent.name} {raw}")
PY
}

nexolab_frontend_assert_no_competing_builds() {
  local report=$1 matches
  matches="$(nexolab_frontend_competing_processes)"
  if [[ -n "$matches" ]]; then
    { printf 'status=FAIL\n'; printf '%s\n' "$matches"; } > "$report"
    return 75
  fi
  printf 'status=PASS\n' > "$report"
}

nexolab_frontend_verify_public_contract() {
  local build_root=$1 mode=$2 api_url=$3 websocket_url=$4 auth_provider=$5 organization_id=$6 report=$7
  python3 - "$build_root" "$mode" "$api_url" "$websocket_url" "$auth_provider" "$organization_id" "$report" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
expected = dict(zip(
    ("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL", "NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID"),
    sys.argv[2:7], strict=True,
))
report = Path(sys.argv[7])
build = root / ".next"
if not (build / "BUILD_ID").is_file():
    report.write_text("status=FAIL\nerror=missing-build-id\n", encoding="utf-8")
    raise SystemExit(70)
files = []
for base in (build / "static", build / "server"):
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if path.is_file() and path.suffix in {".js", ".html", ".json", ".rsc"} and not path.name.endswith(".map"):
            try:
                files.append((path, path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                pass

missing_values = []
dynamic_refs = []
for key, value in expected.items():
    if not any(value in text for _, text in files):
        missing_values.append(key)
    dynamic = re.compile(r"(?:env\.|process\.env\.)" + re.escape(key))
    for path, text in files:
        if dynamic.search(text):
            dynamic_refs.append(f"{key}:{path.relative_to(root)}")
            break

status = "PASS" if not missing_values and not dynamic_refs else "FAIL"
lines = [f"status={status}", f"build_id={(build / 'BUILD_ID').read_text().strip()}"]
for key, value in expected.items():
    lines.append(f"{key}={value}")
for key in missing_values:
    lines.append(f"missing_baked_value={key}")
for item in dynamic_refs:
    lines.append(f"dynamic_public_env_ref={item}")
report.write_text("\n".join(lines) + "\n", encoding="utf-8")
raise SystemExit(0 if status == "PASS" else 70)
PY
}
nexolab_frontend_prepare_release_source() {
  local repo=$1 commit=$2 release_dir=$3 root_env=$4
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid frontend release commit: %s\n' "$commit" >&2
    return 64
  }
  [[ ! -e "$release_dir" ]] || {
    printf 'ERROR: frontend release directory already exists: %s\n' "$release_dir" >&2
    return 73
  }
  mkdir -p "$release_dir"
  if ! git -C "$repo" archive --format=tar "$commit" | tar -xf - -C "$release_dir"; then
    rm -rf -- "$release_dir"
    return 70
  fi
  if [[ -f "$root_env" ]]; then
    install -m 0600 "$root_env" "$release_dir/.env.local"
  fi
}

nexolab_frontend_build_release() {
  local release_dir=$1 mode=$2 api_url=$3 websocket_url=$4 auth_provider=$5 organization_id=$6
  local memory_mb cpus image uid gid
  memory_mb="$(nexolab_frontend_uint NEXOLAB_FRONTEND_BUILD_MEMORY_MB "${NEXOLAB_FRONTEND_BUILD_MEMORY_MB:-}" 1536)" || return $?
  cpus="${NEXOLAB_FRONTEND_BUILD_CPUS:-1.0}"
  image="${NEXOLAB_FRONTEND_BUILD_IMAGE:-node:22.23.1-bookworm-slim}"
  uid="$(id -u)"
  gid="$(id -g)"
  docker image inspect "$image" >/dev/null 2>&1 || {
    printf 'ERROR: bounded frontend build image is unavailable locally: %s\n' "$image" >&2
    return 69
  }
  docker run --rm --init \
    --name "nexolab-frontend-build-$$" \
    --user "$uid:$gid" \
    --memory "${memory_mb}m" \
    --memory-swap "${memory_mb}m" \
    --cpus "$cpus" \
    --pids-limit 512 \
    --env HOME=/tmp/nexolab-home \
    --env HUSKY=0 \
    --env NEXT_TELEMETRY_DISABLED=1 \
    --env NEXT_PUBLIC_NEXOLAB_DATA_MODE="$mode" \
    --env NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$api_url" \
    --env NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="$websocket_url" \
    --env NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="$auth_provider" \
    --env NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$organization_id" \
    --volume "$release_dir:/workspace" \
    --workdir /workspace \
    "$image" \
    bash -lc 'npm ci --no-audit --no-fund && npm run build'
}

nexolab_frontend_write_provenance() {
  local release_dir=$1 commit=$2 runtime_mode=$3 api_url=$4 websocket_url=$5 auth_provider=$6 organization_id=$7
  local lock_sha
  lock_sha="$(sha256sum "$release_dir/package-lock.json" | awk '{print $1}')"
  {
    printf 'commit=%s\n' "$commit"
    printf 'package_lock_sha256=%s\n' "$lock_sha"
    printf 'runtime_mode=%s\n' "$runtime_mode"
    printf 'data_mode=live\n'
    printf 'api_url=%s\n' "$api_url"
    printf 'websocket_url=%s\n' "$websocket_url"
    printf 'auth_provider=%s\n' "$auth_provider"
    printf 'organization_id=%s\n' "$organization_id"
  } > "$release_dir/nexolab-frontend-provenance.txt"
  chmod 0600 "$release_dir/nexolab-frontend-provenance.txt"
}

nexolab_frontend_discard_unactivated_release() {
  local releases_root=$1 release_dir=$2
  [[ -n "$release_dir" && -e "$release_dir" ]] || return 0
  [[ ! -L "$release_dir" ]] || {
    printf 'ERROR: refusing to remove symlinked frontend release: %s\n' "$release_dir" >&2
    return 70
  }
  [[ "$(dirname "$release_dir")" == "$releases_root" ]] || {
    printf 'ERROR: refusing to remove frontend release outside root: %s\n' "$release_dir" >&2
    return 70
  }
  local base
  base="$(basename "$release_dir")"
  [[ "$base" =~ ^[0-9a-f]{40}-[0-9]{8}T[0-9]{6}Z$ ]] || {
    printf 'ERROR: refusing to remove unclassified frontend release: %s\n' "$release_dir" >&2
    return 70
  }
  rm -rf -- "$release_dir"
  [[ ! -e "$release_dir" ]]
}
