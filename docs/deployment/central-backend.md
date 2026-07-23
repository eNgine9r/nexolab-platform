# NEXOLAB central backend deployment contract

## Scope

This runbook prepares the central telemetry backend for a controlled deployment. It does not change the production `edge-01` Modbus polling or its current local MQTT destination.

```text
edge-01 Device Agent
  → existing local MQTT path

central host
  → authenticated Mosquitto
  → Telemetry Service
  → PostgreSQL
  → REST / WebSocket
```

The Edge-to-central MQTT bridge is enabled only after the central stack passes its own acceptance checks.

## Artifact rule

Deploy only an immutable image tag produced by `.github/workflows/telemetry-service-image.yml`:

```text
ghcr.io/engine9r/nexolab-telemetry-service:sha-<full-commit-sha>
```

The mutable `edge` tag may be used for discovery but not as the recorded deployment artifact.

## Host prechecks

The selected central host must have:

- Docker Engine and Docker Compose v2;
- persistent storage for PostgreSQL and Mosquitto;
- a private ingress path for the dashboard and Edge bridge;
- outbound access to GHCR;
- synchronized UTC time;
- sufficient free disk for database growth and backups.

Before deployment:

```bash
hostnamectl
date -u
docker version
docker compose version
df -h
```

Do not expose ports `1884` or `8082` on `0.0.0.0` during the initial acceptance phase.

## Prepare configuration

```bash
cd infrastructure/compose
cp .env.backend.production.example .env.backend.production
mkdir -p secrets
chmod 700 secrets
```

Edit `.env.backend.production` and set:

- the full immutable `TELEMETRY_SERVICE_IMAGE` tag;
- unique PostgreSQL and MQTT passwords;
- the intended dashboard origin in `CORS_ALLOWED_ORIGINS`;
- localhost bind addresses for the first acceptance run.

Generate the Mosquitto password file using the same username and password recorded in the environment file:

```bash
read -r -p "MQTT username: " MQTT_USER
read -r -s -p "MQTT password: " MQTT_PASS
echo

docker run --rm \
  -e MQTT_USER="$MQTT_USER" \
  -e MQTT_PASS="$MQTT_PASS" \
  -v "$PWD/secrets:/work" \
  eclipse-mosquitto:2.0.22 \
  sh -c 'mosquitto_passwd -b -c /work/mosquitto.passwd "$MQTT_USER" "$MQTT_PASS"'

chmod 600 secrets/mosquitto.passwd
unset MQTT_USER MQTT_PASS
```

The username and password used above must match `MQTT_USERNAME` and `MQTT_PASSWORD` in `.env.backend.production`.

## Validate configuration without starting services

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  config > /tmp/nexolab-central-backend.yaml
```

Confirm:

```bash
grep -nE \
  'image:|published:|1884:1883|8082:8082|CORS_ALLOWED_ORIGINS|MQTT_USERNAME' \
  /tmp/nexolab-central-backend.yaml
```

The rendered image must use a `sha-<full-commit-sha>` tag. Password values must not be copied into tickets, chat messages or validation artifacts.

## Pull and verify the immutable image

```bash
set -a
. ./.env.backend.production
set +a

docker pull "$TELEMETRY_SERVICE_IMAGE"

docker run --rm --platform linux/amd64 \
  "$TELEMETRY_SERVICE_IMAGE" \
  python -c 'from app.main import SERVICE_VERSION; print(SERVICE_VERSION)'

docker run --rm --platform linux/amd64 \
  "$TELEMETRY_SERVICE_IMAGE" \
  alembic heads
```

Expected migration head:

```text
20260723_0003
```

## Initial central-stack acceptance

Start storage and broker first:

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  up -d postgres mqtt
```

Apply migrations as a one-shot gate:

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  run --rm telemetry-migrate
```

Start the service:

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  up -d telemetry-service

sleep 20
```

Verify:

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  ps

curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
curl -fsS http://127.0.0.1:8082/metrics | head -n 30
curl -fsS http://127.0.0.1:8082/ | python3 -m json.tool
```

The service must report both PostgreSQL and MQTT as ready before any Edge bridge is configured.

## Dashboard environment contract

The dashboard client uses only public environment variables:

```text
NEXT_PUBLIC_TELEMETRY_MODE=live
NEXT_PUBLIC_TELEMETRY_API_BASE_URL=https://<accepted-ingress>/telemetry-api
NEXT_PUBLIC_TELEMETRY_WS_URL=wss://<accepted-ingress>/telemetry-api/api/v1/telemetry/live
NEXT_PUBLIC_TELEMETRY_REQUEST_TIMEOUT_MS=10000
NEXT_PUBLIC_TELEMETRY_RECONNECT_MIN_MS=1000
NEXT_PUBLIC_TELEMETRY_RECONNECT_MAX_MS=30000
NEXT_PUBLIC_TELEMETRY_RECONNECT_JITTER_RATIO=0.2
```

When REST is exposed on a separate origin, the exact dashboard origin must appear in `CORS_ALLOWED_ORIGINS`. Wildcard origins are not used.

## Restart persistence check

After the local acceptance test:

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  restart

sleep 20
curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
```

A host reboot test belongs to M3 Gate 4 and is not performed before the target host and ingress are approved.

## Rollback

Application rollback uses a previously accepted immutable image tag. Do not downgrade the database migration during a normal application rollback.

```bash
cp .env.backend.production .env.backend.production.failed
# Restore the previous full-SHA TELEMETRY_SERVICE_IMAGE value.

docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  pull telemetry-service

docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  up -d --force-recreate telemetry-service
```

Emergency shutdown of the central stack does not require changing the production Edge Device Agent while the Edge bridge remains disabled:

```bash
docker compose \
  --env-file .env.backend.production \
  -f compose.backend.production.yaml \
  down
```

Database backup, restore and retention procedures remain defined in `docs/operations/telemetry-backend-runbook.md`.
