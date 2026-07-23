#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env.edge-central}"
BASE_FILE="$SCRIPT_DIR/compose.edge.yaml"
HARDWARE_FILE="$SCRIPT_DIR/compose.hardware.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing cutover environment file: $ENV_FILE" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ "${HARDWARE_DEVICE_MODE:-}" != "modbus" ]]; then
  echo "Rollback refuses to change a non-modbus hardware contract." >&2
  exit 2
fi

COMPOSE=(
  docker compose
  --env-file "$ENV_FILE"
  -f "$BASE_FILE"
  -f "$HARDWARE_FILE"
)

"${COMPOSE[@]}" config --quiet

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO_ROOT/runtime/evidence/m3-rollback-$STAMP"
mkdir -p "$EVIDENCE_DIR"

EDGE_HEALTH_URL="http://127.0.0.1:8081/health"
curl -fsS "$EDGE_HEALTH_URL" >"$EVIDENCE_DIR/edge-health-before.json"
AGENT_ID_BEFORE="$("${COMPOSE[@]}" ps -q device-agent)"
if [[ -z "$AGENT_ID_BEFORE" ]]; then
  echo "device-agent is not running" >&2
  exit 1
fi

# Recreate only Mosquitto from the base edge profile. Omitting the bridge
# override removes the central route while the Device Agent keeps polling.
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
  echo "Base edge broker did not recover during rollback" >&2
  "${COMPOSE[@]}" logs --tail=200 mqtt >&2 || true
  exit 1
fi

for _ in $(seq 1 30); do
  if curl -fsS "$EDGE_HEALTH_URL" >"$EVIDENCE_DIR/edge-health-after.json"; then
    break
  fi
  sleep 2
done

test -s "$EVIDENCE_DIR/edge-health-after.json"
AGENT_ID_AFTER="$("${COMPOSE[@]}" ps -q device-agent)"
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
    raise SystemExit(f"Modbus mode changed during rollback: {mode!r}")
PY

printf '%s\n' "$AGENT_ID_BEFORE" >"$EVIDENCE_DIR/device-agent-container-before.txt"
printf '%s\n' "$AGENT_ID_AFTER" >"$EVIDENCE_DIR/device-agent-container-after.txt"
"${COMPOSE[@]}" ps >"$EVIDENCE_DIR/edge-compose-ps.txt"
"${COMPOSE[@]}" logs --since=10m --no-color mqtt device-agent \
  >"$EVIDENCE_DIR/edge-rollback.log"

python3 - "$EVIDENCE_DIR" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
manifest = {
    "validation": "m3-edge-rollback",
    "status": "passed",
    "completed_at": datetime.now(UTC).isoformat(),
    "bridge_override_active": False,
    "device_agent_container_preserved": (
        (root / "device-agent-container-before.txt").read_text().strip()
        == (root / "device-agent-container-after.txt").read_text().strip()
    ),
    "modbus_mode_preserved": True,
    "volumes_deleted": False,
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, indent=2))
PY

printf 'M3 edge rollback passed. Evidence: %s\n' "$EVIDENCE_DIR"
