#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
CENTRAL_ENV="${1:-$SCRIPT_DIR/.env.central}"
EDGE_ENV="${2:-}"
CENTRAL_COMPOSE_FILE="$SCRIPT_DIR/compose.central.yaml"
EDGE_BASE_FILE="$SCRIPT_DIR/compose.edge.yaml"
EDGE_HARDWARE_FILE="$SCRIPT_DIR/compose.hardware.yaml"

if [[ ! -f "$CENTRAL_ENV" ]]; then
  echo "Missing central environment file: $CENTRAL_ENV" >&2
  exit 2
fi

read_env() {
  local file="$1"
  local key="$2"
  local fallback="$3"
  local value
  value="$(
    awk -F= -v key="$key" '
      $0 !~ /^[[:space:]]*#/ && $1 == key {
        sub(/^[^=]*=/, "")
        print
        exit
      }
    ' "$file"
  )"
  printf '%s' "${value:-$fallback}"
}

BIND_ADDRESS="$(read_env "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS 127.0.0.1)"
API_PORT="$(read_env "$CENTRAL_ENV" CENTRAL_API_PORT 8082)"
case "$BIND_ADDRESS" in
  0.0.0.0|::)
    REQUEST_HOST=127.0.0.1
    ;;
  *)
    REQUEST_HOST="$BIND_ADDRESS"
    ;;
esac
API_BASE_URL="http://$REQUEST_HOST:$API_PORT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO_ROOT/runtime/evidence/m3-status-$STAMP"
mkdir -p "$EVIDENCE_DIR"

CENTRAL_COMPOSE=(
  docker compose
  --env-file "$CENTRAL_ENV"
  -f "$CENTRAL_COMPOSE_FILE"
)

"${CENTRAL_COMPOSE[@]}" config --quiet
"${CENTRAL_COMPOSE[@]}" ps -a >"$EVIDENCE_DIR/central-compose-ps.txt"
"${CENTRAL_COMPOSE[@]}" logs --since=15m --tail=400 --no-color \
  mqtt postgres telemetry-migrate telemetry-service \
  >"$EVIDENCE_DIR/central-recent.log" 2>&1 || true

docker volume inspect nexolab-central-postgres-data \
  >"$EVIDENCE_DIR/postgres-volume.json" 2>"$EVIDENCE_DIR/postgres-volume.err" || true
docker volume inspect nexolab-central-mqtt-data \
  >"$EVIDENCE_DIR/mqtt-volume.json" 2>"$EVIDENCE_DIR/mqtt-volume.err" || true

curl_status() {
  local url="$1"
  local output="$2"
  local status_file="$3"
  local status
  status="$(curl -sS -o "$output" -w '%{http_code}' --max-time 10 "$url" || true)"
  printf '%s\n' "${status:-000}" >"$status_file"
}

curl_status \
  "$API_BASE_URL/health/ready" \
  "$EVIDENCE_DIR/central-ready.json" \
  "$EVIDENCE_DIR/central-ready.status"
curl_status \
  "$API_BASE_URL/metrics/json" \
  "$EVIDENCE_DIR/central-metrics.json" \
  "$EVIDENCE_DIR/central-metrics.status"
curl_status \
  "$API_BASE_URL/api/v1/telemetry/latest?node_id=edge-01&limit=1000" \
  "$EVIDENCE_DIR/edge-01-latest.json" \
  "$EVIDENCE_DIR/edge-01-latest.status"

if [[ -n "$EDGE_ENV" ]]; then
  if [[ ! -f "$EDGE_ENV" ]]; then
    echo "Missing edge environment file: $EDGE_ENV" >&2
    exit 2
  fi

  EDGE_COMPOSE=(
    docker compose
    --env-file "$EDGE_ENV"
    -f "$EDGE_BASE_FILE"
    -f "$EDGE_HARDWARE_FILE"
  )
  "${EDGE_COMPOSE[@]}" config --quiet
  "${EDGE_COMPOSE[@]}" ps -a >"$EVIDENCE_DIR/edge-compose-ps.txt"
  "${EDGE_COMPOSE[@]}" logs --since=15m --tail=400 --no-color \
    mqtt device-agent >"$EVIDENCE_DIR/edge-recent.log" 2>&1 || true
  curl_status \
    "http://127.0.0.1:8081/health" \
    "$EVIDENCE_DIR/edge-health.json" \
    "$EVIDENCE_DIR/edge-health.status"
fi

python3 - "$EVIDENCE_DIR" "$API_BASE_URL" "$EDGE_ENV" <<'PY'
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

root = Path(sys.argv[1])
api_base_url = sys.argv[2]
edge_requested = bool(sys.argv[3])


def read_status(name: str) -> int:
    path = root / name
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def read_json(name: str) -> Any:
    path = root / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


ready_status = read_status("central-ready.status")
metrics_status = read_status("central-metrics.status")
latest_status = read_status("edge-01-latest.status")
ready = read_json("central-ready.json")
metrics = read_json("central-metrics.json")
latest = read_json("edge-01-latest.json")

latest_items = []
if isinstance(latest, dict) and isinstance(latest.get("items"), list):
    latest_items = [item for item in latest["items"] if isinstance(item, dict)]

series = {
    (
        str(item.get("equipment_id", "")),
        str(item.get("channel_id", "")),
        str(item.get("metric", "")),
    )
    for item in latest_items
}
quality_counts = Counter(str(item.get("quality", "missing")) for item in latest_items)
alarm_counts = Counter(str(item.get("alarm") or "none") for item in latest_items)

postgres_volume = read_json("postgres-volume.json")
mqtt_volume = read_json("mqtt-volume.json")

edge_health_status = read_status("edge-health.status") if edge_requested else None
edge_health = read_json("edge-health.json") if edge_requested else None
edge_mode = None
if isinstance(edge_health, dict):
    edge_mode = edge_health.get("device_mode", edge_health.get("mode"))

checks = {
    "central_ready_http_200": ready_status == 200,
    "central_ready": isinstance(ready, dict) and ready.get("status") == "ready",
    "database_ready": isinstance(ready, dict) and ready.get("database") == "ready",
    "mqtt_ready": isinstance(ready, dict) and ready.get("mqtt") == "ready",
    "metrics_http_200": metrics_status == 200,
    "latest_http_200": latest_status == 200,
    "postgres_volume_present": isinstance(postgres_volume, list) and bool(postgres_volume),
    "mqtt_volume_present": isinstance(mqtt_volume, list) and bool(mqtt_volume),
}
if edge_requested:
    checks.update(
        {
            "edge_health_http_200": edge_health_status == 200,
            "edge_modbus_mode": edge_mode == "modbus",
        }
    )

manifest = {
    "validation": "m3-read-only-status",
    "status": "passed" if all(checks.values()) else "attention_required",
    "captured_at": datetime.now(UTC).isoformat(),
    "api_base_url": api_base_url,
    "checks": checks,
    "central_readiness": ready,
    "central_metrics_summary": {
        "queue_size": metrics.get("queue_size") if isinstance(metrics, dict) else None,
        "websocket_clients": metrics.get("websocket_clients") if isinstance(metrics, dict) else None,
        "last_persisted_at": metrics.get("last_persisted_at") if isinstance(metrics, dict) else None,
        "ingestion_lag_seconds": metrics.get("ingestion_lag_seconds") if isinstance(metrics, dict) else None,
        "mqtt_error": metrics.get("mqtt_error") if isinstance(metrics, dict) else None,
        "database_error": metrics.get("database_error") if isinstance(metrics, dict) else None,
    },
    "edge_01_latest_summary": {
        "response_count": latest.get("count") if isinstance(latest, dict) else None,
        "unique_series": len(series),
        "quality_counts": dict(sorted(quality_counts.items())),
        "alarm_counts": dict(sorted(alarm_counts.items())),
    },
    "edge_health": edge_health if edge_requested else "not_requested",
    "artifacts": sorted(path.name for path in root.iterdir()),
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, indent=2))
raise SystemExit(0 if manifest["status"] == "passed" else 1)
PY

printf 'M3 read-only status bundle: %s\n' "$EVIDENCE_DIR"
