#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env.central}"
COMPOSE_FILE="$SCRIPT_DIR/compose.central.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing central environment file: $ENV_FILE" >&2
  exit 2
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${COMPOSE[@]}" config --quiet

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO_ROOT/runtime/evidence/m3-central-stop-$STAMP"
mkdir -p "$EVIDENCE_DIR"

"${COMPOSE[@]}" ps >"$EVIDENCE_DIR/central-compose-before.txt"
"${COMPOSE[@]}" stop telemetry-service mqtt postgres
"${COMPOSE[@]}" ps -a >"$EVIDENCE_DIR/central-compose-after.txt"

docker volume inspect nexolab-central-postgres-data \
  >"$EVIDENCE_DIR/postgres-volume.json"
docker volume inspect nexolab-central-mqtt-data \
  >"$EVIDENCE_DIR/mqtt-volume.json"

python3 - "$EVIDENCE_DIR" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
for name in ("postgres-volume.json", "mqtt-volume.json"):
    payload = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise SystemExit(f"Persistent volume evidence is invalid: {name}")

manifest = {
    "validation": "m3-central-stop",
    "status": "passed",
    "completed_at": datetime.now(UTC).isoformat(),
    "central_services_stopped": True,
    "postgres_volume_preserved": True,
    "mqtt_volume_preserved": True,
    "down_v_used": False,
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, indent=2))
PY

printf 'Central services stopped without deleting volumes. Evidence: %s\n' "$EVIDENCE_DIR"
