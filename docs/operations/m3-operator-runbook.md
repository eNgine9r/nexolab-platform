# NEXOLAB M3 operator runbook

## Purpose

This is the canonical operator entry point for the M3 controlled backend deployment and live dashboard.

It covers:

- prerequisites and trust boundaries;
- initial central deployment and migrations;
- edge MQTT cutover;
- dashboard `demo` and `live` selection;
- health and telemetry validation;
- routine status capture;
- MQTT, PostgreSQL, backend and WebSocket incidents;
- backup and restore references;
- controlled rollback;
- evidence and known limitations.

Detailed supporting procedures:

- central deployment: [`central-deployment.md`](central-deployment.md);
- backend incidents, retention and recovery: [`telemetry-backend-runbook.md`](telemetry-backend-runbook.md);
- live cutover and outage drills: [`m3-cutover-validation.md`](m3-cutover-validation.md);
- evidence form: [`m3-validation-evidence-template.md`](m3-validation-evidence-template.md).

## Production contract

```text
XJP60D 106-03, 106-04
LE-01MP 200, 201, 202, 203
          │
          │ 34 telemetry records per complete polling cycle
          ▼
edge-01 Device Agent
          │ MQTT QoS 1
          ▼
edge Mosquitto persistent bridge
          ▼
central Mosquitto
          ▼
Telemetry Service
          ▼
PostgreSQL
          ├── REST latest/history
          └── WebSocket live
                    ▼
             NEXOLAB Dashboard
```

The cutover is MQTT-only. It must never modify:

- Modbus function usage;
- `DEVICE_MODE=modbus`;
- `compose.hardware.yaml`;
- the stable `/dev/serial/by-id/...` adapter path;
- XJP60D or LE-01MP register profiles;
- serial settings;
- polling interval.

## Operator responsibilities

| Role               | Responsibility                                                                                |
| ------------------ | --------------------------------------------------------------------------------------------- |
| Edge operator      | Preserve Modbus polling, stable USB path and local Device Agent health                        |
| Central operator   | Deploy Mosquitto, PostgreSQL, migrations and Telemetry Service                                |
| Dashboard operator | Select `demo` or `live` explicitly and verify freshness states                                |
| Incident owner     | Capture evidence before restart, preserve volumes and follow the subsystem-specific procedure |

One person may perform all roles during the pilot, but the boundaries remain explicit.

## Prerequisites

### Hosts

Required:

- Linux central host with Docker Engine and Docker Compose v2;
- `edge-01` with the validated production Device Agent deployment;
- Python 3.11 or newer;
- `curl`, `bash`, `awk` and standard Docker CLI;
- synchronized UTC time on edge, central and dashboard hosts;
- sufficient persistent storage for PostgreSQL, Mosquitto and edge SQLite.

Check:

```bash
docker --version
docker compose version
python3 --version
timedatectl status
```

### Network

Allowed pilot bindings:

- `127.0.0.1` for same-host access;
- one explicit trusted LAN or IoT VLAN interface;
- one explicit VPN interface.

Not approved:

- `0.0.0.0` on an untrusted network;
- direct public exposure;
- router port forwarding to MQTT or the API;
- public PostgreSQL access.

Default ports:

| Service                  |     Host port | Binding                                                |
| ------------------------ | ------------: | ------------------------------------------------------ |
| Edge Mosquitto           |          1883 | loopback only                                          |
| Central Mosquitto        |          1884 | loopback by default, trusted interface for remote edge |
| Telemetry REST/WebSocket |          8082 | loopback by default, trusted interface for dashboard   |
| PostgreSQL               | not published | internal Compose network only                          |
| Device Agent health      |          8081 | loopback only                                          |
| Dashboard                |          3000 | operator-selected trusted interface                    |

### Edge hardware contract

Before deployment:

```bash
readlink -f /dev/serial/by-id/<validated-adapter>
curl -fsS http://127.0.0.1:8081/health | python3 -m json.tool
```

Required health state:

```text
device_mode=modbus
last_error=null
```

Only one Modbus RTU master may operate on the physical bus.

## Repository preparation

On every participating host:

```bash
cd ~/nexolab-platform
git switch main
git pull --ff-only
```

Inspect the exact revision:

```bash
git rev-parse HEAD
git status --short
```

Do not deploy from an uncommitted working tree.

## Initial central deployment

### 1. Create the environment

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.central.example .env.central
chmod 600 .env.central
```

Set at minimum:

```dotenv
POSTGRES_PASSWORD=<strong-unique-password>
CENTRAL_BIND_ADDRESS=<trusted-interface-address>
CENTRAL_MQTT_PORT=1884
CENTRAL_API_PORT=8082
CORS_ALLOWED_ORIGINS=http://<dashboard-host>:3000
```

Do not commit `.env.central`.

### 2. Validate rendered Compose configuration

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  config --quiet
```

This must complete before images are built or containers are recreated.

### 3. Start the stack

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  up -d --build
```

Startup order is enforced:

1. PostgreSQL health;
2. `alembic upgrade head` successful completion;
3. Mosquitto health;
4. Telemetry Service readiness.

### 4. Verify migration completion

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  ps -a telemetry-migrate

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  logs --no-color telemetry-migrate
```

Expected result: migration service exited with code `0`.

### 5. Run central smoke gate

```bash
bash central-smoke.sh .env.central
```

The smoke gate verifies:

- Compose contract;
- `/health/ready`;
- Prometheus database readiness;
- latest REST response;
- history REST response;
- WebSocket handshake;
- configured CORS origin.

## Edge-to-central cutover

### 1. Prepare the cutover environment

On `edge-01`:

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.edge-central.example .env.edge-central
chmod 600 .env.edge-central
```

Copy the proven edge values rather than replacing them. Required production lines:

```dotenv
HARDWARE_DEVICE_MODE=modbus
RS485_HOST_DEVICE=/dev/serial/by-id/<validated-adapter>
XJP60D_POINTS=106:3,106:4
LE01MP_UNIT_IDS=200,201,202,203
CENTRAL_MQTT_HOST=<trusted-central-address>
CENTRAL_MQTT_PORT=1884
CENTRAL_API_BASE_URL=http://<trusted-central-address>:8082
CENTRAL_WEBSOCKET_URL=ws://<trusted-central-address>:8082/api/v1/telemetry/live
```

### 2. Execute the guarded cutover

```bash
bash m3-cutover.sh .env.edge-central
```

The script recreates only edge Mosquitto. It fails when the Device Agent container ID changes or Modbus mode changes.

Successful output identifies a timestamped directory:

```text
runtime/evidence/m3-cutover-<UTC_TIMESTAMP>/
```

Preserve the complete directory for Issue #59.

## Dashboard configuration

### Demo mode

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=demo
```

Demo mode uses only isolated static data.

### Live mode

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://<trusted-central-address>:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://<trusted-central-address>:8082/api/v1/telemetry/live
```

Live mode rejects missing or malformed URLs. A backend outage must display `reconnecting`, `stale`, `offline` or `error`; it must not silently show demo values.

After environment changes, rebuild or restart the frontend according to its deployment method:

```bash
npm run build
npm run start
```

For local development:

```bash
npm run dev -- --hostname 0.0.0.0
```

## Acceptance checks

### Readiness

```bash
curl -fsS http://<central-host>:8082/health/ready \
  | python3 -m json.tool
```

Required:

```text
status=ready
database=ready
mqtt=ready
```

### Metrics

```bash
curl -fsS http://<central-host>:8082/metrics
curl -fsS http://<central-host>:8082/metrics/json \
  | python3 -m json.tool
```

Watch:

- `queue_size`;
- `last_persisted_at`;
- `ingestion_lag_seconds`;
- `database_retry_total`;
- `database_recovery_total`;
- `queue_dropped_total`;
- `dead_letter_total`;
- `websocket_clients`;
- `mqtt_error`;
- `database_error`.

### Latest REST

```bash
curl -fsS \
  'http://<central-host>:8082/api/v1/telemetry/latest?node_id=edge-01&limit=1000' \
  | python3 -m json.tool
```

Expected production scope:

- at least 34 unique latest series;
- temperature channels `106-03`, `106-04`;
- eight current series for each LE-01MP unit `200–203`;
- valid units;
- explicit `quality` and `alarm` fields;
- fresh UTC `captured_at` values.

### History REST

Use timezone-aware UTC timestamps:

```bash
curl -G -fsS \
  'http://<central-host>:8082/api/v1/telemetry/history' \
  --data-urlencode 'node_id=edge-01' \
  --data-urlencode 'from=2026-07-23T18:00:00+00:00' \
  --data-urlencode 'to=2026-07-23T18:05:00+00:00' \
  --data-urlencode 'limit=1000' \
  | python3 -m json.tool
```

### WebSocket

The complete validation is automated by:

```bash
python3 m3-validate-cutover.py \
  --api-base-url 'http://<central-host>:8082' \
  --websocket-url 'ws://<central-host>:8082/api/v1/telemetry/live' \
  --evidence '../../runtime/evidence/manual-m3-validation.json'
```

It waits for a newly committed event whose `event_id` was not present in the REST snapshot.

## Routine operator status

Collect a read-only central bundle:

```bash
bash m3-status.sh .env.central
```

When edge and central run on the same host, or the command is executed on `edge-01` with access to both Compose projects:

```bash
bash m3-status.sh .env.central .env.edge-central
```

The collector:

- does not restart or stop services;
- does not copy environment files;
- does not delete data;
- captures Compose state, recent logs, readiness, metrics, latest summary and volume presence;
- verifies edge Modbus mode when the edge environment is supplied;
- writes a manifest under `runtime/evidence/`.

Recommended cadence:

- before deployment;
- after deployment;
- before an incident action;
- after recovery;
- before and after rollback.

## Incident routing

Do not restart every container for every incident. Diagnose the failed boundary first.

### Central MQTT incident

Symptoms:

- `mqtt=not_ready`;
- database remains ready;
- latest/history remain queryable but stop advancing;
- edge bridge logs reconnect attempts;
- dashboard freshness expires.

Checks:

```bash
docker compose --env-file .env.central -f compose.central.yaml ps mqtt
docker compose --env-file .env.central -f compose.central.yaml logs --since=15m --no-color mqtt
curl -sS http://<central-host>:8082/health/ready | python3 -m json.tool
```

Action:

```bash
docker compose --env-file .env.central -f compose.central.yaml start mqtt
```

Do not restart PostgreSQL for a broker-only incident.

### Edge bridge incident

Symptoms:

- local Device Agent remains healthy;
- central latest stops advancing;
- edge Mosquitto logs show bridge connection failures.

Checks:

```bash
docker compose \
  --env-file .env.edge-central \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  -f compose.edge-central-bridge.yaml \
  logs --since=15m --no-color mqtt

curl -fsS http://127.0.0.1:8081/health | python3 -m json.tool
```

Verify trusted central address, port and firewall. Do not recreate Device Agent to fix a bridge route.

### PostgreSQL incident

Symptoms:

- `database=not_ready`;
- queue and retry counters increase;
- MQTT may remain ready;
- latest/history requests fail or stop advancing.

Checks:

```bash
docker compose --env-file .env.central -f compose.central.yaml ps postgres
docker compose --env-file .env.central -f compose.central.yaml logs --since=15m --no-color postgres telemetry-service
curl -sS http://<central-host>:8082/metrics/json | python3 -m json.tool
```

Restore PostgreSQL first:

```bash
docker compose --env-file .env.central -f compose.central.yaml start postgres
```

Do not restart Telemetry Service while PostgreSQL is unavailable. Its bounded retry queue is in memory.

### Telemetry Service incident

Symptoms:

- API and WebSocket unavailable;
- MQTT and PostgreSQL containers may remain healthy;
- Device Agent continues local acquisition.

Checks:

```bash
docker compose --env-file .env.central -f compose.central.yaml ps telemetry-service telemetry-migrate
docker compose --env-file .env.central -f compose.central.yaml logs --since=15m --no-color telemetry-service telemetry-migrate
```

Before restart, verify database and MQTT readiness. Then:

```bash
docker compose --env-file .env.central -f compose.central.yaml restart telemetry-service
```

### WebSocket-only incident

Symptoms:

- readiness and REST succeed;
- dashboard reports reconnecting/stale;
- latest data advances after manual refresh;
- WebSocket client count or errors are abnormal.

Checks:

```bash
curl -fsS http://<central-host>:8082/health/ready | python3 -m json.tool
curl -fsS 'http://<central-host>:8082/api/v1/telemetry/latest?node_id=edge-01&limit=1' \
  | python3 -m json.tool
```

Run `m3-validate-cutover.py` to test the WebSocket independently of the browser. Verify reverse proxy upgrade headers when a proxy is present.

### Dashboard configuration incident

Symptoms:

- immediate `error` state;
- malformed URL message;
- CORS rejection;
- live mode never attempts the expected host.

Check the explicit public variables and browser origin. Never solve CORS by adding wildcard origins to the pilot profile.

### Stale telemetry with healthy transport

Check:

- edge clock and central clock;
- `captured_at` timestamps;
- Device Agent queue depth;
- Modbus error fields;
- central ingestion lag;
- future timestamp rejection count in the dashboard.

A WebSocket heartbeat is not proof of fresh device telemetry.

## Backup and restore

The authoritative commands and restore drill are in [`telemetry-backend-runbook.md`](telemetry-backend-runbook.md).

Minimum backup:

```bash
mkdir -p ../../runtime/backups
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose --env-file .env.central -f compose.central.yaml \
  exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "../../runtime/backups/nexolab-telemetry-$STAMP.dump"
test -s "../../runtime/backups/nexolab-telemetry-$STAMP.dump"
```

A backup is not accepted until it is restored into a separate test database and row counts are verified.

## Planned restart

Before restart:

```bash
bash m3-status.sh .env.central
```

Restart central services without deleting volumes:

```bash
docker compose --env-file .env.central -f compose.central.yaml restart
bash central-smoke.sh .env.central
```

Validate recent history remains available.

## Controlled rollback

### Edge routing rollback

```bash
bash m3-edge-rollback.sh .env.edge-central
```

This recreates only base edge Mosquitto and proves that Device Agent was not recreated and Modbus mode remains active.

### Central stop

```bash
bash m3-central-stop.sh .env.central
```

This stops central application services and verifies both persistent volumes still exist.

### Application image rollback

Set a schema-compatible previous image:

```dotenv
TELEMETRY_SERVICE_IMAGE=<previous-compatible-image>
```

Then recreate only the application and migration gate:

```bash
docker compose --env-file .env.central -f compose.central.yaml \
  up -d telemetry-migrate telemetry-service
```

Database migrations are forward-only for the pilot. Never select an image incompatible with the current schema.

### Frontend rollback

Set the intended mode explicitly:

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=demo
```

Do not treat demo mode as an automatic failover. It is a separate operator-selected environment.

## Evidence

Use [`m3-validation-evidence-template.md`](m3-validation-evidence-template.md).

Required artifacts:

- repository revision;
- central and edge environment fingerprints without secret values;
- health and metrics snapshots;
- latest 34-series summary;
- recent history count;
- new WebSocket event ID;
- unchanged Device Agent container ID;
- MQTT, PostgreSQL and WebSocket incident observations;
- duplicate suppression observation;
- restart persistence comparison;
- backup/restore drill result;
- edge and central rollback manifests;
- UTC timestamps and operator identity.

Do not attach `.env` files, database passwords, tokens or private keys.

## Known limitations

- Central Mosquitto is anonymous in the local pilot.
- MQTT and HTTP transport are not yet TLS-protected by this profile.
- There is one central host and no automatic high availability.
- PostgreSQL outage buffering inside Telemetry Service is bounded and in memory.
- Edge Mosquitto bridge queue is bounded by its broker configuration.
- Authentication, RBAC and per-node MQTT ACLs are outside M3.
- Frontend live telemetry is scoped to `edge-01` and current M3 production channels.
- Test sessions, laboratory map and cameras remain labelled demo until their APIs exist.
- The live temperature panel does not fabricate historical chart curves; history visualization remains a later UI scope.
- Anonymous MQTT must not be exposed beyond the trusted pilot boundary.
- None of the M3 procedures permits Modbus write functions.

## Completion criteria

Issue #60 is complete when this runbook, linked subsystem procedures, evidence template and read-only status collector are present and CI-validated.

Milestone M3 is complete only after real host execution also closes #56 and #59.
