#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.central.yaml"
CAPACITY_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.capacity.yaml"
POLICY="$ROOT_DIR/infrastructure/performance/release-workload.v1.yaml"
EVIDENCE_DIR="${NEXOLAB_CAPACITY_EVIDENCE_DIR:-$ROOT_DIR/test-results-capacity}"
RUN_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$"

cd "$ROOT_DIR"

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
  fi
}

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-capacity-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${CAPACITY_API_PORT:-18083}"
export CENTRAL_MQTT_PORT="${CAPACITY_MQTT_PORT:-11885}"
export CENTRAL_OBJECT_STORAGE_PORT="${CAPACITY_OBJECT_STORAGE_PORT:-19010}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${CAPACITY_OBJECT_STORAGE_CONSOLE_PORT:-19011}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-capacity}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-capacity-images}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export AUTH_MODE="disabled"
export RETENTION_ENABLED="false"
export INGESTION_QUEUE_MAXSIZE="10000"
export WEBSOCKET_CLIENT_QUEUE_MAXSIZE="256"
export NEXOLAB_TELEMETRY_VERSION="${NEXOLAB_TELEMETRY_VERSION:-capacity-acceptance}"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:capacity-acceptance}"

STACK_STARTED=0
mkdir -p "$EVIDENCE_DIR"
rm -rf "$EVIDENCE_DIR"/*

compose() {
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --file "$BASE_COMPOSE" \
    --file "$CAPACITY_COMPOSE" \
    "$@"
}

sanitize_file() {
  local path=$1
  [[ -f "$path" ]] || return 0
  python3 - "$path" "$POSTGRES_PASSWORD" "$MINIO_ROOT_PASSWORD" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
for secret in sys.argv[2:]:
    if secret:
        text = text.replace(secret, "[REDACTED]")
path.write_text(text, encoding="utf-8")
PY
}

collect_failure_evidence() {
  if [[ "$STACK_STARTED" == "1" ]]; then
    compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
    compose logs --no-color >"$EVIDENCE_DIR/services.log" 2>&1 || true
    sanitize_file "$EVIDENCE_DIR/services.log"
  fi
}

cleanup() {
  local status=$?
  set +e
  if [[ $status -ne 0 ]]; then
    collect_failure_evidence
  fi
  if [[ "$STACK_STARTED" == "1" && "${KEEP_CAPACITY_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ $status -ne 0 ]]; then
    printf 'Capacity acceptance failed. Evidence: %s\n' "$EVIDENCE_DIR" >&2
    tail -n 200 "$EVIDENCE_DIR/services.log" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in curl docker python3; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is missing: %s\n' "$command" >&2
    exit 1
  }
done

python3 "$ROOT_DIR/scripts/validate_capacity_policy.py" "$POLICY"
compose config --quiet
compose up --detach --build
STACK_STARTED=1

for _ in $(seq 1 120); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:$CENTRAL_API_PORT/health/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl --fail --silent --show-error \
  "http://127.0.0.1:$CENTRAL_API_PORT/health/ready" >/dev/null

python3 "$ROOT_DIR/scripts/run_capacity_acceptance.py" \
  --policy "infrastructure/performance/release-workload.v1.yaml" \
  --evidence-dir "$EVIDENCE_DIR" \
  --api-url "http://127.0.0.1:$CENTRAL_API_PORT" \
  --compose-project "$COMPOSE_PROJECT_NAME" \
  --compose-file "$BASE_COMPOSE" \
  --compose-file "$CAPACITY_COMPOSE"

python3 "$ROOT_DIR/scripts/verify_capacity_evidence.py" "$EVIDENCE_DIR"

python3 - "$EVIDENCE_DIR" "$POSTGRES_PASSWORD" "$MINIO_ROOT_PASSWORD" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
secrets = [value for value in sys.argv[2:] if value]
pattern = re.compile(
    "BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY|"
    + "g" + r"hp_[A-Za-z0-9]{20,}|"
    + "s" + r"k-[A-Za-z0-9]{20,}"
)
for path in root.rglob("*"):
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    if pattern.search(text):
        raise SystemExit(f"secret-like material found in capacity evidence: {path}")
    for secret in secrets:
        if secret in text:
            raise SystemExit(f"generated credential found in capacity evidence: {path}")
PY

printf 'Capacity release Gate passed. Evidence: %s\n' "$EVIDENCE_DIR"
