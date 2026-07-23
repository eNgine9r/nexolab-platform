#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env.edge-central}"
BASE_FILE="$SCRIPT_DIR/compose.edge.yaml"
HARDWARE_FILE="$SCRIPT_DIR/compose.hardware.yaml"
BRIDGE_FILE="$SCRIPT_DIR/compose.edge-central-bridge.yaml"
VALIDATOR="$SCRIPT_DIR/m3-validate-cutover.py"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing cutover environment file: $ENV_FILE" >&2
  echo "Copy .env.edge-central.example and preserve the proven edge hardware values." >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${CENTRAL_MQTT_HOST:?CENTRAL_MQTT_HOST is required}"
: "${CENTRAL_API_BASE_URL:?CENTRAL_API_BASE_URL is required}"
: "${CENTRAL_WEBSOCKET_URL:?CENTRAL_WEBSOCKET_URL is required}"

if [[ "${HARDWARE_DEVICE_MODE:-}" != "modbus" ]]; then
  echo "HARDWARE_DEVICE_MODE must remain modbus for the production cutover." >&2
  exit 2
fi

if [[ "${RS485_HOST_DEVICE:-}" != /dev/serial/by-id/* ]]; then
  echo "RS485_HOST_DEVICE must use the stable /dev/serial/by-id path." >&2
  exit 2
fi

COMPOSE=(
  docker compose
  --env-file "$ENV_FILE"
  -f "$BASE_FILE"
  -f "$HARDWARE_FILE"
  -f "$BRIDGE_FILE"
)

"${COMPOSE[@]}" config --quiet

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO_ROOT/runtime/evidence/m3-cutover-$STAMP"
mkdir -p "$EVIDENCE_DIR"

EDGE_HEALTH_URL="http://127.0.0.1:8081/health"
curl -fsS "$EDGE_HEALTH_URL" >"$EVIDENCE_DIR/edge-health-before.json"
curl -fsS "${CENTRAL_API_BASE_URL%/}/health/ready" \
  >"$EVIDENCE_DIR/central-ready-before.json"

python3 - "$EVIDENCE_DIR/edge-health-before.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
mode = payload.get("device_mode", payload.get("mode"))
if mode != "modbus":
    raise SystemExit(f"edge-01 must already be in modbus mode, got {mode!r}")
if payload.get("last_error") not in (None, ""):
    raise SystemExit(f"edge-01 reports last_error={payload['last_error']!r}")
PY

AGENT_ID_BEFORE="$("${COMPOSE[@]}" ps -q device-agent)"
if [[ -z "$AGENT_ID_BEFORE" ]]; then
  echo "device-agent is not running" >&2
  exit 1
fi
printf '%s\n' "$AGENT_ID_BEFORE" >"$EVIDENCE_DIR/device-agent-container-before.txt"

# Recreate only the local broker. The Device Agent keeps polling Modbus and
# queues MQTT work locally while the broker restarts.
"${COMPOSE[@]}" up -d --no-deps --force-recreate mqtt

BROKER_READY=0
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T mqtt \
    mosquitto_sub -h 127.0.0.1 -t '$SYS/broker/version' -C 1 -W 2 \
    >/dev/null 2>&1; then
    BROKER_READY=1
    break
  fi
  sleep 2
done

if [[ "$BROKER_READY" -ne 1 ]]; then
  echo "Local edge broker did not recover after bridge activation" >&2
  "${COMPOSE[@]}" logs --tail=200 mqtt >&2 || true
  exit 1
fi

EDGE_READY=0
for _ in $(seq 1 30); do
  if curl -fsS "$EDGE_HEALTH_URL" >"$EVIDENCE_DIR/edge-health-after.json"; then
    EDGE_READY=1
    break
  fi
  sleep 2
done

if [[ "$EDGE_READY" -ne 1 ]]; then
  echo "Device Agent health endpoint did not recover" >&2
  exit 1
fi

AGENT_ID_AFTER="$("${COMPOSE[@]}" ps -q device-agent)"
printf '%s\n' "$AGENT_ID_AFTER" >"$EVIDENCE_DIR/device-agent-container-after.txt"
if [[ "$AGENT_ID_BEFORE" != "$AGENT_ID_AFTER" ]]; then
  echo "Safety gate failed: device-agent container was recreated" >&2
  exit 1
fi

python3 - "$EVIDENCE_DIR/edge-health-after.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
mode = payload.get("device_mode", payload.get("mode"))
if mode != "modbus":
    raise SystemExit(f"Modbus mode changed during MQTT cutover: {mode!r}")
PY

python3 "$VALIDATOR" \
  --api-base-url "$CENTRAL_API_BASE_URL" \
  --websocket-url "$CENTRAL_WEBSOCKET_URL" \
  --node-id "${NEXOLAB_NODE_ID:-edge-01}" \
  --expected-records 34 \
  --max-age-seconds "${CUTOVER_MAX_SAMPLE_AGE_SECONDS:-90}" \
  --websocket-timeout-seconds "${CUTOVER_WEBSOCKET_TIMEOUT_SECONDS:-45}" \
  --evidence "$EVIDENCE_DIR/telemetry-validation.json"

"${COMPOSE[@]}" ps >"$EVIDENCE_DIR/edge-compose-ps.txt"
"${COMPOSE[@]}" logs --since=10m --no-color mqtt device-agent \
  >"$EVIDENCE_DIR/edge-cutover.log"

python3 - "$EVIDENCE_DIR" "$STAMP" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
manifest = {
    "validation": "m3-edge-central-cutover",
    "status": "passed",
    "stamp": sys.argv[2],
    "completed_at": datetime.now(UTC).isoformat(),
    "device_agent_container_preserved": (
        (root / "device-agent-container-before.txt").read_text().strip()
        == (root / "device-agent-container-after.txt").read_text().strip()
    ),
    "artifacts": sorted(path.name for path in root.iterdir()),
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, indent=2))
PY

printf 'M3 cutover passed. Evidence: %s\n' "$EVIDENCE_DIR"
