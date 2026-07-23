# ADR 0004: Controlled central deployment topology

- Status: Accepted
- Date: 2026-07-23
- Issues: #54, #55, #56

## Context

M2 proved the telemetry backend contract and operational behavior. M3 must deploy that backend on a controlled central host and later connect the NEXOLAB dashboard without changing the proven Raspberry Pi Modbus polling path.

The production input remains:

- node `edge-01`;
- XJP60D channels `106-03` and `106-04`;
- LE-01MP units `200`, `201`, `202`, `203`;
- 34 telemetry records per complete polling cycle;
- canonical MQTT topic `nexolab/telemetry`.

The central deployment must not expose PostgreSQL, MQTT or the telemetry API to arbitrary interfaces by default.

## Decision

Use one central Docker Compose project named `nexolab-central` containing:

```text
edge-01 Device Agent
        ↓ MQTT QoS 1
central Mosquitto
        ↓ validated ingestion
Telemetry Service
        ↓
PostgreSQL
        ├── REST latest/history
        └── WebSocket live
```

The controlled profile is `infrastructure/compose/compose.central.yaml` with environment contract `infrastructure/compose/.env.central.example`.

## Service ownership

| Concern | Owner |
| --- | --- |
| Modbus RTU polling and local SQLite outbox | `edge-01` Device Agent |
| Canonical M3 MQTT ingress | central Mosquitto |
| Schema migration | one-shot `telemetry-migrate` service |
| Persistence, latest/history and live fan-out | central Telemetry Service |
| Durable telemetry store | central PostgreSQL |
| Demo/live selection | NEXOLAB frontend runtime configuration |

The later edge cutover is MQTT-only. It must not modify `DEVICE_MODE`, `compose.hardware.yaml`, RS-485 device paths, register profiles or polling intervals.

## Network boundary

The default binding is loopback:

| Service | Container port | Default host binding |
| --- | ---: | --- |
| MQTT | 1883 | `127.0.0.1:1884` |
| Telemetry REST/WebSocket | 8082 | `127.0.0.1:8082` |
| PostgreSQL | 5432 | not published |

`CENTRAL_BIND_ADDRESS` may be changed only to an explicit trusted LAN, IoT VLAN or VPN interface address. `0.0.0.0` is not an approved pilot value.

Mosquitto remains anonymous for the local pilot, so the published MQTT socket must stay on loopback or an isolated trusted interface. Authentication and per-node ACLs are required before broader network exposure.

## URL contract

Frontend runtime variables are explicit:

```text
NEXT_PUBLIC_NEXOLAB_DATA_MODE=demo|live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://<trusted-host>:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://<trusted-host>:8082/api/v1/telemetry/live
```

In `demo` mode the dashboard uses only isolated demo data. In `live` mode the adapter introduced by #57 must reject missing or malformed API/WebSocket URLs rather than silently falling back to demo data.

The REST contract is:

```text
GET /health/ready
GET /metrics
GET /api/v1/telemetry/latest
GET /api/v1/telemetry/history
```

The live contract is:

```text
WS /api/v1/telemetry/live
```

## CORS policy

The telemetry service accepts a comma-separated `CORS_ALLOWED_ORIGINS` allowlist. The controlled profile defaults to the local dashboard origins:

```text
http://127.0.0.1:3000
http://localhost:3000
```

Wildcard origins are not part of the controlled profile. Cross-origin credentials remain disabled until authentication is introduced.

## Persistence and migration ordering

Named volumes are stable across container recreation:

```text
nexolab-central-postgres-data
nexolab-central-mqtt-data
```

`telemetry-service` starts only after:

1. PostgreSQL is healthy;
2. `alembic upgrade head` exits successfully;
3. Mosquitto is healthy.

PostgreSQL is never published to the host in this profile. Backup and restore use `docker compose exec` against the internal service.

## Deployment gate

A deployment is accepted only when `central-smoke.sh` verifies:

- Compose configuration validity;
- `/health/ready`;
- Prometheus database readiness;
- REST latest;
- REST history;
- WebSocket handshake;
- configured CORS response.

## Rollback

Application rollback changes only `TELEMETRY_SERVICE_IMAGE` and recreates `telemetry-service` without deleting volumes. Database migrations are forward-only for the pilot; an older image may be selected only when it is compatible with the current schema.

The rollback procedure must not run `docker compose down -v` and must not change the Raspberry Pi hardware deployment files.

## Consequences

Positive:

- one repeatable central deployment command;
- deterministic migration-before-readiness;
- durable PostgreSQL and MQTT state;
- no public service exposure by default;
- explicit dashboard mode and URL contract;
- rollback isolated from Modbus acquisition.

Trade-offs:

- anonymous MQTT is acceptable only inside the pilot trust boundary;
- the first deployment uses one central host and is not highly available;
- frontend validation and the live state machine remain separate work in #57 and #58;
- actual `edge-01` broker cutover and rollback remain separate work in #59.
