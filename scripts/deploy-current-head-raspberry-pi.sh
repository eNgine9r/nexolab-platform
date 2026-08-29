#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/raspberry-pi-runtime-mode.sh
source "$SCRIPT_DIR/lib/raspberry-pi-runtime-mode.sh"
# shellcheck source=deploy-capacity-guard.sh
source "$SCRIPT_DIR/deploy-capacity-guard.sh"
# shellcheck source=lib/raspberry-pi-frontend-release.sh
source "$SCRIPT_DIR/lib/raspberry-pi-frontend-release.sh"
# shellcheck source=lib/frontend-candidate-liveness.sh
source "$SCRIPT_DIR/lib/frontend-candidate-liveness.sh"

usage() {
  cat <<'USAGE'
Usage: deploy-current-head-raspberry-pi.sh [--runtime-mode lan|standalone] [--frontend-artifact PATH]
       [--source-ref SHA --expected-deployed-source SHA] [--source-selection-check-only]
       [--restore-edge-snapshot DEPLOYMENT_EVIDENCE_DIR
        --expected-deployed-source SHA --expected-target-source SHA]

Options:
  --frontend-artifact PATH  Import a verified off-device frontend artifact instead of building on this host.
  --source-ref SHA          Deploy an explicitly approved historical commit already contained in main history.
  --expected-deployed-source SHA
                           Exact currently deployed source SHA; required with --source-ref.
  --source-selection-check-only
                           Validate source lineage and exit before capacity, backup or runtime mutation.
  --restore-edge-snapshot DEPLOYMENT_EVIDENCE_DIR
                           Explicitly restore that deployment's captured edge SQLite snapshot.
                           The Device Agent must already be stopped; this command never restarts it.
  --expected-target-source SHA
                           Exact failed deployment target; required with --restore-edge-snapshot.

Modes:
  lan         Trusted-LAN dashboard and API exposure. This is the default.
  standalone  Loopback-only dashboard/API runtime for a locally attached browser.
USAGE
}

RUNTIME_MODE="lan"
FRONTEND_ARTIFACT_INPUT=""
REQUESTED_SOURCE_REF=""
EXPECTED_DEPLOYED_SOURCE=""
SOURCE_SELECTION_CHECK_ONLY="0"
RESTORE_EDGE_SNAPSHOT_DIR=""
EXPECTED_TARGET_SOURCE=""
while (($# > 0)); do
  case "$1" in
    --runtime-mode)
      (($# >= 2)) || {
        echo "ERROR: --runtime-mode requires lan or standalone" >&2
        exit 64
      }
      RUNTIME_MODE="$2"
      shift 2
      ;;
    --frontend-artifact)
      (($# >= 2)) || {
        echo "ERROR: --frontend-artifact requires an extracted artifact directory" >&2
        exit 64
      }
      FRONTEND_ARTIFACT_INPUT="$2"
      shift 2
      ;;
    --source-ref)
      (($# >= 2)) || {
        echo "ERROR: --source-ref requires a full 40-character commit SHA" >&2
        exit 64
      }
      REQUESTED_SOURCE_REF="$2"
      shift 2
      ;;
    --expected-deployed-source)
      (($# >= 2)) || {
        echo "ERROR: --expected-deployed-source requires a full 40-character commit SHA" >&2
        exit 64
      }
      EXPECTED_DEPLOYED_SOURCE="$2"
      shift 2
      ;;
    --source-selection-check-only)
      SOURCE_SELECTION_CHECK_ONLY="1"
      shift
      ;;
    --restore-edge-snapshot)
      (($# >= 2)) || {
        echo "ERROR: --restore-edge-snapshot requires a deployment evidence directory" >&2
        exit 64
      }
      RESTORE_EDGE_SNAPSHOT_DIR="$2"
      shift 2
      ;;
    --expected-target-source)
      (($# >= 2)) || {
        echo "ERROR: --expected-target-source requires a full 40-character commit SHA" >&2
        exit 64
      }
      EXPECTED_TARGET_SOURCE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done
nexolab_validate_runtime_mode "$RUNTIME_MODE" || exit $?
if [[ -n "$REQUESTED_SOURCE_REF" || -n "$EXPECTED_DEPLOYED_SOURCE" ]]; then
  [[ -n "$RESTORE_EDGE_SNAPSHOT_DIR" || ( -n "$REQUESTED_SOURCE_REF" && -n "$EXPECTED_DEPLOYED_SOURCE" ) ]] || {
    echo "ERROR: --source-ref and --expected-deployed-source must be supplied together" >&2
    exit 64
  }
fi

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"

restore_edge_sqlite_snapshot() {
  [[ -z "$REQUESTED_SOURCE_REF" && "$SOURCE_SELECTION_CHECK_ONLY" == "0" \
    && -z "$FRONTEND_ARTIFACT_INPUT" ]] \
    || {
      echo "ERROR: edge SQLite restore cannot be combined with deployment/source-selection options" >&2
      return 64
    }
  [[ "$EXPECTED_DEPLOYED_SOURCE" =~ ^[0-9a-f]{40}$ \
    && "$EXPECTED_TARGET_SOURCE" =~ ^[0-9a-f]{40}$ ]] \
    || {
      echo "ERROR: restore requires exact --expected-deployed-source and --expected-target-source SHAs" >&2
      return 64
    }
  for command in docker python3 flock mv; do
    command -v "$command" >/dev/null 2>&1 || {
      echo "ERROR: required restore command is missing: $command" >&2
      return 69
    }
  done

  local deployments_root evidence_dir evidence_id snapshot metadata result_tmp result_file
  local deployed_device_agent_image_id
  deployments_root="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$REPO/runtime/deployments")"
  evidence_dir="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$RESTORE_EDGE_SNAPSHOT_DIR")"
  [[ "$evidence_dir" == "$deployments_root"/* ]] \
    || {
      echo "ERROR: restore evidence must be a deployment audit directory" >&2
      return 64
    }
  evidence_id="${evidence_dir##*/}"
  [[ "$evidence_id" =~ ^[0-9]{8}T[0-9]{6}Z$ && "${evidence_dir%/*}" == "$deployments_root" ]] \
    || {
      echo "ERROR: restore evidence must be a direct timestamped deployment audit directory" >&2
      return 64
    }
  snapshot="$evidence_dir/edge-sqlite-pre-cutover.db"
  metadata="$evidence_dir/edge-sqlite-pre-cutover.json"
  [[ -f "$snapshot" && ! -L "$snapshot" && -f "$metadata" && ! -L "$metadata" ]] \
    || {
      echo "ERROR: exact edge SQLite snapshot and metadata are required" >&2
      return 66
    }

  local lock_file="${XDG_RUNTIME_DIR:-/tmp}/nexolab-current-head-launch.lock"
  exec 8>"$lock_file"
  flock -n 8 || {
    echo "ERROR: another NEXOLAB deployment/recovery operation is already running" >&2
    return 75
  }

  local -a edge_containers=()
  mapfile -t edge_containers < <(
    docker ps -aq \
      --filter label=com.docker.compose.project=nexolab-edge \
      --filter label=com.docker.compose.service=device-agent
  )
  [[ "${#edge_containers[@]}" == "1" ]] \
    || {
      echo "ERROR: restore requires exactly one known Device Agent container" >&2
      return 1
    }
  local edge_container="${edge_containers[0]}"
  [[ "$(docker inspect --format '{{.State.Running}}' "$edge_container")" == "false" ]] \
    || {
      echo "ERROR: Device Agent must already be stopped before edge SQLite restore" >&2
      return 1
    }
  [[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination \"/var/lib/nexolab\"}}{{.Name}}{{end}}{{end}}' "$edge_container")" == "nexolab-edge_edge-data" ]] \
    || {
      echo "ERROR: Device Agent edge-data volume identity is unexpected" >&2
      return 1
    }
  local edge_image
  edge_image="$(docker inspect --format '{{.Image}}' "$edge_container")"
  [[ -n "$edge_image" ]] || {
    echo "ERROR: Device Agent image identity is unavailable" >&2
    return 1
  }

  result_tmp="$evidence_dir/.edge-sqlite-restore-result.json.partial"
  result_file="$evidence_dir/edge-sqlite-restore-result.json"
  [[ ! -e "$result_file" ]] || {
    echo "ERROR: final restore result already exists; refusing to repeat completed recovery" >&2
    return 1
  }
  if [[ -e "$result_tmp" ]]; then
    [[ -f "$result_tmp" && ! -L "$result_tmp" ]] || {
      echo "ERROR: interrupted restore result is not a safe regular file" >&2
      return 1
    }
    echo "Resuming interrupted restore through full guarded snapshot revalidation" >&2
  fi
  deployed_device_agent_image_id="$(python3 - "$metadata" <<'PY_RESTORE_IMAGE'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream).get("deployed_device_agent_image_id", ""))
PY_RESTORE_IMAGE
)"
  [[ "$deployed_device_agent_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || {
      echo "ERROR: snapshot evidence has no valid pre-cutover Device Agent image id" >&2
      return 1
    }
  docker image inspect "$deployed_device_agent_image_id" >/dev/null 2>&1 \
    || {
      echo "ERROR: exact pre-cutover Device Agent image is unavailable; database was not restored" >&2
      return 1
    }
  if ! docker run --rm --user 0:0 \
    --volumes-from "$edge_container" \
    --mount "type=bind,src=$SCRIPT_DIR,dst=/nexolab-scripts,readonly" \
    --mount "type=bind,src=$evidence_dir,dst=/evidence,readonly" \
    --entrypoint /usr/bin/python3 \
    "$edge_image" \
    /nexolab-scripts/deploy-edge-sqlite-snapshot.py restore \
      --snapshot /evidence/edge-sqlite-pre-cutover.db \
      --metadata /evidence/edge-sqlite-pre-cutover.json \
      --destination /var/lib/nexolab/edge.db \
      --expected-deployed-source "$EXPECTED_DEPLOYED_SOURCE" \
      --expected-target-source "$EXPECTED_TARGET_SOURCE" \
      --expected-deployment-evidence-id "$evidence_id" \
      > "$result_tmp"; then
    rm -f -- "$result_tmp"
    echo "ERROR: guarded edge SQLite restore failed; Device Agent remains stopped" >&2
    return 1
  fi
  if [[ "$(docker inspect --format '{{.State.Running}}' "$edge_container")" != "false" ]]; then
    rm -f -- "$result_tmp"
    echo "ERROR: Device Agent state changed during restore; do not restart or continue" >&2
    return 1
  fi
  docker image tag "$deployed_device_agent_image_id" nexolab-device-agent:local \
    || {
      rm -f -- "$result_tmp"
      echo "ERROR: SQLite was restored but the pre-cutover Device Agent image could not be selected; Device Agent remains stopped" >&2
      return 1
    }
  [[ "$(docker image inspect --format '{{.Id}}' nexolab-device-agent:local)" == "$deployed_device_agent_image_id" ]] \
    || {
      rm -f -- "$result_tmp"
      echo "ERROR: SQLite was restored but pre-cutover Device Agent image verification failed; Device Agent remains stopped" >&2
      return 1
    }
  python3 - "$result_tmp" "$result_file" <<'PY_RESTORE_RESULT'
import os
from pathlib import Path
import sys

temporary = Path(sys.argv[1])
result = Path(sys.argv[2])
with temporary.open("rb") as stream:
    os.fsync(stream.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, result)
directory_fd = os.open(result.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY_RESTORE_RESULT
  echo "EDGE_SQLITE_RESTORE_VERIFIED"
  echo "evidence=$result_file"
  echo "Device Agent remains stopped; restart requires a separate explicit operator action."
}

if [[ -n "$RESTORE_EDGE_SNAPSHOT_DIR" ]]; then
  restore_edge_sqlite_snapshot
  exit $?
fi

[[ -z "$EXPECTED_TARGET_SOURCE" ]] || {
  echo "ERROR: --expected-target-source is valid only with --restore-edge-snapshot" >&2
  exit 64
}
FRONTEND_ARTIFACT_DIR=""
if [[ -n "$FRONTEND_ARTIFACT_INPUT" ]]; then
  [[ -d "$FRONTEND_ARTIFACT_INPUT" ]] || {
    echo "ERROR: frontend artifact directory not found: $FRONTEND_ARTIFACT_INPUT" >&2
    exit 66
  }
  FRONTEND_ARTIFACT_DIR="$(cd "$FRONTEND_ARTIFACT_INPUT" && pwd -P)"
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
AUDIT_DIR="$REPO/runtime/deployments/$STAMP"
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/nexolab-current-head-launch.lock"
CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
EDGE_ENV="$CENTRAL_DIR/.env.edge-central"
ROOT_ENV="$REPO/.env.local"
SUMMARY="$AUDIT_DIR/summary.txt"
RUNTIME_MODE_FILE="$REPO/runtime/runtime-mode"
FRONTEND_RELEASES_DIR="$REPO/runtime/frontend-releases"
FRONTEND_RELEASE_DIR=""
FRONTEND_CANDIDATE_PID=""
FRONTEND_CANDIDATE_PGID=""
FRONTEND_CANDIDATE_START_GATE=""
SOURCE_CHECKOUT_RESTORE_REQUIRED="0"
EDGE_DEVICE_AGENT_QUIESCED_BY_DEPLOYMENT="0"
EDGE_DEVICE_AGENT_QUIESCED_CONTAINER=""
EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID=""
EDGE_DEVICE_AGENT_QUIESCE_EVIDENCE=""
CONTROL_HEAD=""
TARGET_HEAD=""
EXPECTED_DEPLOYMENT_EVIDENCE=""
VERIFIED_DEPLOYED_SOURCE=""
VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID=""

CENTRAL_COMPOSE_ARGS=(
  -f "$CENTRAL_DIR/compose.central.yaml"
  -f "$CENTRAL_DIR/compose.observability.yaml"
)
EDGE_COMPOSE_ARGS=(
  -f "$CENTRAL_DIR/compose.edge.yaml"
  -f "$CENTRAL_DIR/compose.hardware.yaml"
  -f "$CENTRAL_DIR/compose.edge-central-bridge.yaml"
)

mkdir -p "$AUDIT_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "ERROR: another NEXOLAB deployment is already running." >&2
  exit 75
fi

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$SUMMARY"
}

fail() {
  log "ERROR: $*"
  exit 1
}

cleanup_frontend_candidate() {
  local pid="${FRONTEND_CANDIDATE_PID:-}"
  local pgid="${FRONTEND_CANDIDATE_PGID:-}"
  local actual_pgid=""
  local attempt

  if [[ -n "${FRONTEND_CANDIDATE_START_GATE:-}" ]]; then
    rm -f -- "$FRONTEND_CANDIDATE_START_GATE"
    FRONTEND_CANDIDATE_START_GATE=""
  fi

  if [[ -z "$pgid" && -n "$pid" ]]; then
    actual_pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | awk 'NF {print $1; exit}')"
    if [[ "$actual_pgid" == "$pid" ]]; then
      pgid="$actual_pgid"
      FRONTEND_CANDIDATE_PGID="$actual_pgid"
    fi
  fi

  if [[ -z "$pgid" ]]; then
    if [[ -n "$pid" ]]; then
      kill -TERM "$pid" >/dev/null 2>&1 || true
      for attempt in $(seq 1 20); do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
          break
        fi
        sleep 0.1
      done
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -KILL "$pid" >/dev/null 2>&1 || true
        for attempt in $(seq 1 10); do
          if ! kill -0 "$pid" >/dev/null 2>&1; then
            break
          fi
          sleep 0.1
        done
      fi
      if kill -0 "$pid" >/dev/null 2>&1; then
        log "ERROR: frontend candidate process did not terminate: $pid"
        return 1
      fi
      wait "$pid" >/dev/null 2>&1 || true
    fi
    FRONTEND_CANDIDATE_PID=""
    FRONTEND_CANDIDATE_PGID=""
    return 0
  fi

  kill -TERM -- "-$pgid" >/dev/null 2>&1 || true
  for attempt in $(seq 1 20); do
    if ! nexolab_frontend_candidate_group_has_live_processes "$pgid"; then
      break
    fi
    sleep 0.1
  done

  if nexolab_frontend_candidate_group_has_live_processes "$pgid"; then
    kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
    for attempt in $(seq 1 10); do
      if ! nexolab_frontend_candidate_group_has_live_processes "$pgid"; then
        break
      fi
      sleep 0.1
    done
  fi

  if nexolab_frontend_candidate_group_has_live_processes "$pgid"; then
    log "ERROR: frontend candidate process group did not terminate: $pgid"
    return 1
  fi
  if [[ -n "$pid" ]]; then
    wait "$pid" >/dev/null 2>&1 || true
  fi

  FRONTEND_CANDIDATE_PID=""
  FRONTEND_CANDIDATE_PGID=""
  return 0
}

restore_control_checkout() {
  [[ "$SOURCE_CHECKOUT_RESTORE_REQUIRED" == "1" ]] || return 0
  if ! git -C "$REPO" switch main >/dev/null 2>&1; then
    log "ERROR: failed to restore repository checkout to main"
    return 1
  fi
  local restored_head
  restored_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
  if [[ -z "$CONTROL_HEAD" || "$restored_head" != "$CONTROL_HEAD" ]]; then
    log "ERROR: restored main does not match the pre-deployment origin/main head"
    return 1
  fi
  SOURCE_CHECKOUT_RESTORE_REQUIRED="0"
  log "Repository checkout restored to main: $restored_head"
}

publish_edge_device_agent_quiesce_recovery() {
  local evidence_dir="$1"
  local container_id="$2"
  local image_id="$3"
  python3 - "$evidence_dir/edge-device-agent-quiesce-recovered.json" \
    "$container_id" "$image_id" <<'PY_QUIESCE_RECOVERED'
import json
import os
from pathlib import Path
import sys
from datetime import datetime

result = Path(sys.argv[1])
container_id = sys.argv[2]
image_id = sys.argv[3]
temporary = result.with_name(f".{result.name}.tmp-{os.getpid()}")
document = {
    "schema_version": 1,
    "kind": "nexolab-edge-device-agent-quiesce-recovered",
    "deployment_evidence_id": result.parent.name,
    "container_id": container_id,
    "image_id": image_id,
    "recovered_at": datetime.now().astimezone().isoformat(),
}
try:
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, result)
    directory_fd = os.open(result.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    temporary.unlink(missing_ok=True)
PY_QUIESCE_RECOVERED
}

recover_interrupted_pre_mutation_quiesce() {
  local recovery
  if ! recovery="$(python3 - "$REPO/runtime/deployments" "$AUDIT_DIR" <<'PY_FIND_QUIESCE'
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
current = Path(sys.argv[2]).resolve()
stamp_re = re.compile(r"^\d{8}T\d{6}Z$")
container_re = re.compile(r"^[0-9a-f]{64}$")
image_re = re.compile(r"^sha256:[0-9a-f]{64}$")
candidates = []
if root.is_dir():
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not stamp_re.fullmatch(directory.name):
            continue
        record_path = directory / "edge-device-agent-quiesce.json"
        if not record_path.exists():
            continue
        if record_path.is_symlink() or not record_path.is_file():
            print(f"ERROR: unsafe Device Agent quiesce record: {directory}", file=sys.stderr)
            raise SystemExit(1)
        if (directory / "runtime-mutation-started").is_file() or (
            directory / "edge-device-agent-quiesce-recovered.json"
        ).is_file():
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"ERROR: unreadable Device Agent quiesce record: {directory}: {error}", file=sys.stderr)
            raise SystemExit(1)
        valid = (
            isinstance(record, dict)
            and record.get("schema_version") == 1
            and record.get("kind") == "nexolab-edge-device-agent-quiesce"
            and record.get("deployment_evidence_id") == directory.name
            and container_re.fullmatch(str(record.get("container_id", "")))
            and image_re.fullmatch(str(record.get("image_id", "")))
        )
        if not valid:
            print(f"ERROR: invalid Device Agent quiesce record: {directory}", file=sys.stderr)
            raise SystemExit(1)
        candidates.append((directory.name, directory.resolve(), record["container_id"], record["image_id"]))
if len(candidates) > 1:
    print("ERROR: multiple unresolved Device Agent quiesce records", file=sys.stderr)
    raise SystemExit(1)
if candidates:
    _stamp, directory, container_id, image_id = candidates[0]
    if directory == current:
        raise SystemExit(0)
    print(f"{directory}\t{container_id}\t{image_id}")
PY_FIND_QUIESCE
)"; then
    fail "unresolved Device Agent quiesce evidence is unsafe"
  fi
  [[ -n "$recovery" ]] || return 0
  local evidence_dir="${recovery%%$'\t'*}"
  local recovery_tail="${recovery#*$'\t'}"
  local container_id="${recovery_tail%%$'\t'*}"
  local image_id="${recovery_tail#*$'\t'}"
  [[ "$(docker inspect --format '{{.Id}}' "$container_id")" == "$container_id" \
    && "$(docker inspect --format '{{.Image}}' "$container_id")" == "$image_id" ]] \
    || fail "recorded pre-mutation Device Agent container/image is unavailable"
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" != "true" ]]; then
    docker start "$container_id" >/dev/null \
      || fail "recorded pre-mutation Device Agent could not be restarted"
  fi
  [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" == "true" ]] \
    || fail "recorded pre-mutation Device Agent did not return to running state"
  publish_edge_device_agent_quiesce_recovery "$evidence_dir" "$container_id" "$image_id" \
    || fail "Device Agent quiesce recovery evidence could not be published"
  log "Recovered exact Device Agent from interrupted pre-mutation quiesce: $evidence_dir"
}

restart_quiesced_device_agent_after_pre_mutation_failure() {
  [[ "$EDGE_DEVICE_AGENT_QUIESCED_BY_DEPLOYMENT" == "1" ]] || return 0
  [[ ! -e "$AUDIT_DIR/runtime-mutation-started" ]] || return 0
  [[ -n "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER" \
    && -n "$EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID" ]] \
    || return 1
  [[ "$(docker inspect --format '{{.Image}}' "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER")" == "$EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID" ]] \
    || return 1
  docker start "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER" >/dev/null || return 1
  [[ "$(docker inspect --format '{{.State.Running}}' "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER")" == "true" ]] \
    || return 1
  publish_edge_device_agent_quiesce_recovery \
    "$EDGE_DEVICE_AGENT_QUIESCE_EVIDENCE" \
    "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER" \
    "$EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID" \
    || return 1
  EDGE_DEVICE_AGENT_QUIESCED_BY_DEPLOYMENT="0"
  log "Restarted unchanged Device Agent after pre-mutation snapshot-boundary failure"
}

on_exit() {
  local rc=$?
  local cleanup_rc=0
  local edge_restart_rc=0
  local restore_rc=0
  trap - EXIT ERR
  if ((rc != 0)); then
    if restart_quiesced_device_agent_after_pre_mutation_failure; then
      edge_restart_rc=0
    else
      edge_restart_rc=$?
      log "ERROR: unchanged Device Agent could not be restarted during failed deployment exit"
    fi
  fi
  if cleanup_frontend_candidate; then
    cleanup_rc=0
  else
    cleanup_rc=$?
  fi
  if ((cleanup_rc != 0)); then
    log "ERROR: frontend candidate cleanup failed during exit; original exit code: $rc"
    if ((rc == 0)); then
      rc=$cleanup_rc
    fi
  fi
  if restore_control_checkout; then
    restore_rc=0
  else
    restore_rc=$?
  fi
  if ((restore_rc != 0 && rc == 0)); then
    rc=$restore_rc
  fi
  if ((edge_restart_rc != 0 && rc == 0)); then
    rc=$edge_restart_rc
  fi
  exit "$rc"
}

on_error() {
  local rc=$?
  cleanup_frontend_candidate || true
  if ! restart_quiesced_device_agent_after_pre_mutation_failure; then
    log "ERROR: unchanged Device Agent could not be restarted after pre-mutation failure"
  fi
  if [[ "${NEXOLAB_FRONTEND_ACTIVATED:-0}" != "1" && -n "${FRONTEND_RELEASE_DIR:-}" ]]; then
    nexolab_frontend_discard_unactivated_release "$FRONTEND_RELEASES_DIR" "$FRONTEND_RELEASE_DIR" || true
  fi
  log "Deployment failed with exit code $rc. Evidence: $AUDIT_DIR"
  {
    echo
    echo '=== docker compose projects ==='
    docker compose ls 2>&1 || true
    echo
    echo '=== containers ==='
    docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1 || true
    echo
    echo '=== central logs ==='
    if [[ -f "$CENTRAL_ENV" ]]; then
      docker compose --env-file "$CENTRAL_ENV" \
        "${CENTRAL_COMPOSE_ARGS[@]}" \
        logs --tail=250 --no-color 2>&1 || true
    fi
    echo
    echo '=== edge logs ==='
    if [[ -f "$EDGE_ENV" ]]; then
      docker compose --env-file "$EDGE_ENV" \
        "${EDGE_COMPOSE_ARGS[@]}" \
        logs --tail=250 --no-color 2>&1 || true
    fi
  } > "$AUDIT_DIR/failure-diagnostics.txt"
  exit "$rc"
}
trap on_error ERR
trap on_exit EXIT

require() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

require git
require python3
[[ -d "$REPO/.git" ]] || fail "repository not found: $REPO"
cd "$REPO"

validate_full_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

resolve_latest_deployment_evidence() {
  local deployment_evidence
  if ! deployment_evidence="$(python3 - "$REPO/runtime/deployments" "$AUDIT_DIR" <<'PY_EVIDENCE'
from datetime import datetime
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
current_audit = Path(sys.argv[2]).resolve()
stamp_re = re.compile(r"^\d{8}T\d{6}Z$")
sha_re = re.compile(r"^[0-9a-f]{40}$")
legacy_mutation_markers = (
    "Starting central backend, MinIO and observability",
    "Starting real-hardware edge stack",
    "Activating verified frontend release",
    "RUNTIME MUTATION STARTED",
)

def valid_stamp(name: str) -> bool:
    if not stamp_re.fullmatch(name):
        return False
    try:
        datetime.strptime(name, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True

attempts: list[tuple[str, Path, str, bool, str | None, str | None]] = []
if root.is_dir():
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not valid_stamp(directory.name):
            continue
        summary = directory / "summary.txt"
        summary_text = summary.read_text(encoding="utf-8", errors="replace") if summary.is_file() else ""
        final_state = directory / "final-state.txt"
        commit = None
        if final_state.is_file():
            for line in final_state.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("commit="):
                    candidate = line.split("=", 1)[1].strip()
                    if sha_re.fullmatch(candidate):
                        commit = candidate
                    break
        passed_commit = commit if "DEPLOYMENT PASSED" in summary_text else None
        restore_result_path = directory / "edge-sqlite-restore-result.json"
        recovered_commit = None
        recovered_image = None
        if restore_result_path.exists():
            metadata_path = directory / "edge-sqlite-pre-cutover.json"
            if (
                restore_result_path.is_symlink()
                or metadata_path.is_symlink()
                or not restore_result_path.is_file()
                or not metadata_path.is_file()
            ):
                print(f"ERROR: recovery authority evidence is unsafe: {directory}", file=sys.stderr)
                raise SystemExit(3)
            try:
                restore_result = json.loads(restore_result_path.read_text(encoding="utf-8"))
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                print(f"ERROR: recovery authority evidence is unreadable: {directory}: {error}", file=sys.stderr)
                raise SystemExit(3)
            matching_fields = (
                "sha256",
                "bytes",
                "registry_revision",
                "outbound_queue_count",
                "outbound_queue_high_water",
                "node_stream_sequences",
                "deployment_evidence_id",
                "deployed_source",
                "deployed_device_agent_image_id",
                "target_source",
            )
            valid_restore = (
                isinstance(restore_result, dict)
                and isinstance(metadata, dict)
                and restore_result.get("schema_version") == 1
                and restore_result.get("kind") == "nexolab-edge-sqlite-restore-result"
                and restore_result.get("status") == "restored"
                and metadata.get("schema_version") == 1
                and metadata.get("kind") == "nexolab-edge-sqlite-pre-cutover"
                and metadata.get("source_quick_check") == "ok"
                and metadata.get("snapshot_quick_check") == "ok"
                and restore_result.get("deployment_evidence_id") == directory.name
                and sha_re.fullmatch(str(restore_result.get("deployed_source", "")))
                and sha_re.fullmatch(str(restore_result.get("target_source", "")))
                and all(restore_result.get(field) == metadata.get(field) for field in matching_fields)
            )
            if not valid_restore:
                print(f"ERROR: recovery authority evidence is inconsistent: {directory}", file=sys.stderr)
                raise SystemExit(3)
            recovered_commit = restore_result["deployed_source"]
            recovered_image = restore_result["deployed_device_agent_image_id"]
        effective_commit = recovered_commit or passed_commit
        mutated = (directory / "runtime-mutation-started").is_file() or any(
            marker in summary_text for marker in legacy_mutation_markers
        )
        attempts.append(
            (directory.name, directory.resolve(), summary_text, mutated, effective_commit, recovered_image)
        )

successful = [
    (stamp, directory, commit, recovered_image)
    for stamp, directory, _summary, _mutated, commit, recovered_image in attempts
    if commit
]
if not successful:
    print("ERROR: no successful source-deployment evidence is available", file=sys.stderr)
    raise SystemExit(1)

success_stamp, success_dir, success_commit, success_image = max(successful, key=lambda item: item[0])
for stamp, directory, _summary, mutated, commit, _recovered_image in attempts:
    if stamp <= success_stamp or directory == current_audit:
        continue
    if mutated and commit is None:
        print(
            f"ERROR: newer deployment attempt crossed runtime mutation boundary without success: {directory}",
            file=sys.stderr,
        )
        raise SystemExit(2)

print(f"{success_commit}\t{success_dir}\t{success_stamp}\t{success_image or 'not_applicable'}")
PY_EVIDENCE
)"; then
    fail "deployed source authority is indeterminate; inspect runtime/deployments before continuing"
  fi

  local evidence_commit evidence_tail
  evidence_commit="${deployment_evidence%%$'\t'*}"
  evidence_tail="${deployment_evidence#*$'\t'}"
  EXPECTED_DEPLOYMENT_EVIDENCE="${evidence_tail%%$'\t'*}"
  evidence_tail="${evidence_tail#*$'\t'}"
  VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID="${evidence_tail#*$'\t'}"
  [[ "$VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID=""
  VERIFIED_DEPLOYED_SOURCE="$evidence_commit"
}

resolve_deployed_source_authority() {
  if [[ -z "$REQUESTED_SOURCE_REF" ]]; then
    if [[ "$SOURCE_SELECTION_CHECK_ONLY" == "0" ]] \
      && docker volume inspect nexolab-edge_edge-data >/dev/null 2>&1; then
      resolve_latest_deployment_evidence
    fi
    return 0
  fi
  validate_full_sha "$REQUESTED_SOURCE_REF" || fail "--source-ref must be a full lowercase 40-character commit SHA"
  validate_full_sha "$EXPECTED_DEPLOYED_SOURCE" || fail "--expected-deployed-source must be a full lowercase 40-character commit SHA"
  resolve_latest_deployment_evidence
  [[ "$VERIFIED_DEPLOYED_SOURCE" == "$EXPECTED_DEPLOYED_SOURCE" ]] \
    || fail "expected deployed source does not match the latest authoritative successful deployment evidence"
}

validate_selected_source_against_control() {
  TARGET_HEAD="$CONTROL_HEAD"
  if [[ -n "$REQUESTED_SOURCE_REF" ]]; then
    [[ -n "$VERIFIED_DEPLOYED_SOURCE" && -n "$EXPECTED_DEPLOYMENT_EVIDENCE" ]] \
      || fail "historical source selection requires verified deployed-source authority"
    git cat-file -e "${REQUESTED_SOURCE_REF}^{commit}" 2>/dev/null || fail "requested source commit is not available locally"
    git cat-file -e "${EXPECTED_DEPLOYED_SOURCE}^{commit}" 2>/dev/null || fail "expected deployed source commit is not available locally"
    git merge-base --is-ancestor "$REQUESTED_SOURCE_REF" "$CONTROL_HEAD" \
      || fail "requested source is not contained in current main history"
    git merge-base --is-ancestor "$EXPECTED_DEPLOYED_SOURCE" "$REQUESTED_SOURCE_REF" \
      || fail "requested source is not a fast-forward descendant of the expected deployed source"
    TARGET_HEAD="$REQUESTED_SOURCE_REF"
    log "Approved historical-main source selection: deployed=$EXPECTED_DEPLOYED_SOURCE target=$TARGET_HEAD origin_main=$CONTROL_HEAD evidence=$EXPECTED_DEPLOYMENT_EVIDENCE"
  else
    [[ -z "$EXPECTED_DEPLOYED_SOURCE" ]] || fail "--expected-deployed-source requires --source-ref"
    log "Current-main source selection: target=$TARGET_HEAD"
  fi
}

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "tracked local changes detected before source selection"
fi
[[ "$(git branch --show-current)" == "main" ]] || fail "deployment must start from the main branch"

if [[ "$SOURCE_SELECTION_CHECK_ONLY" == "1" ]]; then
  log "Fetching current main for source-selection preflight"
  git fetch --prune origin main
  CONTROL_HEAD="$(git rev-parse origin/main 2>/dev/null || true)"
  [[ -n "$CONTROL_HEAD" ]] || fail "origin/main is unavailable after source-selection preflight fetch"
  git merge --ff-only "$CONTROL_HEAD" >/dev/null || fail "local main cannot fast-forward to fresh origin/main for source-selection preflight"
  [[ "$(git rev-parse HEAD)" == "$CONTROL_HEAD" ]] || fail "local main is not synchronized to fresh origin/main for source-selection preflight"
  resolve_deployed_source_authority
  validate_selected_source_against_control
  if [[ "$TARGET_HEAD" != "$CONTROL_HEAD" ]]; then
    git switch --detach "$TARGET_HEAD" >/dev/null
    SOURCE_CHECKOUT_RESTORE_REQUIRED="1"
    [[ "$(git rev-parse HEAD)" == "$TARGET_HEAD" ]] || fail "source-selection checkout does not match requested target"
    restore_control_checkout || fail "source-selection preflight could not restore main"
  fi
  printf 'SOURCE_SELECTION_VALIDATED\n'
  printf 'target=%s\n' "$TARGET_HEAD"
  printf 'expected_deployed_source=%s\n' "${EXPECTED_DEPLOYED_SOURCE:-not_supplied}"
  printf 'origin_main=%s\n' "$CONTROL_HEAD"
  exit 0
fi

for command in docker curl python3 openssl npm node flock ip sudo tar du df find sort stat mv rm ss sha256sum cp cmp install setsid ps awk; do
  require "$command"
done
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"

log "Starting controlled current-head deployment"
log "Repository: $REPO"
log "Runtime mode: $RUNTIME_MODE"
if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then log "Frontend candidate source: verified off-device artifact ($FRONTEND_ARTIFACT_DIR)"; else log "Frontend candidate source: bounded local build fallback"; fi
log "Evidence: $AUDIT_DIR"

PG_CONTAINER="$(docker ps -q \
  --filter label=com.docker.compose.project=nexolab-central \
  --filter label=com.docker.compose.service=postgres \
  | head -n 1)"

recover_interrupted_pre_mutation_quiesce
resolve_deployed_source_authority
log "Applying bounded deployment-evidence retention"
if ! nexolab_prune_deployment_evidence "$REPO/runtime/deployments" "$AUDIT_DIR" "$EXPECTED_DEPLOYMENT_EVIDENCE"; then
  fail "deployment evidence retention failed before runtime mutation"
fi
log "Running deployment capacity preflight before evidence capture"
if ! nexolab_capacity_preflight "$REPO" "$AUDIT_DIR" "$PG_CONTAINER" "$AUDIT_DIR/capacity-preflight.txt"; then
  fail "deployment capacity preflight failed before runtime mutation; see $AUDIT_DIR/capacity-preflight.txt"
fi

log "Fetching current main for deployment authority"
git fetch --prune origin main
git switch main
git pull --ff-only origin main
CONTROL_HEAD="$(git rev-parse origin/main)"
[[ "$(git rev-parse HEAD)" == "$CONTROL_HEAD" ]] || fail "local main is not at origin/main after fetch"
validate_selected_source_against_control

{
  echo '=== host ==='
  date --iso-8601=seconds
  hostnamectl 2>/dev/null || true
  uname -a
  free -h || true
  df -h / "$REPO" || true
  echo
  echo '=== network ==='
  ip -4 -br address || true
  ip route || true
  echo
  echo '=== git ==='
  git branch --show-current
  git rev-parse HEAD
  git log -5 --oneline
  git status --short
  echo
  echo '=== docker ==='
  docker version
  docker compose version
  docker compose ls
  docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  docker volume ls
  echo
  echo '=== ports ==='
  sudo ss -ltnp || true
} > "$AUDIT_DIR/pre-deployment-inventory.txt" 2>&1

mkdir -p "$AUDIT_DIR/config-backup"
for file in \
  "$CENTRAL_DIR/.env.central" \
  "$CENTRAL_DIR/.env.edge" \
  "$CENTRAL_DIR/.env.edge-central" \
  "$CENTRAL_DIR/.env.edge-secure" \
  "$CENTRAL_DIR/.env.observability.local" \
  "$ROOT_ENV" \
  "$RUNTIME_MODE_FILE" \
  "$CENTRAL_DIR/m4-session-acceptance-local.py"; do
  if [[ -f "$file" ]]; then
    cp -a "$file" "$AUDIT_DIR/config-backup/"
  fi
done

git diff > "$AUDIT_DIR/tracked-working-tree.patch"
git diff --cached > "$AUDIT_DIR/tracked-index.patch"
git ls-files --others --exclude-standard > "$AUDIT_DIR/untracked-files.txt"

log "Rechecking deployment capacity immediately before large evidence writes"
if ! nexolab_capacity_preflight "$REPO" "$AUDIT_DIR" "$PG_CONTAINER" "$AUDIT_DIR/capacity-preflight.txt"; then
  fail "deployment capacity recheck failed before large writes; see $AUDIT_DIR/capacity-preflight.txt"
fi

if [[ -d "$REPO/runtime/evidence" ]]; then
  RUNTIME_ARCHIVE_TMP="$AUDIT_DIR/.runtime-evidence.tar.gz.partial"
  rm -f -- "$RUNTIME_ARCHIVE_TMP"
  if ! tar -C "$REPO" -czf "$RUNTIME_ARCHIVE_TMP" runtime/evidence; then
    rm -f -- "$RUNTIME_ARCHIVE_TMP"
    fail "runtime evidence archive failed; partial archive was removed"
  fi
  mv -- "$RUNTIME_ARCHIVE_TMP" "$AUDIT_DIR/runtime-evidence.tar.gz"
fi

docker volume inspect \
  nexolab-central-postgres-data \
  nexolab-central-mqtt-data \
  nexolab-central-object-storage-data \
  nexolab-central-telemetry-ingestion-data \
  nexolab-edge_edge-data \
  nexolab-edge_mqtt-data \
  > "$AUDIT_DIR/volume-identities-before.json" 2>"$AUDIT_DIR/volume-identities-before.err" || true

if [[ -n "$PG_CONTAINER" ]]; then
  log "Creating PostgreSQL pre-upgrade backup"
  PG_DUMP_TMP="$AUDIT_DIR/.postgresql-pre-upgrade.dump.partial"
  rm -f -- "$PG_DUMP_TMP"
  if ! docker exec "$PG_CONTAINER" sh -ec \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$PG_DUMP_TMP"; then
    rm -f -- "$PG_DUMP_TMP"
    fail "PostgreSQL backup failed; partial dump was removed"
  fi
  if [[ ! -s "$PG_DUMP_TMP" ]]; then
    rm -f -- "$PG_DUMP_TMP"
    fail "PostgreSQL backup is empty; partial dump was removed"
  fi
  mv -- "$PG_DUMP_TMP" "$AUDIT_DIR/postgresql-pre-upgrade.dump"
else
  log "No running central PostgreSQL container found; skipping live pg_dump"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "tracked local changes detected; patches were saved in $AUDIT_DIR"
fi

EDGE_SNAPSHOT_HELPER="$AUDIT_DIR/deploy-edge-sqlite-snapshot.py"
install -m 0500 "$SCRIPT_DIR/deploy-edge-sqlite-snapshot.py" "$EDGE_SNAPSHOT_HELPER"
sha256sum "$EDGE_SNAPSHOT_HELPER" > "$AUDIT_DIR/deploy-edge-sqlite-snapshot.sha256"

if [[ "$TARGET_HEAD" != "$CONTROL_HEAD" ]]; then
  log "Switching temporarily to approved historical main source: $TARGET_HEAD"
  git switch --detach "$TARGET_HEAD" >/dev/null
  SOURCE_CHECKOUT_RESTORE_REQUIRED="1"
fi
CURRENT_HEAD="$(git rev-parse HEAD)"
[[ "$CURRENT_HEAD" == "$TARGET_HEAD" ]] || fail "deployment checkout does not match selected source"
log "Deployment source: $CURRENT_HEAD"
log "Control origin/main: $CONTROL_HEAD"

capture_edge_sqlite_snapshot() {
  local edge_volume="nexolab-edge_edge-data"
  local snapshot="$AUDIT_DIR/edge-sqlite-pre-cutover.db"
  local metadata="$AUDIT_DIR/edge-sqlite-pre-cutover.json"
  local deployed_source="${VERIFIED_DEPLOYED_SOURCE:-${EXPECTED_DEPLOYED_SOURCE:-}}"
  local -a edge_containers=()

  if ! docker volume inspect "$edge_volume" >/dev/null 2>&1; then
    mapfile -t edge_containers < <(
      docker ps -aq \
        --filter label=com.docker.compose.project=nexolab-edge \
        --filter label=com.docker.compose.service=device-agent
    )
    [[ "${#edge_containers[@]}" == "0" ]] \
      || fail "Device Agent container exists without the expected edge-data volume"
    log "No existing edge runtime found; edge SQLite snapshot is not applicable"
    return 0
  fi

  mapfile -t edge_containers < <(
    docker ps -aq \
      --filter label=com.docker.compose.project=nexolab-edge \
      --filter label=com.docker.compose.service=device-agent
  )
  [[ "${#edge_containers[@]}" == "1" ]] \
    || fail "edge SQLite snapshot requires exactly one known Device Agent container"
  local edge_container="${edge_containers[0]}"
  [[ "$(docker inspect --format '{{.State.Running}}' "$edge_container")" == "false" ]] \
    || fail "Device Agent must be quiesced before the final edge SQLite snapshot"
  if ! validate_full_sha "$deployed_source"; then
    resolve_latest_deployment_evidence
    deployed_source="$VERIFIED_DEPLOYED_SOURCE"
  fi
  validate_full_sha "$deployed_source" \
    || fail "exact deployed source authority is required before edge SQLite snapshot"
  [[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination \"/var/lib/nexolab\"}}{{.Name}}{{end}}{{end}}' "$edge_container")" == "$edge_volume" ]] \
    || fail "Device Agent edge-data volume identity is unexpected"
  local edge_image
  edge_image="$(docker inspect --format '{{.Image}}' "$edge_container")"
  [[ -n "$edge_image" ]] || fail "Device Agent image identity is unavailable for edge SQLite snapshot"
  if [[ -n "$VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID" ]]; then
    [[ "$edge_image" == "$VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID" ]] \
      || fail "Device Agent container image does not match verified recovery authority; complete the explicit restart verification first"
  fi

  log "Capturing consistent pre-cutover edge SQLite snapshot"
  if ! docker run --rm --user "$(id -u):$(id -g)" \
    --volumes-from "$edge_container" \
    --mount "type=bind,src=$AUDIT_DIR,dst=/evidence" \
    --entrypoint /usr/bin/python3 \
    "$edge_image" \
    /evidence/deploy-edge-sqlite-snapshot.py capture \
      --source /var/lib/nexolab/edge.db \
      --snapshot /evidence/edge-sqlite-pre-cutover.db \
      --metadata /evidence/edge-sqlite-pre-cutover.json \
      --deployed-source "$deployed_source" \
      --target-source "$CURRENT_HEAD" \
      --deployment-evidence-id "$STAMP" \
      --deployed-device-agent-image-id "$edge_image" \
      > "$AUDIT_DIR/edge-sqlite-capture-result.json"; then
    rm -f -- "$snapshot" "$metadata" "$AUDIT_DIR/edge-sqlite-capture-result.json"
    fail "required edge SQLite snapshot/verification failed before runtime mutation"
  fi
  chmod 0600 "$snapshot" "$metadata" "$AUDIT_DIR/edge-sqlite-capture-result.json"
  python3 - "$metadata" >> "$SUMMARY" <<'PY_EDGE_SNAPSHOT'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    evidence = json.load(stream)
print(
    "edge_sqlite_snapshot="
    f"sha256:{evidence['sha256']} "
    f"bytes:{evidence['bytes']} "
    f"registry_revision:{evidence['registry_revision']} "
    f"outbound_queue_count:{evidence['outbound_queue_count']} "
    f"source_quick_check:{evidence['source_quick_check']} "
    f"snapshot_quick_check:{evidence['snapshot_quick_check']}"
)
PY_EDGE_SNAPSHOT
}

persist_edge_device_agent_quiesce_record() {
  local container_id="$1"
  local image_id="$2"
  python3 - "$AUDIT_DIR/edge-device-agent-quiesce.json" \
    "$STAMP" "$container_id" "$image_id" "$CURRENT_HEAD" <<'PY_QUIESCE_RECORD'
import json
import os
from pathlib import Path
import sys
from datetime import datetime

record = Path(sys.argv[1])
temporary = record.with_name(f".{record.name}.tmp-{os.getpid()}")
document = {
    "schema_version": 1,
    "kind": "nexolab-edge-device-agent-quiesce",
    "deployment_evidence_id": sys.argv[2],
    "container_id": sys.argv[3],
    "image_id": sys.argv[4],
    "target_source": sys.argv[5],
    "recorded_at": datetime.now().astimezone().isoformat(),
}
try:
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, record)
    directory_fd = os.open(record.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    temporary.unlink(missing_ok=True)
PY_QUIESCE_RECORD
}

quiesce_edge_device_agent_for_cutover() {
  local edge_volume="nexolab-edge_edge-data"
  local -a edge_containers=()
  if ! docker volume inspect "$edge_volume" >/dev/null 2>&1; then
    return 0
  fi
  mapfile -t edge_containers < <(
    docker ps -aq \
      --filter label=com.docker.compose.project=nexolab-edge \
      --filter label=com.docker.compose.service=device-agent
  )
  [[ "${#edge_containers[@]}" == "1" ]] \
    || fail "Device Agent quiesce requires exactly one known container"
  local edge_container="${edge_containers[0]}"
  if [[ "$(docker inspect --format '{{.State.Running}}' "$edge_container")" == "true" ]]; then
    EDGE_DEVICE_AGENT_QUIESCED_CONTAINER="$(docker inspect --format '{{.Id}}' "$edge_container")"
    EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$edge_container")"
    [[ "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER" =~ ^[0-9a-f]{64}$ ]] \
      || fail "Device Agent container identity is invalid before quiesce"
    [[ "$EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] \
      || fail "Device Agent image identity is invalid before quiesce"
    if [[ -n "$VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID" ]]; then
      [[ "$EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID" == "$VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID" ]] \
        || fail "running Device Agent image does not match verified recovery authority"
    fi
    persist_edge_device_agent_quiesce_record \
      "$EDGE_DEVICE_AGENT_QUIESCED_CONTAINER" \
      "$EDGE_DEVICE_AGENT_PRE_CUTOVER_IMAGE_ID" \
      || fail "durable Device Agent quiesce record could not be published"
    EDGE_DEVICE_AGENT_QUIESCE_EVIDENCE="$AUDIT_DIR"
    EDGE_DEVICE_AGENT_QUIESCED_BY_DEPLOYMENT="1"
    log "Quiescing Device Agent at the edge SQLite snapshot boundary"
    docker stop --time 30 "$edge_container" >/dev/null \
      || fail "Device Agent could not be quiesced before snapshot capture"
  fi
  [[ "$(docker inspect --format '{{.State.Running}}' "$edge_container")" == "false" ]] \
    || fail "Device Agent remained active at the edge SQLite snapshot boundary"
}

write_durable_runtime_mutation_marker() {
  python3 - "$AUDIT_DIR/runtime-mutation-started" "$CURRENT_HEAD" <<'PY_MUTATION_MARKER'
import os
from pathlib import Path
import sys
from datetime import datetime

marker = Path(sys.argv[1])
source = sys.argv[2]
temporary = marker.with_name(f".{marker.name}.tmp-{os.getpid()}")
try:
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(f"source={source}\nstarted_at={datetime.now().astimezone().isoformat()}\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, marker)
    directory_fd = os.open(marker.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    temporary.unlink(missing_ok=True)
PY_MUTATION_MARKER
  EDGE_DEVICE_AGENT_QUIESCED_BY_DEPLOYMENT="0"
}

env_get() {
  local file=$1 key=$2
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file" 2>/dev/null || true
}

env_set() {
  local file=$1 key=$2 value=$3
  python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
replacement = f"{key}={value}"
for index, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[index] = replacement
        break
else:
    lines.append(replacement)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

ensure_secret() {
  local file=$1 key=$2
  local value
  value="$(env_get "$file" "$key")"
  if [[ -z "$value" || "$value" == replace-with-* ]]; then
    value="$(openssl rand -hex 32)"
    env_set "$file" "$key" "$value"
  fi
}

resolve_compose_path() {
  local value=$1
  if [[ "$value" == /* ]]; then
    printf '%s\n' "$value"
  else
    printf '%s/%s\n' "$CENTRAL_DIR" "$value"
  fi
}

if [[ ! -f "$CENTRAL_ENV" ]]; then
  if docker volume inspect nexolab-central-postgres-data >/dev/null 2>&1; then
    fail "existing PostgreSQL volume found but .env.central is missing"
  fi
  cp "$CENTRAL_DIR/.env.central.example" "$CENTRAL_ENV"
fi
chmod 0600 "$CENTRAL_ENV"

LAN_BIND_IP=""
if [[ "$RUNTIME_MODE" == "lan" ]]; then
  LAN_BIND_IP="$(env_get "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS)"
  if [[ -z "$LAN_BIND_IP" || "$LAN_BIND_IP" == "127.0.0.1" ]]; then
    if ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -qx '172.20.10.10'; then
      LAN_BIND_IP='172.20.10.10'
    else
      LAN_BIND_IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n 1)"
    fi
  fi
  [[ -n "$LAN_BIND_IP" ]] || fail "no trusted IPv4 address detected for lan mode"
  ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -qx "$LAN_BIND_IP" \
    || fail "CENTRAL_BIND_ADDRESS is not assigned to this host: $LAN_BIND_IP"
fi

nexolab_configure_runtime_contract "$RUNTIME_MODE" "$LAN_BIND_IP" || exit $?
BIND_IP="$NEXOLAB_HOST_BIND_ADDRESS"
log "Host bind address: $BIND_IP"
log "Dashboard origin: $NEXOLAB_DASHBOARD_ORIGIN"

if [[ "$NEXOLAB_USE_STANDALONE_OVERLAYS" == "true" ]]; then
  CENTRAL_COMPOSE_ARGS+=( -f "$CENTRAL_DIR/compose.central-standalone.yaml" )
  EDGE_COMPOSE_ARGS+=( -f "$CENTRAL_DIR/compose.edge-standalone.yaml" )
fi

env_set "$CENTRAL_ENV" CENTRAL_RESOURCE_PREFIX nexolab-central
env_set "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS "$BIND_IP"
env_set "$CENTRAL_ENV" CENTRAL_API_PORT 8082
env_set "$CENTRAL_ENV" CENTRAL_MQTT_PORT 1884
env_set "$CENTRAL_ENV" CENTRAL_OBJECT_STORAGE_PORT 9000
env_set "$CENTRAL_ENV" CENTRAL_OBJECT_STORAGE_CONSOLE_PORT 9001
env_set "$CENTRAL_ENV" TELEMETRY_SERVICE_IMAGE nexolab-telemetry-service:local
env_set "$CENTRAL_ENV" MINIO_ROOT_USER nexolab-storage
ensure_secret "$CENTRAL_ENV" POSTGRES_PASSWORD
ensure_secret "$CENTRAL_ENV" MINIO_ROOT_PASSWORD
env_set "$CENTRAL_ENV" OBJECT_STORAGE_BUCKET nexolab-equipment-images
env_set "$CENTRAL_ENV" OBJECT_STORAGE_PUBLIC_ENDPOINT_URL "$NEXOLAB_OBJECT_STORAGE_PUBLIC_URL"
env_set "$CENTRAL_ENV" CORS_ALLOWED_ORIGINS "$NEXOLAB_CORS_ALLOWED_ORIGINS"
env_set "$CENTRAL_ENV" CORS_ALLOW_CREDENTIALS false
env_set "$CENTRAL_ENV" AUTH_DEFAULT_ORGANIZATION_ID 00000000-0000-0000-0000-000000000001
env_set "$CENTRAL_ENV" MQTT_NODE_REGISTRY_ENFORCED false
env_set "$CENTRAL_ENV" MQTT_TOPIC nexolab/telemetry
env_set "$CENTRAL_ENV" MQTT_CLIENT_ID nexolab-central-telemetry-ingestion
env_set "$CENTRAL_ENV" OBSERVABILITY_RESOURCE_PREFIX nexolab-observability
env_set "$CENTRAL_ENV" OBSERVABILITY_BIND_ADDRESS 127.0.0.1
env_set "$CENTRAL_ENV" PROMETHEUS_PORT 9090
env_set "$CENTRAL_ENV" ALERTMANAGER_PORT 9093
env_set "$CENTRAL_ENV" GRAFANA_PORT 3001
env_set "$CENTRAL_ENV" GRAFANA_ADMIN_USER nexolab-admin
ensure_secret "$CENTRAL_ENV" GRAFANA_ADMIN_PASSWORD

AUTH_MODE_VALUE="$(env_get "$CENTRAL_ENV" AUTH_MODE)"
[[ -n "$AUTH_MODE_VALUE" ]] || fail "AUTH_MODE must be configured explicitly"
[[ "$AUTH_MODE_VALUE" != "disabled" ]] \
  || fail "AUTH_MODE=disabled is development-only and forbidden for controlled Raspberry Pi deployment"
log "Authentication mode preserved: $AUTH_MODE_VALUE"

LOCAL_AUTH_OVERLAY_ENABLED="false"
if [[ "$AUTH_MODE_VALUE" == "jwt" ]]; then
  LOCAL_PRIVATE="$(env_get "$CENTRAL_ENV" AUTH_LOCAL_PRIVATE_KEY_HOST_FILE)"
  LOCAL_PUBLIC="$(env_get "$CENTRAL_ENV" AUTH_LOCAL_PUBLIC_KEY_HOST_FILE)"
  JWKS_URL="$(env_get "$CENTRAL_ENV" AUTH_JWT_JWKS_URL)"
  if [[ -n "$LOCAL_PRIVATE" && -n "$LOCAL_PUBLIC" \
    && -r "$(resolve_compose_path "$LOCAL_PRIVATE")" \
    && -r "$(resolve_compose_path "$LOCAL_PUBLIC")" ]]; then
    CENTRAL_COMPOSE_ARGS+=( -f "$CENTRAL_DIR/compose.local-auth.yaml" )
    LOCAL_AUTH_OVERLAY_ENABLED="true"
    log "Enabled fail-closed local operator authentication overlay"
  elif [[ "$RUNTIME_MODE" == "standalone" && -n "$JWKS_URL" ]]; then
    fail "standalone mode cannot depend on remote AUTH_JWT_JWKS_URL; configure local auth keys or a local static key"
  else
    log "JWT profile preserved without local-auth overlay; operator-owned static provider settings remain authoritative"
  fi
fi

FRONTEND_AUTH_PROVIDER="disabled"
if [[ "$LOCAL_AUTH_OVERLAY_ENABLED" == "true" ]]; then
  FRONTEND_AUTH_PROVIDER="local"
fi
FRONTEND_ORGANIZATION_ID="$(env_get "$CENTRAL_ENV" AUTH_DEFAULT_ORGANIZATION_ID)"
[[ -n "$FRONTEND_ORGANIZATION_ID" ]] || fail "AUTH_DEFAULT_ORGANIZATION_ID must be configured"

if [[ ! -f "$EDGE_ENV" ]]; then
  if [[ -f "$CENTRAL_DIR/.env.edge" ]]; then
    cp "$CENTRAL_DIR/.env.edge" "$EDGE_ENV"
  else
    fail ".env.edge-central is missing; real RS-485 settings cannot be invented"
  fi
fi
chmod 0600 "$EDGE_ENV"
RS485_DEVICE="$(env_get "$EDGE_ENV" RS485_HOST_DEVICE)"
[[ "$RS485_DEVICE" == /dev/serial/by-id/* ]] || fail "RS485_HOST_DEVICE must use /dev/serial/by-id/..."
[[ -e "$RS485_DEVICE" ]] || fail "RS-485 adapter is not present: $RS485_DEVICE"
env_set "$EDGE_ENV" NEXOLAB_NODE_ID edge-01
env_set "$EDGE_ENV" DEVICE_AGENT_IMAGE nexolab-device-agent:local
env_set "$EDGE_ENV" CENTRAL_RUNTIME_NETWORK nexolab-central
env_set "$EDGE_ENV" CENTRAL_MQTT_HOST "$NEXOLAB_EDGE_CENTRAL_MQTT_HOST"
env_set "$EDGE_ENV" CENTRAL_MQTT_PORT "$NEXOLAB_EDGE_CENTRAL_MQTT_PORT"
env_set "$EDGE_ENV" CENTRAL_MQTT_TOPIC nexolab/telemetry
env_set "$EDGE_ENV" CENTRAL_API_BASE_URL "$NEXOLAB_EDGE_CENTRAL_API_BASE_URL"
env_set "$EDGE_ENV" CENTRAL_WEBSOCKET_URL "$NEXOLAB_EDGE_CENTRAL_WEBSOCKET_URL"

cat > "$ROOT_ENV" <<EOF_ENV
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=$NEXOLAB_API_BASE_URL
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=$NEXOLAB_WEBSOCKET_URL
NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=$FRONTEND_AUTH_PROVIDER
NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=$FRONTEND_ORGANIZATION_ID
EOF_ENV
chmod 0600 "$ROOT_ENV"

if [[ "$LOCAL_AUTH_OVERLAY_ENABLED" == "true" ]]; then
  [[ "$(env_get "$ROOT_ENV" NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER)" == "local" ]] \
    || fail "local-auth overlay requires NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local before dashboard build"
  [[ "$(env_get "$ROOT_ENV" NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID)" == "$FRONTEND_ORGANIZATION_ID" ]] \
    || fail "local-auth overlay requires dashboard organization scope to match AUTH_DEFAULT_ORGANIZATION_ID"
fi

mkdir -p "$REPO/runtime/observability"
chmod 0700 "$REPO/runtime/observability"
if [[ ! -f "$REPO/runtime/observability/disaster-recovery.prom" ]]; then
  cat > "$REPO/runtime/observability/disaster-recovery.prom" <<'EOF_PROM'
# Actual-host DR scheduler is not commissioned yet. Zero values are intentional and alertable.
# HELP nexolab_dr_last_verified_backup_timestamp_seconds Unix timestamp of the newest verified encrypted backup.
# TYPE nexolab_dr_last_verified_backup_timestamp_seconds gauge
nexolab_dr_last_verified_backup_timestamp_seconds 0
# HELP nexolab_dr_last_off_host_copy_timestamp_seconds Unix timestamp of the newest verified off-host copy.
# TYPE nexolab_dr_last_off_host_copy_timestamp_seconds gauge
nexolab_dr_last_off_host_copy_timestamp_seconds 0
# HELP nexolab_dr_last_restore_rehearsal_timestamp_seconds Unix timestamp of the newest restore rehearsal.
# TYPE nexolab_dr_last_restore_rehearsal_timestamp_seconds gauge
nexolab_dr_last_restore_rehearsal_timestamp_seconds 0
# HELP nexolab_dr_last_bundle_verification_success Whether the newest bundle passed verification.
# TYPE nexolab_dr_last_bundle_verification_success gauge
nexolab_dr_last_bundle_verification_success 0
EOF_PROM
  chmod 0600 "$REPO/runtime/observability/disaster-recovery.prom"
fi

log "Validating Compose models"
docker compose --env-file "$CENTRAL_ENV" "${CENTRAL_COMPOSE_ARGS[@]}" config --quiet
docker compose --env-file "$EDGE_ENV" "${EDGE_COMPOSE_ARGS[@]}" config --quiet

if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then
  log "Skipping frontend build headroom gate because a verified off-device artifact was supplied"
  {
    echo 'status=SKIPPED_OFF_DEVICE_ARTIFACT'
    echo "mem_available_kib=$(nexolab_frontend_mem_available_kib)"
    echo "swap_free_kib=$(nexolab_frontend_swap_free_kib)"
  } > "$AUDIT_DIR/frontend-resource-preflight.txt"
else
  log "Checking frontend deployment resource headroom for bounded local build fallback"
  if ! nexolab_frontend_resource_preflight "$AUDIT_DIR/frontend-resource-preflight.txt"; then
    fail "frontend resource preflight failed before candidate build; active dashboard was not touched"
  fi
fi
if ! nexolab_frontend_assert_no_competing_builds "$AUDIT_DIR/frontend-competing-processes.txt"; then
  fail "another heavy build/acceptance workload is active; refusing concurrent production deployment"
fi

log "Building current Device Agent image"
docker build --pull -t nexolab-device-agent:local "$REPO/services/device-agent"

EXPECTED_NODE_VERSION="$(tr -d '[:space:]' < "$REPO/.nvmrc")"
[[ -n "$EXPECTED_NODE_VERSION" ]] || fail "repository .nvmrc is empty"
ACTUAL_NODE_VERSION="$(node --version | sed 's/^v//')"
[[ "$ACTUAL_NODE_VERSION" == "$EXPECTED_NODE_VERSION" ]] \
  || fail "host Node version $ACTUAL_NODE_VERSION does not match repository baseline $EXPECTED_NODE_VERSION"
FRONTEND_RELEASE_DIR="$FRONTEND_RELEASES_DIR/${CURRENT_HEAD}-${STAMP}"
mkdir -p "$FRONTEND_RELEASES_DIR"
log "Preparing immutable frontend candidate: $FRONTEND_RELEASE_DIR"
if ! nexolab_frontend_prepare_release_source "$REPO" "$CURRENT_HEAD" "$FRONTEND_RELEASE_DIR" "$ROOT_ENV"; then
  fail "failed to prepare immutable frontend candidate source"
fi

if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then
  log "Importing verified off-device frontend artifact"
  if ! nexolab_frontend_import_artifact \
    "$FRONTEND_ARTIFACT_DIR" \
    "$REPO" \
    "$FRONTEND_RELEASE_DIR" \
    "$CURRENT_HEAD" \
    live \
    "$NEXOLAB_API_BASE_URL" \
    "$NEXOLAB_WEBSOCKET_URL" \
    "$FRONTEND_AUTH_PROVIDER" \
    "$FRONTEND_ORGANIZATION_ID" \
    "$AUDIT_DIR/frontend-artifact-import.txt"; then
    fail "off-device frontend artifact verification/import failed; active dashboard was not touched"
  fi
  printf '%s\n' 'status=SKIPPED_OFF_DEVICE_ARTIFACT' > "$AUDIT_DIR/frontend-build.txt"
else
  log "Building frontend candidate inside a bounded container"
  export NEXOLAB_FRONTEND_BUILD_IMAGE="${NEXOLAB_FRONTEND_BUILD_IMAGE:-node:${EXPECTED_NODE_VERSION}-bookworm-slim}"
  if ! nexolab_frontend_build_release \
    "$FRONTEND_RELEASE_DIR" \
    live \
    "$NEXOLAB_API_BASE_URL" \
    "$NEXOLAB_WEBSOCKET_URL" \
    "$FRONTEND_AUTH_PROVIDER" \
    "$FRONTEND_ORGANIZATION_ID" \
    > "$AUDIT_DIR/frontend-build.txt" 2>&1; then
    fail "bounded frontend candidate build failed; active dashboard was not touched"
  fi
fi

log "Verifying compiled frontend public runtime contract"
if ! nexolab_frontend_verify_public_contract \
  "$FRONTEND_RELEASE_DIR" \
  live \
  "$NEXOLAB_API_BASE_URL" \
  "$NEXOLAB_WEBSOCKET_URL" \
  "$FRONTEND_AUTH_PROVIDER" \
  "$FRONTEND_ORGANIZATION_ID" \
  "$AUDIT_DIR/frontend-public-contract.txt"; then
  fail "frontend candidate public runtime contract does not match this deployment"
fi
nexolab_frontend_write_provenance \
  "$FRONTEND_RELEASE_DIR" \
  "$CURRENT_HEAD" \
  "$RUNTIME_MODE" \
  "$NEXOLAB_API_BASE_URL" \
  "$NEXOLAB_WEBSOCKET_URL" \
  "$FRONTEND_AUTH_PROVIDER" \
  "$FRONTEND_ORGANIZATION_ID"

FRONTEND_CANDIDATE_PORT="${NEXOLAB_FRONTEND_CANDIDATE_PORT:-3100}"
if ss -ltn | awk '{print $4}' | grep -Eq "(^|:)$FRONTEND_CANDIDATE_PORT$"; then
  fail "frontend candidate verification port is already in use: $FRONTEND_CANDIDATE_PORT"
fi
log "Starting frontend candidate on isolated port $FRONTEND_CANDIDATE_PORT"
FRONTEND_CANDIDATE_START_GATE="$AUDIT_DIR/frontend-candidate-start.gate"
rm -f -- "$FRONTEND_CANDIDATE_START_GATE"
FRONTEND_CANDIDATE_PARENT_PID="$BASHPID"
(
  trap - EXIT ERR
  for _ in $(seq 1 100); do
    if [[ -f "$FRONTEND_CANDIDATE_START_GATE" ]]; then
      break
    fi
    if ! kill -0 "$FRONTEND_CANDIDATE_PARENT_PID" >/dev/null 2>&1; then
      exit 75
    fi
    sleep 0.01
  done
  [[ -f "$FRONTEND_CANDIDATE_START_GATE" ]] || exit 75
  cd "$FRONTEND_RELEASE_DIR"
  exec setsid env \
    NEXT_PUBLIC_NEXOLAB_DATA_MODE=live \
    NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$NEXOLAB_API_BASE_URL" \
    NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="$NEXOLAB_WEBSOCKET_URL" \
    NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="$FRONTEND_AUTH_PROVIDER" \
    NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$FRONTEND_ORGANIZATION_ID" \
    NEXT_TELEMETRY_DISABLED=1 \
    "$FRONTEND_RELEASE_DIR/node_modules/.bin/next" start \
      --hostname 127.0.0.1 --port "$FRONTEND_CANDIDATE_PORT"
) > "$AUDIT_DIR/frontend-candidate.txt" 2>&1 &
FRONTEND_CANDIDATE_PID=$!
: > "$FRONTEND_CANDIDATE_START_GATE"
FRONTEND_CANDIDATE_PGID=""
for _ in $(seq 1 20); do
  FRONTEND_CANDIDATE_ACTUAL_PGID="$(ps -o pgid= -p "$FRONTEND_CANDIDATE_PID" 2>/dev/null | awk 'NF {print $1; exit}')"
  if [[ "$FRONTEND_CANDIDATE_ACTUAL_PGID" == "$FRONTEND_CANDIDATE_PID" ]]; then
    FRONTEND_CANDIDATE_PGID="$FRONTEND_CANDIDATE_ACTUAL_PGID"
    break
  fi
  if ! kill -0 "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1; then
    break
  fi
  sleep 0.05
done
rm -f -- "$FRONTEND_CANDIDATE_START_GATE"
FRONTEND_CANDIDATE_START_GATE=""
if [[ -z "$FRONTEND_CANDIDATE_PGID" ]]; then
  fail "frontend candidate did not establish its isolated process group; active dashboard was not touched"
fi
FRONTEND_CANDIDATE_READY=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$FRONTEND_CANDIDATE_PORT/" >/dev/null; then
    FRONTEND_CANDIDATE_READY=true
    break
  fi
  if ! kill -0 "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if [[ "$FRONTEND_CANDIDATE_READY" != true ]]; then
  fail "frontend candidate did not become ready; active dashboard was not touched"
fi
for route in / /nodes /live /energy /sessions; do
  curl -fsS --max-time 5 "http://127.0.0.1:$FRONTEND_CANDIDATE_PORT$route" >/dev/null \
    || fail "frontend candidate route failed: $route"
done
if ! cleanup_frontend_candidate; then
  fail "frontend candidate cleanup failed; active dashboard was not touched"
fi
if ss -ltn | awk '{print $4}' | grep -Eq "(^|:)$FRONTEND_CANDIDATE_PORT$"; then
  fail "frontend candidate cleanup left verification port in use: $FRONTEND_CANDIDATE_PORT"
fi
log "Frontend candidate verified and terminated without mutating the active dashboard"

quiesce_edge_device_agent_for_cutover
capture_edge_sqlite_snapshot
write_durable_runtime_mutation_marker
log "RUNTIME MUTATION STARTED: central backend activation"
log "Starting central backend, MinIO and observability"
docker compose --env-file "$CENTRAL_ENV" \
  "${CENTRAL_COMPOSE_ARGS[@]}" \
  up -d --build --wait

log "Starting real-hardware edge stack"
docker compose --env-file "$EDGE_ENV" \
  "${EDGE_COMPOSE_ARGS[@]}" \
  up -d --force-recreate mqtt device-agent

NODE_BIN_DIR="$(dirname "$(command -v node)")"
DASHBOARD_USER="$(id -un)"
DASHBOARD_GROUP="$(id -gn)"
DASHBOARD_UNIT="/etc/systemd/system/nexolab-dashboard.service"
DASHBOARD_UNIT_BACKUP="$AUDIT_DIR/dashboard-unit-before.service"
DASHBOARD_UNIT_CANDIDATE="$AUDIT_DIR/dashboard-unit-candidate.service"

if sudo test -f "$DASHBOARD_UNIT"; then
  sudo cp -a "$DASHBOARD_UNIT" "$DASHBOARD_UNIT_BACKUP"
  sudo chown "$DASHBOARD_USER:$DASHBOARD_GROUP" "$DASHBOARD_UNIT_BACKUP" || true
fi

cat > "$DASHBOARD_UNIT_CANDIDATE" <<EOF_UNIT
[Unit]
Description=NEXOLAB production dashboard
After=$NEXOLAB_SYSTEMD_AFTER
$(if [[ -n "$NEXOLAB_SYSTEMD_WANTS" ]]; then printf 'Wants=%s\n' "$NEXOLAB_SYSTEMD_WANTS"; fi)

[Service]
Type=simple
User=$DASHBOARD_USER
Group=$DASHBOARD_GROUP
WorkingDirectory=$FRONTEND_RELEASE_DIR
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
Environment=NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
Environment=NEXT_PUBLIC_NEXOLAB_API_BASE_URL=$NEXOLAB_API_BASE_URL
Environment=NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=$NEXOLAB_WEBSOCKET_URL
Environment=NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=$FRONTEND_AUTH_PROVIDER
Environment=NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=$FRONTEND_ORGANIZATION_ID
Environment=PATH=$NODE_BIN_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$FRONTEND_RELEASE_DIR/node_modules/.bin/next start --hostname $NEXOLAB_DASHBOARD_BIND_ADDRESS --port 3000
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF_UNIT

rollback_dashboard_release() {
  log "Rolling back dashboard service to the last-known-good unit"
  sudo systemctl stop nexolab-dashboard.service >/dev/null 2>&1 || true
  if [[ -f "$DASHBOARD_UNIT_BACKUP" ]]; then
    sudo install -m 0644 "$DASHBOARD_UNIT_BACKUP" "$DASHBOARD_UNIT"
    sudo systemctl daemon-reload
    sudo systemctl start nexolab-dashboard.service >/dev/null 2>&1 || true
  else
    sudo rm -f "$DASHBOARD_UNIT"
    sudo systemctl daemon-reload
  fi
}

log "Activating verified frontend release"
sudo systemctl stop nexolab-dashboard.service >/dev/null 2>&1 || true
if [[ -f "$REPO/runtime/dashboard.pid" ]]; then
  OLD_PID="$(cat "$REPO/runtime/dashboard.pid" 2>/dev/null || true)"
  if [[ "$OLD_PID" =~ ^[0-9]+$ ]]; then
    kill "$OLD_PID" >/dev/null 2>&1 || true
  fi
fi
sudo install -m 0644 "$DASHBOARD_UNIT_CANDIDATE" "$DASHBOARD_UNIT"
sudo systemctl daemon-reload
sudo systemctl enable nexolab-dashboard.service >/dev/null
if ! sudo systemctl start nexolab-dashboard.service; then
  rollback_dashboard_release
  fail "verified frontend release failed to start; last-known-good dashboard unit restored"
fi
DASHBOARD_ACTIVATED=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$NEXOLAB_DASHBOARD_ORIGIN" >/dev/null; then
    DASHBOARD_ACTIVATED=true
    break
  fi
  sleep 1
done
if [[ "$DASHBOARD_ACTIVATED" != true ]]; then
  rollback_dashboard_release
  fail "verified frontend release failed post-activation health check; last-known-good dashboard restored"
fi
NEXOLAB_FRONTEND_ACTIVATED=1
log "Activated frontend release: $FRONTEND_RELEASE_DIR"

wait_http() {
  local label=$1 url=$2 attempts=${3:-60}
  local index
  for index in $(seq 1 "$attempts"); do
    if curl -fsS --max-time 5 "$url" >/dev/null; then
      log "Ready: $label ($url)"
      return 0
    fi
    sleep 2
  done
  log "Not ready after activation: $label ($url)"
  return 1
}

wait_http_or_rollback() {
  local label=$1
  if wait_http "$@"; then
    return 0
  fi
  rollback_dashboard_release
  fail "post-activation readiness failed for $label; last-known-good dashboard restored"
}

wait_http_or_rollback telemetry "$NEXOLAB_API_BASE_URL/health/ready" 90
wait_http_or_rollback device-agent "http://127.0.0.1:8081/health" 90
wait_http_or_rollback dashboard "$NEXOLAB_DASHBOARD_ORIGIN" 90
wait_http_or_rollback prometheus "http://127.0.0.1:9090/-/ready" 90
wait_http_or_rollback alertmanager "http://127.0.0.1:9093/-/ready" 90
wait_http_or_rollback grafana "http://127.0.0.1:3001/api/health" 120
wait_http_or_rollback minio "$NEXOLAB_OBJECT_STORAGE_PUBLIC_URL/minio/health/live" 90

log "Running central smoke gate"
(
  cd "$CENTRAL_DIR"
  bash central-smoke.sh .env.central
) > "$AUDIT_DIR/central-smoke.txt" 2>&1

log "Verifying current API contracts"
python3 - "$NEXOLAB_API_BASE_URL" "$LOCAL_AUTH_OVERLAY_ENABLED" > "$AUDIT_DIR/api-contracts.txt" <<'PY'
import json
import sys
import urllib.request

base_url = sys.argv[1]
local_auth_enabled = sys.argv[2].lower() == "true"
with urllib.request.urlopen(f"{base_url}/openapi.json", timeout=15) as response:
    document = json.load(response)
paths = document.get("paths", {})
required = {
    "/api/v1/auth/session",
    "/api/v1/sessions",
    "/api/v1/nodes",
    "/api/v1/equipment/{equipment_id}/layout/draft",
    "/api/v1/reports",
    "/api/v1/alerts",
}
if local_auth_enabled:
    required.update(
        {
            "/api/v1/auth/local/login",
            "/api/v1/admin/users",
        }
    )
missing = sorted(path for path in required if path not in paths)
print("required routes:")
for path in sorted(required):
    print(f"  {'OK' if path in paths else 'MISSING'} {path}")
if missing:
    raise SystemExit(f"missing API routes: {missing}")
PY

mkdir -p "$REPO/runtime"
printf '%s\n' "$RUNTIME_MODE" > "$AUDIT_DIR/runtime-mode"
install -m 0600 "$AUDIT_DIR/runtime-mode" "$RUNTIME_MODE_FILE"

{
  echo "deployed_at=$(date --iso-8601=seconds)"
  echo "commit=$CURRENT_HEAD"
  echo "requested_source_ref=${REQUESTED_SOURCE_REF:-current_origin_main}"
  echo "expected_deployed_source=${EXPECTED_DEPLOYED_SOURCE:-not_supplied}"
  echo "control_origin_main=$CONTROL_HEAD"
  echo "expected_deployed_evidence=${EXPECTED_DEPLOYMENT_EVIDENCE:-not_applicable}"
  echo "runtime_mode=$RUNTIME_MODE"
  echo "bind_address=$BIND_IP"
  echo "dashboard=$NEXOLAB_DASHBOARD_ORIGIN"
  echo "api=$NEXOLAB_API_BASE_URL"
  echo "minio=$NEXOLAB_OBJECT_STORAGE_PUBLIC_URL"
  echo "auth_mode=$AUTH_MODE_VALUE"
  echo "local_auth_overlay=$LOCAL_AUTH_OVERLAY_ENABLED"
  echo "dashboard_auth_provider=$FRONTEND_AUTH_PROVIDER"
  echo "dashboard_organization_id=$FRONTEND_ORGANIZATION_ID"
  echo "frontend_release_dir=$FRONTEND_RELEASE_DIR"
  echo "frontend_build_id=$(cat "$FRONTEND_RELEASE_DIR/.next/BUILD_ID")"
  echo "grafana_local=http://127.0.0.1:3001"
  echo "prometheus_local=http://127.0.0.1:9090"
  echo "alertmanager_local=http://127.0.0.1:9093"
  echo
  echo '=== central ==='
  docker compose --env-file "$CENTRAL_ENV" "${CENTRAL_COMPOSE_ARGS[@]}" ps -a
  echo
  echo '=== edge ==='
  docker compose --env-file "$EDGE_ENV" "${EDGE_COMPOSE_ARGS[@]}" ps -a
  echo
  echo '=== dashboard ==='
  sudo systemctl --no-pager --full status nexolab-dashboard.service || true
  echo
  echo '=== health ==='
  curl -fsS "$NEXOLAB_API_BASE_URL/health/ready"
  echo
  curl -fsS "http://127.0.0.1:8081/health"
  echo
} > "$AUDIT_DIR/final-state.txt" 2>&1

docker volume inspect \
  nexolab-central-postgres-data \
  nexolab-central-mqtt-data \
  nexolab-central-object-storage-data \
  nexolab-central-telemetry-ingestion-data \
  nexolab-edge_edge-data \
  nexolab-edge_mqtt-data \
  > "$AUDIT_DIR/volume-identities-after.json" 2>"$AUDIT_DIR/volume-identities-after.err" || true

log "DEPLOYMENT PASSED"
log "Runtime mode: $RUNTIME_MODE"
log "Dashboard: $NEXOLAB_DASHBOARD_ORIGIN"
log "API: $NEXOLAB_API_BASE_URL"
log "Grafana on Raspberry Pi: http://127.0.0.1:3001"
log "Evidence: $AUDIT_DIR"
log "Security note: standalone mode is loopback-only; lan mode retains trusted-LAN exposure. MQTT TLS cutover remains a separate controlled gate."
