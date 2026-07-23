#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env.central}"
COMPOSE_FILE="$SCRIPT_DIR/compose.central.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing environment file: $ENV_FILE" >&2
  exit 2
fi

read_env() {
  local key="$1"
  local fallback="$2"
  local value
  value="$(
    awk -F= -v key="$key" '
      $0 !~ /^[[:space:]]*#/ && $1 == key {
        sub(/^[^=]*=/, "")
        print
        exit
      }
    ' "$ENV_FILE"
  )"
  printf '%s' "${value:-$fallback}"
}

BIND_ADDRESS="$(read_env CENTRAL_BIND_ADDRESS 127.0.0.1)"
API_PORT="$(read_env CENTRAL_API_PORT 8082)"
CORS_ORIGINS="$(read_env CORS_ALLOWED_ORIGINS '')"

case "$BIND_ADDRESS" in
  0.0.0.0|::)
    REQUEST_HOST=127.0.0.1
    ;;
  *)
    REQUEST_HOST="$BIND_ADDRESS"
    ;;
esac

BASE_URL="http://$REQUEST_HOST:$API_PORT"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${COMPOSE[@]}" config --quiet

ready=0
for _ in $(seq 1 30); do
  if curl -fsS "$BASE_URL/health/ready" >/tmp/nexolab-central-ready.json; then
    ready=1
    break
  fi
  sleep 2
done

if [[ "$ready" -ne 1 ]]; then
  echo "Telemetry service did not become ready" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail=200 telemetry-migrate telemetry-service >&2 || true
  exit 1
fi

python3 -m json.tool </tmp/nexolab-central-ready.json >/dev/null
curl -fsS "$BASE_URL/metrics" | grep -q '^nexolab_telemetry_database_ready 1'

python3 - "$BASE_URL" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1]

with urlopen(f"{base_url}/api/v1/telemetry/latest?limit=1", timeout=5) as response:
    latest = json.load(response)
assert latest["count"] >= 0
assert isinstance(latest["items"], list)

now = datetime.now(UTC)
query = urlencode(
    {
        "from": (now - timedelta(minutes=5)).isoformat(),
        "to": now.isoformat(),
        "limit": 1,
    }
)
with urlopen(
    f"{base_url}/api/v1/telemetry/history?{query}", timeout=5
) as response:
    history = json.load(response)
assert history["count"] >= 0
assert isinstance(history["items"], list)
PY

"${COMPOSE[@]}" exec -T telemetry-service python - <<'PY'
from __future__ import annotations

import asyncio

import websockets


async def main() -> None:
    uri = "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=smoke-test"
    async with websockets.connect(uri, open_timeout=5, close_timeout=5):
        return


asyncio.run(main())
PY

if [[ -n "$CORS_ORIGINS" ]]; then
  FIRST_ORIGIN="${CORS_ORIGINS%%,*}"
  curl -fsS -D /tmp/nexolab-central-cors.headers -o /dev/null \
    -H "Origin: $FIRST_ORIGIN" \
    "$BASE_URL/health/live"
  grep -qi "^access-control-allow-origin: $FIRST_ORIGIN" \
    /tmp/nexolab-central-cors.headers
fi

printf 'Central smoke test passed: %s\n' "$BASE_URL"
