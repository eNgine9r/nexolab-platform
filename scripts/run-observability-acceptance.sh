#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.central.yaml"
OBSERVABILITY_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.observability.yaml"
RUN_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$"

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

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-observability-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${OBSERVABILITY_API_PORT:-18082}"
export CENTRAL_MQTT_PORT="${OBSERVABILITY_MQTT_PORT:-11884}"
export CENTRAL_OBJECT_STORAGE_PORT="${OBSERVABILITY_OBJECT_STORAGE_PORT:-19000}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${OBSERVABILITY_OBJECT_STORAGE_CONSOLE_PORT:-19001}"
export OBSERVABILITY_BIND_ADDRESS="127.0.0.1"
export PROMETHEUS_PORT="${OBSERVABILITY_PROMETHEUS_PORT:-19090}"
export ALERTMANAGER_PORT="${OBSERVABILITY_ALERTMANAGER_PORT:-19093}"
export GRAFANA_PORT="${OBSERVABILITY_GRAFANA_PORT:-13030}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-observability}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-nexolab-admin}"
export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-observability-images}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export AUTH_MODE="disabled"
export RETENTION_ENABLED="false"
export NEXOLAB_TELEMETRY_VERSION="${NEXOLAB_TELEMETRY_VERSION:-observability-acceptance}"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:observability-acceptance}"

PRIVATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${COMPOSE_PROJECT_NAME}.XXXXXX")"
export OBSERVABILITY_TEXTFILE_DIR="$PRIVATE_DIR/textfile"
EVIDENCE_DIR="${NEXOLAB_OBSERVABILITY_EVIDENCE_DIR:-$ROOT_DIR/test-results-observability}"
mkdir -p "$OBSERVABILITY_TEXTFILE_DIR" "$EVIDENCE_DIR"
chmod 0700 "$PRIVATE_DIR"
rm -rf "$EVIDENCE_DIR"/*

PROMETHEUS_URL="http://127.0.0.1:$PROMETHEUS_PORT"
ALERTMANAGER_URL="http://127.0.0.1:$ALERTMANAGER_PORT"
GRAFANA_URL="http://127.0.0.1:$GRAFANA_PORT"
API_URL="http://127.0.0.1:$CENTRAL_API_PORT"
STACK_STARTED=0
STARTED_AT="$(date +%s)"

compose() {
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --file "$BASE_COMPOSE" \
    --file "$OBSERVABILITY_COMPOSE" \
    "$@"
}

sanitize_file() {
  local path=$1
  [[ -f "$path" ]] || return 0
  python3 - "$path" "$POSTGRES_PASSWORD" "$MINIO_ROOT_PASSWORD" "$GRAFANA_ADMIN_PASSWORD" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
for value in sys.argv[2:]:
    if value:
        text = text.replace(value, "[REDACTED]")
path.write_text(text, encoding="utf-8")
PY
}

collect_evidence() {
  if [[ "$STACK_STARTED" == "1" ]]; then
    compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
    compose logs --no-color \
      telemetry-service prometheus alertmanager grafana \
      observability-alert-sink observability-textfile \
      >"$EVIDENCE_DIR/services.log" 2>&1 || true
    sanitize_file "$EVIDENCE_DIR/services.log"
  fi
}

cleanup() {
  local status=$?
  set +e
  collect_evidence
  if [[ "$STACK_STARTED" == "1" && "${KEEP_OBSERVABILITY_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    printf 'Observability acceptance failed. Evidence: %s\n' "$EVIDENCE_DIR" >&2
    tail -n 240 "$EVIDENCE_DIR/services.log" >&2 || true
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

NOW="$(date +%s)"
cat >"$OBSERVABILITY_TEXTFILE_DIR/disaster-recovery.prom" <<EOF
# HELP nexolab_dr_last_verified_backup_timestamp_seconds Unix timestamp of the newest verified encrypted backup.
# TYPE nexolab_dr_last_verified_backup_timestamp_seconds gauge
nexolab_dr_last_verified_backup_timestamp_seconds $((NOW - 3600))
# HELP nexolab_dr_last_offsite_copy_timestamp_seconds Unix timestamp of the newest verified off-host copy.
# TYPE nexolab_dr_last_offsite_copy_timestamp_seconds gauge
nexolab_dr_last_offsite_copy_timestamp_seconds $((NOW - 7200))
# HELP nexolab_dr_last_restore_rehearsal_timestamp_seconds Unix timestamp of the newest fresh-volume restore rehearsal.
# TYPE nexolab_dr_last_restore_rehearsal_timestamp_seconds gauge
nexolab_dr_last_restore_rehearsal_timestamp_seconds $((NOW - 86400))
# HELP nexolab_dr_last_bundle_verification_success Whether the newest encrypted bundle passed authentication and manifest verification.
# TYPE nexolab_dr_last_bundle_verification_success gauge
nexolab_dr_last_bundle_verification_success 1
# HELP nexolab_dr_backup_duration_seconds Duration of the newest backup operation.
# TYPE nexolab_dr_backup_duration_seconds gauge
nexolab_dr_backup_duration_seconds 42
# HELP nexolab_dr_restore_duration_seconds Duration of the newest restore rehearsal.
# TYPE nexolab_dr_restore_duration_seconds gauge
nexolab_dr_restore_duration_seconds 95
# HELP nexolab_dr_backup_destination_free_bytes Free bytes in the backup destination.
# TYPE nexolab_dr_backup_destination_free_bytes gauge
nexolab_dr_backup_destination_free_bytes 80530636800
# HELP nexolab_dr_backup_destination_capacity_bytes Capacity bytes in the backup destination.
# TYPE nexolab_dr_backup_destination_capacity_bytes gauge
nexolab_dr_backup_destination_capacity_bytes 107374182400
EOF
chmod 0600 "$OBSERVABILITY_TEXTFILE_DIR/disaster-recovery.prom"

compose config --quiet
compose up --detach --build
STACK_STARTED=1

wait_http() {
  local url=$1
  local attempts=${2:-120}
  for _ in $(seq 1 "$attempts"); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  printf 'Timed out waiting for %s\n' "$url" >&2
  return 1
}

wait_query_sample() {
  local expression=$1
  local output=$2
  local attempts=${3:-90}
  for _ in $(seq 1 "$attempts"); do
    curl --fail --silent --show-error --get \
      --data-urlencode "query=$expression" \
      "$PROMETHEUS_URL/api/v1/query" >"$output.tmp" || true
    if python3 - "$output.tmp" <<'PY' 2>/dev/null
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)
payload = json.loads(path.read_text(encoding="utf-8"))
result = payload.get("data", {}).get("result", [])
raise SystemExit(0 if result else 1)
PY
    then
      mv "$output.tmp" "$output"
      return 0
    fi
    sleep 2
  done
  printf 'Timed out waiting for Prometheus query: %s\n' "$expression" >&2
  return 1
}

wait_http "$API_URL/health/ready"
wait_http "$PROMETHEUS_URL/-/ready"
wait_http "$ALERTMANAGER_URL/-/ready"
wait_http "$GRAFANA_URL/api/health"

CAPTURED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EVENT_ID="$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"
PAYLOAD="$(python3 - "$EVENT_ID" "$CAPTURED_AT" <<'PY'
import json
import sys

print(json.dumps({
    "event_id": sys.argv[1],
    "node_id": "observability-edge-01",
    "captured_at": sys.argv[2],
    "metric": "temperature.probe",
    "value": 4.2,
    "unit": "degC",
    "quality": "valid",
    "source": "observability-acceptance",
    "equipment_id": "monitoring-case-01",
    "channel_id": "monitoring-01",
    "alarm": None,
    "raw_value": 42,
    "raw_status": None,
}, separators=(",", ":")))
PY
)"
compose exec -T mqtt mosquitto_pub -h mqtt -t nexolab/telemetry -m "$PAYLOAD"

for _ in $(seq 1 60); do
  if curl --fail --silent --show-error "$API_URL/metrics" \
    | grep -q 'nexolab_telemetry_persisted_total 1'; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error "$API_URL/metrics" >"$EVIDENCE_DIR/telemetry-metrics.prom"
grep -q 'nexolab_telemetry_persisted_total 1' "$EVIDENCE_DIR/telemetry-metrics.prom"
grep -q 'nexolab_telemetry_queue_capacity ' "$EVIDENCE_DIR/telemetry-metrics.prom"
grep -q 'nexolab_telemetry_build_info{' "$EVIDENCE_DIR/telemetry-metrics.prom"

sleep 12
curl --fail --silent --show-error "$PROMETHEUS_URL/api/v1/targets" \
  >"$EVIDENCE_DIR/prometheus-targets.json"
python3 - "$EVIDENCE_DIR/prometheus-targets.json" <<'PY'
from pathlib import Path
import json
import sys

required = {
    "prometheus",
    "telemetry-service",
    "alertmanager",
    "observability-alert-sink",
    "disaster-recovery-status",
}
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
targets = payload.get("data", {}).get("activeTargets", [])
health = {}
for target in targets:
    job = target.get("labels", {}).get("job")
    if job:
        health[job] = target.get("health")
missing = required - health.keys()
unhealthy = {job: health.get(job) for job in required if health.get(job) != "up"}
if missing or unhealthy:
    raise SystemExit(f"targets missing={sorted(missing)} unhealthy={unhealthy}")
PY

curl --fail --silent --show-error "$PROMETHEUS_URL/api/v1/rules" \
  >"$EVIDENCE_DIR/prometheus-rules.json"
python3 - "$EVIDENCE_DIR/prometheus-rules.json" <<'PY'
from pathlib import Path
import json
import sys

required = {
    "nexolab:platform_dependency_ready",
    "nexolab:ingestion_queue_utilization_ratio",
    "nexolab:verified_backup_age_seconds",
    "NexolabTelemetryServiceDown",
}
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
names = {
    rule.get("name")
    for group in payload.get("data", {}).get("groups", [])
    for rule in group.get("rules", [])
}
missing = required - names
if missing:
    raise SystemExit(f"Prometheus rules missing: {sorted(missing)}")
PY

wait_query_sample "nexolab:platform_dependency_ready" \
  "$EVIDENCE_DIR/query-platform-dependencies.json"
wait_query_sample "nexolab:ingestion_queue_utilization_ratio" \
  "$EVIDENCE_DIR/query-queue-utilization.json"
wait_query_sample "nexolab:verified_backup_age_seconds" \
  "$EVIDENCE_DIR/query-backup-age.json"

curl --fail --silent --show-error \
  --user "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
  "$GRAFANA_URL/api/dashboards/uid/nexolab-platform-overview" \
  >"$EVIDENCE_DIR/grafana-dashboard.json"
python3 - "$EVIDENCE_DIR/grafana-dashboard.json" <<'PY'
from pathlib import Path
import json
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dashboard = payload.get("dashboard", {})
if dashboard.get("uid") != "nexolab-platform-overview":
    raise SystemExit("Grafana dashboard UID mismatch")
panels = dashboard.get("panels", [])
ids = {panel.get("id") for panel in panels}
required_ids = set(range(1, 23))
if not required_ids <= ids:
    raise SystemExit(f"Grafana panels missing: {sorted(required_ids - ids)}")
PY
sanitize_file "$EVIDENCE_DIR/grafana-dashboard.json"

compose stop -t 15 telemetry-service
wait_query_sample \
  'ALERTS{alertname="NexolabTelemetryServiceDown",alertstate="firing"}' \
  "$EVIDENCE_DIR/query-service-down-firing.json" 100

for _ in $(seq 1 90); do
  curl --fail --silent --show-error \
    "http://127.0.0.1:$PROMETHEUS_PORT/-/healthy" >/dev/null
  compose exec -T observability-alert-sink python - <<'PY' \
    >"$EVIDENCE_DIR/alert-events.json.tmp" 2>/dev/null || true
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8080/events", timeout=3) as response:
    print(json.dumps(json.load(response), indent=2, sort_keys=True))
PY
  if python3 - "$EVIDENCE_DIR/alert-events.json.tmp" firing <<'PY' 2>/dev/null
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
status = sys.argv[2]
if not path.is_file():
    raise SystemExit(1)
events = json.loads(path.read_text(encoding="utf-8"))
found = any(
    alert.get("status") == status
    and alert.get("labels", {}).get("alertname") == "NexolabTelemetryServiceDown"
    for event in events
    for alert in event.get("alerts", [])
)
raise SystemExit(0 if found else 1)
PY
  then
    mv "$EVIDENCE_DIR/alert-events.json.tmp" "$EVIDENCE_DIR/alert-events-firing.json"
    break
  fi
  sleep 2
done
test -s "$EVIDENCE_DIR/alert-events-firing.json"

compose start telemetry-service
wait_http "$API_URL/health/ready"

for _ in $(seq 1 100); do
  compose exec -T observability-alert-sink python - <<'PY' \
    >"$EVIDENCE_DIR/alert-events.json.tmp" 2>/dev/null || true
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8080/events", timeout=3) as response:
    print(json.dumps(json.load(response), indent=2, sort_keys=True))
PY
  if python3 - "$EVIDENCE_DIR/alert-events.json.tmp" resolved <<'PY' 2>/dev/null
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
status = sys.argv[2]
if not path.is_file():
    raise SystemExit(1)
events = json.loads(path.read_text(encoding="utf-8"))
found = any(
    alert.get("status") == status
    and alert.get("labels", {}).get("alertname") == "NexolabTelemetryServiceDown"
    for event in events
    for alert in event.get("alerts", [])
)
raise SystemExit(0 if found else 1)
PY
  then
    mv "$EVIDENCE_DIR/alert-events.json.tmp" "$EVIDENCE_DIR/alert-events-resolved.json"
    break
  fi
  sleep 2
done
test -s "$EVIDENCE_DIR/alert-events-resolved.json"

DURATION_SECONDS="$(( $(date +%s) - STARTED_AT ))"
python3 - "$EVIDENCE_DIR/summary.json" <<PY
from pathlib import Path
import json
import sys

payload = {
    "schema_version": 1,
    "repository": "eNgine9r/nexolab-platform",
    "commit": "${GITHUB_SHA:-local}",
    "duration_seconds": $DURATION_SECONDS,
    "targets_healthy": True,
    "recording_rules_sampled": True,
    "grafana_dashboard_uid": "nexolab-platform-overview",
    "grafana_panel_ids": list(range(1, 23)),
    "controlled_failure": "telemetry-service stopped",
    "firing_alert_delivered": True,
    "resolved_alert_delivered": True,
    "temporary_credentials_uploaded": False,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

collect_evidence
python3 - "$EVIDENCE_DIR" "$POSTGRES_PASSWORD" "$MINIO_ROOT_PASSWORD" "$GRAFANA_ADMIN_PASSWORD" <<'PY'
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
        raise SystemExit(f"secret-like material found in evidence: {path}")
    for secret in secrets:
        if secret in text:
            raise SystemExit(f"generated credential found in evidence: {path}")
PY

printf 'Observability acceptance passed. Evidence: %s\n' "$EVIDENCE_DIR"
