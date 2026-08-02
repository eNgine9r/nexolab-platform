from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:72]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    subprocess.run(
        [
            "git",
            "checkout",
            "origin/main",
            "--",
            "infrastructure/compose/compose.disaster-recovery.yaml",
        ],
        cwd=ROOT,
        check=True,
    )

    overlay = ROOT / "infrastructure/compose/compose.disaster-recovery-local-auth.yaml"
    overlay.write_text(
        """services:
  source-migrate:
    volumes:
      - ${DR_SECRETS_DIR:?DR_SECRETS_DIR is required}:/run/secrets/nexolab:ro

  source-auth-service:
    image: ${DR_TELEMETRY_IMAGE:-nexolab-telemetry-service:disaster-recovery}
    restart: \"no\"
    init: true
    environment:
      DATABASE_URL: postgresql+psycopg://${DR_POSTGRES_USER:-nexolab}:${DR_POSTGRES_PASSWORD:?DR_POSTGRES_PASSWORD is required}@source-postgres:5432/${DR_POSTGRES_DB:-nexolab}
      MQTT_ENABLED: \"false\"
      BROKER_CONTROL_ENABLED: \"false\"
      OBJECT_STORAGE_BACKEND: disabled
      RETENTION_ENABLED: \"false\"
      AUTH_MODE: jwt
      AUTH_DEFAULT_ORGANIZATION_ID: ${DR_LOCAL_AUTH_ORGANIZATION_ID:-00000000-0000-0000-0000-000000000099}
      AUTH_LOCAL_ENABLED: \"true\"
      AUTH_LOCAL_PRIVATE_KEY_FILE: /run/secrets/nexolab/local-auth-private.pem
      AUTH_LOCAL_PUBLIC_KEY_FILE: /run/secrets/nexolab/local-auth-public.pem
      AUTH_LOCAL_ISSUER: urn:nexolab:dr-local-auth
      AUTH_LOCAL_AUDIENCE: nexolab-api
      AUTH_LOCAL_PROVIDER: nexolab-local
      AUTH_LOCAL_ACCESS_TOKEN_SECONDS: \"600\"
      AUTH_LOCAL_REFRESH_TOKEN_SECONDS: \"3600\"
    volumes:
      - ${DR_SECRETS_DIR:?DR_SECRETS_DIR is required}:/run/secrets/nexolab:ro
    depends_on:
      source-postgres:
        condition: service_healthy
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/health/ready', timeout=3)
      interval: 2s
      timeout: 4s
      retries: 30
      start_period: 5s
    networks: [dr]

  restore-telemetry-service:
    environment:
      AUTH_MODE: jwt
      AUTH_DEFAULT_ORGANIZATION_ID: ${DR_LOCAL_AUTH_ORGANIZATION_ID:-00000000-0000-0000-0000-000000000099}
      AUTH_LOCAL_ENABLED: \"true\"
      AUTH_LOCAL_PRIVATE_KEY_FILE: /run/secrets/local-auth/private.pem
      AUTH_LOCAL_PUBLIC_KEY_FILE: /run/secrets/local-auth/public.pem
      AUTH_LOCAL_ISSUER: urn:nexolab:dr-local-auth
      AUTH_LOCAL_AUDIENCE: nexolab-api
      AUTH_LOCAL_PROVIDER: nexolab-local
      AUTH_LOCAL_ACCESS_TOKEN_SECONDS: \"600\"
      AUTH_LOCAL_REFRESH_TOKEN_SECONDS: \"3600\"
    volumes:
      - ${DR_RESTORE_LOCAL_AUTH_DIR:?DR_RESTORE_LOCAL_AUTH_DIR is required}:/run/secrets/local-auth:ro
""",
        encoding="utf-8",
    )

    run = "scripts/run-disaster-recovery-acceptance.sh"
    replace_once(
        run,
        'COMPOSE_FILE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery.yaml"',
        'BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery.yaml"\nLOCAL_AUTH_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery-local-auth.yaml"',
    )
    replace_once(
        run,
        '  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"',
        '  docker compose \\\n    --project-name "$PROJECT_NAME" \\\n    -f "$BASE_COMPOSE" \\\n    -f "$LOCAL_AUTH_COMPOSE" \\\n    "$@"',
    )
    replace_once(
        run,
        '>"$WORK_DIR/source-local-auth-tokens.json" <<\'PY\'',
        '>"$SECRETS_DIR/source-local-auth-tokens.json" <<\'PY\'',
    )
    replace_once(
        run,
        'chmod 0600 "$WORK_DIR/source-local-auth-tokens.json"',
        'chmod 0600 "$SECRETS_DIR/source-local-auth-tokens.json"',
    )
    replace_once(
        run,
        '  "$PROJECT_NAME" "$COMPOSE_FILE" "$EVIDENCE_DIR"',
        '  "$PROJECT_NAME" "$BASE_COMPOSE" "$LOCAL_AUTH_COMPOSE" "$EVIDENCE_DIR"',
    )

    verify = "scripts/verify-restored-platform.sh"
    replace_once(
        verify,
        '''if [[ $# -ne 3 ]]; then
  echo "Usage: verify-restored-platform.sh <project-name> <compose-file> <evidence-dir>" >&2
  exit 64
fi

PROJECT_NAME=$1
COMPOSE_FILE=$2
EVIDENCE_DIR=$3
''',
        '''if [[ $# -ne 4 ]]; then
  echo "Usage: verify-restored-platform.sh <project-name> <base-compose> <local-auth-compose> <evidence-dir>" >&2
  exit 64
fi

PROJECT_NAME=$1
BASE_COMPOSE=$2
LOCAL_AUTH_COMPOSE=$3
EVIDENCE_DIR=$4
''',
    )
    replace_once(
        verify,
        'TOKEN_FILE="${DR_WORK_DIR:?DR_WORK_DIR is required}/source-local-auth-tokens.json"',
        'TOKEN_FILE="${DR_SECRETS_DIR:?DR_SECRETS_DIR is required}/source-local-auth-tokens.json"',
    )
    replace_once(
        verify,
        '  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"',
        '  docker compose \\\n    --project-name "$PROJECT_NAME" \\\n    -f "$BASE_COMPOSE" \\\n    -f "$LOCAL_AUTH_COMPOSE" \\\n    "$@"',
    )
    replace_once(
        verify,
        '''compose exec -T restore-telemetry-service python - \\
  "$ORGANIZATION_ID" <"$TOKEN_FILE" <<'PY'
from __future__ import annotations

import asyncio
import json
import sys
import websockets

organization_id = sys.argv[1]
tokens = json.load(sys.stdin)
''',
        '''compose exec -T restore-telemetry-service python - \\
  "$ORGANIZATION_ID" <<'PY'
from __future__ import annotations

from pathlib import Path
import asyncio
import json
import sys
import websockets

organization_id = sys.argv[1]
tokens = json.loads(
    Path("/run/secrets/nexolab/source-local-auth-tokens.json").read_text(
        encoding="utf-8"
    )
)
''',
    )


if __name__ == "__main__":
    main()
