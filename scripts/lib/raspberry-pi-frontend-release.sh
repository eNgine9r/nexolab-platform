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

nexolab_frontend_host_platform() {
  case "$(uname -m)" in
    aarch64) printf 'linux/arm64\n' ;;
    x86_64) printf 'linux/amd64\n' ;;
    *) return 69 ;;
  esac
}

nexolab_frontend_verify_runtime_archive() {
  local archive=$1 report=$2
  python3 - "$archive" "$report" <<'PY_ARCHIVE'
import posixpath
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive = Path(sys.argv[1])
report = Path(sys.argv[2])
allowed = {".next", "node_modules"}
errors: list[str] = []
member_count = 0

try:
    tf = tarfile.open(archive, "r:gz")
except (OSError, tarfile.TarError) as exc:
    report.write_text(f"status=FAIL\nerror=invalid-runtime-archive:{type(exc).__name__}\n", encoding="utf-8")
    raise SystemExit(70)

with tf:
    for member in tf.getmembers():
        member_count += 1
        name = member.name
        path = PurePosixPath(name)
        parts = tuple(part for part in path.parts if part not in ("", "."))
        if path.is_absolute() or not parts or ".." in parts or parts[0] not in allowed:
            errors.append(f"path:{name}")
            continue
        if member.ischr() or member.isblk() or member.isfifo() or member.mode & 0o6000:
            errors.append(f"unsafe-type-or-mode:{name}")
            continue
        if member.issym() or member.islnk():
            target = member.linkname
            if PurePosixPath(target).is_absolute():
                errors.append(f"absolute-link:{name}")
                continue
            if member.islnk():
                resolved = posixpath.normpath(target)
            else:
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            resolved_parts = tuple(part for part in PurePosixPath(resolved).parts if part not in ("", "."))
            if not resolved_parts or resolved_parts[0] not in allowed or ".." in resolved_parts or resolved.startswith("../"):
                errors.append(f"escaping-link:{name}")

lines = [f"members={member_count}"]
if errors:
    lines.insert(0, "status=FAIL")
    lines.extend(f"error={item}" for item in errors[:20])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    raise SystemExit(70)
lines.insert(0, "status=PASS")
report.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY_ARCHIVE
}

nexolab_frontend_import_artifact() {
  local artifact_root=$1 repo=$2 release_dir=$3 target_commit=$4
  local mode=$5 api_url=$6 websocket_url=$7 auth_provider=$8 organization_id=$9 report=${10}
  local required source_sha artifact_platform host_platform artifact_node expected_node actual_node
  : > "$report"
  for required in \
    frontend-runtime.tar.gz package.json package-lock.json \
    frontend-source-sha.txt frontend-package-sha256.txt frontend-runtime-contract.txt \
    frontend-platform.txt frontend-node-version.txt frontend-build-id.txt \
    frontend-runtime-files-sha256.txt frontend-public-contract.txt \
    frontend-native-files.txt frontend-artifact-sha256.txt; do
    if [[ ! -f "$artifact_root/$required" ]]; then
      printf 'status=FAIL\nerror=missing-artifact-file:%s\n' "$required" > "$report"
      return 70
    fi
  done
  source_sha="$(tr -d '[:space:]' < "$artifact_root/frontend-source-sha.txt")"
  if [[ "$source_sha" != "$target_commit" ]]; then
    printf 'status=FAIL\nerror=source-sha-mismatch\nexpected=%s\nactual=%s\n' "$target_commit" "$source_sha" > "$report"
    return 70
  fi
  if ! (cd "$artifact_root" && sha256sum --check frontend-package-sha256.txt >/dev/null); then
    printf 'status=FAIL\nerror=package-checksum-mismatch\n' > "$report"
    return 70
  fi
  if ! (cd "$artifact_root" && sha256sum --check frontend-artifact-sha256.txt >/dev/null); then
    printf 'status=FAIL\nerror=artifact-checksum-mismatch\n' > "$report"
    return 70
  fi
  if ! cmp -s "$artifact_root/package.json" "$release_dir/package.json" || ! cmp -s "$artifact_root/package-lock.json" "$release_dir/package-lock.json"; then
    printf 'status=FAIL\nerror=target-package-identity-mismatch\n' > "$report"
    return 70
  fi
  if ! python3 - "$artifact_root/frontend-runtime-contract.txt" "$mode" "$api_url" "$websocket_url" "$auth_provider" "$organization_id" <<'PY_CONTRACT'
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = dict(zip(("runtime_mode", "api_base_url", "websocket_url", "auth_provider", "organization_id"), sys.argv[2:7], strict=True))
parsed = {}
for line in path.read_text(encoding="utf-8").splitlines():
    if not line or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key in parsed:
        raise SystemExit(70)
    parsed[key] = value
raise SystemExit(0 if parsed == expected else 70)
PY_CONTRACT
  then
    printf 'status=FAIL\nerror=runtime-contract-mismatch\n' > "$report"
    return 70
  fi
  artifact_platform="$(tr -d '[:space:]' < "$artifact_root/frontend-platform.txt")"
  host_platform="$(nexolab_frontend_host_platform)" || {
    printf 'status=FAIL\nerror=unsupported-host-platform\n' > "$report"
    return 70
  }
  if [[ "$artifact_platform" != "$host_platform" ]]; then
    printf 'status=FAIL\nerror=artifact-platform-mismatch\nexpected=%s\nactual=%s\n' "$host_platform" "$artifact_platform" > "$report"
    return 70
  fi
  artifact_node="$(tr -d '[:space:]' < "$artifact_root/frontend-node-version.txt")"
  expected_node="$(tr -d '[:space:]' < "$release_dir/.nvmrc")"
  actual_node="$(node --version | sed 's/^v//')"
  if [[ "$artifact_node" != "$expected_node" || "$actual_node" != "$expected_node" ]]; then
    printf 'status=FAIL\nerror=node-version-mismatch\nartifact=%s\nsource=%s\nhost=%s\n' "$artifact_node" "$expected_node" "$actual_node" > "$report"
    return 70
  fi
  if ! nexolab_frontend_verify_runtime_archive "$artifact_root/frontend-runtime.tar.gz" "${report}.archive"; then
    printf 'status=FAIL\nerror=unsafe-runtime-archive\n' > "$report"
    return 70
  fi
  [[ ! -e "$release_dir/.next" && ! -e "$release_dir/node_modules" ]] || {
    printf 'status=FAIL\nerror=release-runtime-already-present\n' > "$report"
    return 70
  }
  if ! tar --extract --gzip --file "$artifact_root/frontend-runtime.tar.gz" --directory "$release_dir" --no-same-owner; then
    printf 'status=FAIL\nerror=runtime-archive-extract-failed\n' > "$report"
    return 70
  fi
  if ! (cd "$release_dir" && sha256sum --check "$artifact_root/frontend-runtime-files-sha256.txt" >/dev/null); then
    printf 'status=FAIL\nerror=runtime-files-checksum-mismatch\n' > "$report"
    return 70
  fi
  if [[ ! -x "$release_dir/node_modules/.bin/next" ]]; then
    printf 'status=FAIL\nerror=next-runtime-executable-missing\n' > "$report"
    return 70
  fi
  for required in \
    frontend-source-sha.txt frontend-package-sha256.txt frontend-runtime-contract.txt \
    frontend-platform.txt frontend-node-version.txt frontend-build-id.txt \
    frontend-runtime-files-sha256.txt frontend-native-files.txt frontend-artifact-sha256.txt; do
    install -m 0600 "$artifact_root/$required" "$release_dir/$required"
  done
  if ! nexolab_frontend_verify_public_contract \
    "$release_dir" "$mode" "$api_url" "$websocket_url" "$auth_provider" "$organization_id" "${report}.public-contract"; then
    printf 'status=FAIL\nerror=compiled-public-contract-mismatch\n' > "$report"
    return 70
  fi
  {
    printf 'status=PASS\n'
    printf 'preparation=off-device-self-contained-runtime\n'
    printf 'source_sha=%s\n' "$source_sha"
    printf 'platform=%s\n' "$artifact_platform"
    printf 'node_version=%s\n' "$artifact_node"
    printf 'build_id=%s\n' "$(cat "$release_dir/.next/BUILD_ID")"
  } > "$report"
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
