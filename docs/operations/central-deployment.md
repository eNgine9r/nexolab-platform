# NEXOLAB central deployment runbook

## Scope

This runbook deploys the M3 central telemetry path:

```text
central Mosquitto → Telemetry Service → PostgreSQL
                                  ├── REST
                                  └── WebSocket
```

It does not deploy or modify the Raspberry Pi Device Agent, Modbus configuration or `compose.hardware.yaml`.

## Prerequisites

- Docker Engine with Docker Compose v2;
- a central Linux host on the same trusted LAN, IoT VLAN or VPN as the intended clients;
- local checkout of `nexolab-platform`;
- `curl`, `python3` and `openssl` on the host;
- free API and MQTT ports selected in `.env.central`.

## 1. Create the environment file

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.central.example .env.central
```

Generate a PostgreSQL password:

```bash
openssl rand -base64 36 | tr -d '\n'
echo
```

Put the generated value in `POSTGRES_PASSWORD`. Do not commit `.env.central`.

Default bindings are local-only:

```text
CENTRAL_BIND_ADDRESS=127.0.0.1
CENTRAL_API_PORT=8082
CENTRAL_MQTT_PORT=1884
```

For a separate dashboard or edge host, replace `CENTRAL_BIND_ADDRESS` with the exact trusted interface address. Do not use `0.0.0.0` for the pilot.

Update `CORS_ALLOWED_ORIGINS` with every browser origin allowed to call the REST API. Keep it comma-separated and do not use `*`.

## 2. Validate the resolved Compose model

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  config --quiet
```

Inspect published ports before startup:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  config | sed -n '/ports:/,/volumes:/p'
```

Expected boundary:

- PostgreSQL has no published host port;
- MQTT binds only to `CENTRAL_BIND_ADDRESS:CENTRAL_MQTT_PORT`;
- REST/WebSocket binds only to `CENTRAL_BIND_ADDRESS:CENTRAL_API_PORT`.

## 3. Start the controlled stack

One repeatable deployment command:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  up -d --build --wait
```

Startup ordering is enforced:

1. PostgreSQL becomes healthy;
2. `telemetry-migrate` runs `alembic upgrade head` and exits successfully;
3. Mosquitto becomes healthy;
4. Telemetry Service starts and reaches `/health/ready`.

Inspect state:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  ps -a
```

`telemetry-migrate` must show exit code `0`. `postgres`, `mqtt` and `telemetry-service` must be healthy.

## 4. Run the deployment smoke gate

```bash
bash central-smoke.sh .env.central
```

The smoke gate checks:

- resolved Compose syntax;
- readiness JSON;
- Prometheus database readiness;
- latest endpoint;
- history endpoint;
- WebSocket handshake;
- configured CORS origin.

Manual checks:

```bash
curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
curl -fsS http://127.0.0.1:8082/metrics
curl -fsS 'http://127.0.0.1:8082/api/v1/telemetry/latest?limit=10' \
  | python3 -m json.tool
```

Replace `127.0.0.1` with the configured trusted interface address when needed.

## 5. Frontend mode contract

Copy the frontend template from the repository root:

```bash
cd ~/nexolab-platform
cp .env.local.example .env.local
```

Keep the dashboard isolated from the backend while Gate 1 is being validated:

```text
NEXT_PUBLIC_NEXOLAB_DATA_MODE=demo
```

The later #57/#58 cutover uses:

```text
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://<central-host>:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://<central-host>:8082/api/v1/telemetry/live
```

Live mode must never silently fall back to demo data.

## 6. MQTT route contract

Canonical M3 route:

```text
edge-01 → <central-host>:CENTRAL_MQTT_PORT → nexolab/telemetry
```

The current production records remain:

```text
XJP60D: 106-03, 106-04
LE-01MP: 200, 201, 202, 203
34 records per complete polling cycle
```

Do not change the edge MQTT target during Gate 1. The controlled `edge-01` cutover and rollback are implemented and tested separately in #59.

## 7. Logs and diagnostics

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  logs --since=15m --no-color telemetry-migrate telemetry-service mqtt postgres
```

Operational telemetry details, retention and outage handling remain documented in `docs/operations/telemetry-backend-runbook.md`.

## 8. Backup

```bash
cd ~/nexolab-platform/infrastructure/compose
mkdir -p ../../runtime/backups

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="../../runtime/backups/nexolab-central-$STAMP.dump"

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$BACKUP"

test -s "$BACKUP"
ls -lh "$BACKUP"
```

## 9. Restore drill

Restore to a separate database first:

```bash
cd ~/nexolab-platform/infrastructure/compose
BACKUP="../../runtime/backups/nexolab-central-YYYYMMDDTHHMMSSZ.dump"

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  exec -T postgres sh -c \
  'createdb -U "$POSTGRES_USER" nexolab_restore_test'

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d nexolab_restore_test --clean --if-exists' \
  < "$BACKUP"

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d nexolab_restore_test -c "
    SELECT COUNT(*) AS telemetry_samples FROM telemetry_samples;
    SELECT COUNT(*) AS dead_letters FROM telemetry_dead_letters;
  "'
```

Remove the drill database after verification:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  exec -T postgres sh -c \
  'dropdb -U "$POSTGRES_USER" nexolab_restore_test'
```

## 10. Application rollback

Record the current image first:

```bash
grep '^TELEMETRY_SERVICE_IMAGE=' .env.central
```

Set `TELEMETRY_SERVICE_IMAGE` to a previously validated tag and recreate only the application container:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  up -d --no-deps telemetry-service

bash central-smoke.sh .env.central
```

Do not add `--build` during an image rollback. The selected image must be compatible with the current database schema.

## 11. Stop without deleting data

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  down --remove-orphans
```

This preserves:

```text
nexolab-central-postgres-data
nexolab-central-mqtt-data
```

Never use `down -v` as a routine rollback or restart command.

## Acceptance record

Gate 1 is accepted after recording:

- central host and trusted bind address;
- deployed application image or commit;
- migration exit code;
- smoke test result;
- PostgreSQL and MQTT volume names;
- CORS origins;
- backup filename and restore-drill result;
- confirmation that `edge-01` Modbus mode was not changed.
