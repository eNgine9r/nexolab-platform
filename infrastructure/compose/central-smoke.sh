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

require_positive_integer() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$name must be a positive integer, got: $value" >&2
    exit 2
  fi
}

BIND_ADDRESS="$(read_env CENTRAL_BIND_ADDRESS 127.0.0.1)"
API_PORT="$(read_env CENTRAL_API_PORT 8082)"
CORS_ORIGINS="$(read_env CORS_ALLOWED_ORIGINS '')"
SMOKE_HTTP_ATTEMPTS="$(read_env CENTRAL_SMOKE_HTTP_ATTEMPTS 5)"
SMOKE_HTTP_TIMEOUT_SECONDS="$(read_env CENTRAL_SMOKE_HTTP_TIMEOUT_SECONDS 15)"
SMOKE_HTTP_RETRY_DELAY_SECONDS="$(read_env CENTRAL_SMOKE_HTTP_RETRY_DELAY_SECONDS 2)"

require_positive_integer CENTRAL_SMOKE_HTTP_ATTEMPTS "$SMOKE_HTTP_ATTEMPTS"
require_positive_integer CENTRAL_SMOKE_HTTP_TIMEOUT_SECONDS "$SMOKE_HTTP_TIMEOUT_SECONDS"
require_positive_integer CENTRAL_SMOKE_HTTP_RETRY_DELAY_SECONDS "$SMOKE_HTTP_RETRY_DELAY_SECONDS"

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
CURL_RETRY=(
  --connect-timeout 5
  --max-time "$SMOKE_HTTP_TIMEOUT_SECONDS"
  --retry "$((SMOKE_HTTP_ATTEMPTS - 1))"
  --retry-delay "$SMOKE_HTTP_RETRY_DELAY_SECONDS"
  --retry-all-errors
)

"${COMPOSE[@]}" config --quiet

ready=0
for _ in $(seq 1 30); do
  if curl -fsS --connect-timeout 3 --max-time 10 \
    "$BASE_URL/health/ready" >/tmp/nexolab-central-ready.json; then
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
curl -fsS "${CURL_RETRY[@]}" "$BASE_URL/metrics" \
  | grep -q '^nexolab_telemetry_database_ready 1'

python3 - \
  "$BASE_URL" \
  "$SMOKE_HTTP_ATTEMPTS" \
  "$SMOKE_HTTP_TIMEOUT_SECONDS" \
  "$SMOKE_HTTP_RETRY_DELAY_SECONDS" <<'PY'
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

base_url = sys.argv[1]
attempts = int(sys.argv[2])
timeout_seconds = int(sys.argv[3])
retry_delay_seconds = int(sys.argv[4])


def load_json(path: str) -> dict[str, object]:
    url = f"{base_url}{path}"
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise TypeError(f"GET {url} returned a non-object JSON payload")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, TypeError) as error:
            last_error = error
            if attempt == attempts:
                break
            print(
                f"Central smoke REST retry {attempt}/{attempts} for {url}: {error}",
                file=sys.stderr,
            )
            time.sleep(retry_delay_seconds)

    raise RuntimeError(
        f"GET {url} failed after {attempts} attempts "
        f"with {timeout_seconds}s timeout: {last_error}"
    ) from last_error


latest = load_json("/api/v1/telemetry/latest?limit=1")
assert isinstance(latest.get("count"), int)
assert latest["count"] >= 0
assert isinstance(latest.get("items"), list)

now = datetime.now(UTC)
query = urlencode(
    {
        "from": (now - timedelta(minutes=5)).isoformat(),
        "to": now.isoformat(),
        "limit": 1,
    }
)
history = load_json(f"/api/v1/telemetry/history?{query}")
assert isinstance(history.get("count"), int)
assert history["count"] >= 0
assert isinstance(history.get("items"), list)
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
  curl -fsS "${CURL_RETRY[@]}" \
    -D /tmp/nexolab-central-cors.headers -o /dev/null \
    -H "Origin: $FIRST_ORIGIN" \
    "$BASE_URL/health/live"
  grep -qi "^access-control-allow-origin: $FIRST_ORIGIN" \
    /tmp/nexolab-central-cors.headers
fi

printf 'Central smoke test passed: %s\n' "$BASE_URL"
