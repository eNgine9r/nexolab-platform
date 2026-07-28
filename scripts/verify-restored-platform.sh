#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: verify-restored-platform.sh <project-name> <compose-file> <evidence-dir>" >&2
  exit 64
fi

PROJECT_NAME=$1
COMPOSE_FILE=$2
EVIDENCE_DIR=$3
API_PORT="${DR_RESTORE_API_PORT:-8094}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
ORGANIZATION_ID="00000000-0000-0000-0000-000000000099"
EDGE_01_USERNAME="node:${ORGANIZATION_ID}:edge-01"
EDGE_01_CLIENT_ID="nexolab-${ORGANIZATION_ID}-edge-01"
POST_RESTORE_EVENT_ID="30000000-0000-0000-0000-000000000001"
STARTED_AT="$(date +%s)"

compose() {
  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

capture_failure() {
  local status=$?
  set +e
  compose ps --all >"$EVIDENCE_DIR/application-compose-ps.txt" 2>&1 || true
  compose logs --no-color restore-telemetry-service restore-postgres restore-mqtt restore-minio \
    >"$EVIDENCE_DIR/application-services.log" 2>&1 || true
  exit "$status"
}
trap capture_failure ERR

compose up -d --wait restore-telemetry-service

python3 - "$API_BASE_URL" "$EVIDENCE_DIR" <<'PY'
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import json
import sys

base_url = sys.argv[1]
evidence = Path(sys.argv[2])
expected = {
    "20000000-0000-0000-0000-000000000001",
    "20000000-0000-0000-0000-000000000002",
}

with urlopen(f"{base_url}/health/ready", timeout=10) as response:
    ready = json.load(response)
evidence.joinpath("restored-ready.json").write_text(
    json.dumps(ready, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

with urlopen(f"{base_url}/api/v1/telemetry/latest?limit=20", timeout=10) as response:
    latest = json.load(response)
evidence.joinpath("restored-latest.json").write_text(
    json.dumps(latest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

history_query = urlencode(
    {
        "from": "2026-07-28T00:00:00+00:00",
        "to": "2026-07-29T00:00:00+00:00",
        "limit": 20,
    }
)
with urlopen(
    f"{base_url}/api/v1/telemetry/history?{history_query}", timeout=10
) as response:
    history = json.load(response)
evidence.joinpath("restored-history.json").write_text(
    json.dumps(history, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

for label, payload in (("latest", latest), ("history", history)):
    found = {item["event_id"] for item in payload["items"]}
    if not expected.issubset(found):
        raise SystemExit(f"Restored telemetry is missing from {label}: {expected - found}")
PY

compose exec -T restore-telemetry-service python - <<'PY'
from __future__ import annotations

import asyncio
import websockets


async def main() -> None:
    uri = "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01"
    async with websockets.connect(uri, open_timeout=5, close_timeout=5):
        return


asyncio.run(main())
PY

compose exec -T restore-telemetry-service python - \
  "$ORGANIZATION_ID" "$EDGE_01_USERNAME" "$EDGE_01_CLIENT_ID" \
  "$POST_RESTORE_EVENT_ID" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json
import sys
import threading

import paho.mqtt.client as mqtt

organization_id, username, client_id, event_id = sys.argv[1:]
password = Path("/run/secrets/nexolab/edge-01-password").read_text(
    encoding="utf-8"
).strip()
connected = threading.Event()
errors: list[str] = []

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
client.username_pw_set(username, password)
del password


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        connected.set()
        return
    errors.append(str(reason_code))
    connected.set()


client.on_connect = on_connect
client.connect("restore-mqtt", 1883, keepalive=30)
client.loop_start()
if not connected.wait(10) or errors:
    raise SystemExit(f"Restored node identity could not connect: {errors}")

payload = {
    "event_id": event_id,
    "node_id": "edge-01",
    "captured_at": datetime.now(UTC).isoformat(),
    "metric": "temperature.air",
    "value": 5.25,
    "unit": "degC",
    "quality": "valid",
    "source": "disaster-recovery-acceptance",
    "equipment_id": "SIM-DR-POST-RESTORE",
    "channel_id": "ambient-temperature",
    "alarm": None,
    "raw_value": 525,
    "raw_status": 0,
    "node_sequence": 2,
}
body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
topic = f"nexolab/v1/{organization_id}/edge-01/telemetry"
for _ in range(2):
    result = client.publish(topic, body, qos=1)
    result.wait_for_publish(timeout=10)
    if result.rc != mqtt.MQTT_ERR_SUCCESS or not result.is_published():
        raise SystemExit("Post-restore QoS 1 publish was not acknowledged")
client.disconnect()
client.loop_stop()
PY

POST_RESTORE_ROW_COUNT=0
for _ in $(seq 1 80); do
  POST_RESTORE_ROW_COUNT="$(compose exec -T restore-postgres \
    psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
    "SELECT COUNT(*) FROM telemetry_samples WHERE event_id = '$POST_RESTORE_EVENT_ID'")"
  if [[ "$POST_RESTORE_ROW_COUNT" = "1" ]]; then
    break
  fi
  sleep 0.25
done
test "$POST_RESTORE_ROW_COUNT" = "1"

TOTAL_TELEMETRY_ROWS="$(compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
  "SELECT COUNT(*) FROM telemetry_samples")"
DEAD_LETTER_ROWS="$(compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
  "SELECT COUNT(*) FROM telemetry_dead_letters")"
test "$TOTAL_TELEMETRY_ROWS" = "3"
test "$DEAD_LETTER_ROWS" = "0"

python3 - "$API_BASE_URL" "$EVIDENCE_DIR" "$POST_RESTORE_EVENT_ID" <<'PY'
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import json
import sys

base_url = sys.argv[1]
evidence = Path(sys.argv[2])
event_id = sys.argv[3]
query = urlencode(
    {
        "node_id": "edge-01",
        "equipment_id": "SIM-DR-POST-RESTORE",
        "limit": 5,
    }
)
with urlopen(f"{base_url}/api/v1/telemetry/latest?{query}", timeout=10) as response:
    payload = json.load(response)
if payload["count"] != 1 or payload["items"][0]["event_id"] != event_id:
    raise SystemExit("Post-restore telemetry is not visible exactly once through REST")
evidence.joinpath("post-restore-latest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

APPLICATION_SECONDS="$(( $(date +%s) - STARTED_AT ))"
python3 - "$EVIDENCE_DIR/application-summary.json" <<PY
from pathlib import Path
import json
import sys

payload = {
    "schema_version": 1,
    "ready": True,
    "restored_rest_rows": 2,
    "websocket_handshake": True,
    "restored_node_identity_connected": True,
    "post_restore_event_id": "$POST_RESTORE_EVENT_ID",
    "post_restore_duplicate_publishes": 2,
    "post_restore_exactly_once_rows": int("$POST_RESTORE_ROW_COUNT"),
    "total_telemetry_rows": int("$TOTAL_TELEMETRY_ROWS"),
    "dead_letter_rows": int("$DEAD_LETTER_ROWS"),
    "application_verification_seconds": $APPLICATION_SECONDS,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

trap - ERR
echo "Restored NEXOLAB application flows passed."
