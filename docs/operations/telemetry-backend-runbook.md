# NEXOLAB telemetry backend operations runbook

## Scope

This runbook covers the central telemetry stack:

```text
MQTT QoS 1
    ↓ validate
local SQLite WAL ingestion spool
    ↓ FIFO replay
PostgreSQL
    ├→ REST
    └→ WebSocket
```

The spool is the durable application boundary between MQTT delivery and PostgreSQL commit. It does not change the production Raspberry Pi Modbus polling configuration and introduces no hardware write path.

## Delivery and acknowledgement contract

When `INGESTION_SPOOL_ENABLED=true`:

1. the Telemetry Service receives a QoS 1 MQTT message;
2. it validates the payload or classifies it as a dead letter;
3. it commits the work to the local SQLite spool using WAL and `synchronous=FULL`;
4. only after that commit does it manually acknowledge the MQTT message;
5. a FIFO worker persists the record to PostgreSQL;
6. an existing `event_id` is treated as an idempotent duplicate;
7. the spool row is deleted after successful PostgreSQL processing.

If local staging fails, the message remains unacknowledged and the service retries staging with bounded exponential backoff. This is intentional backpressure. Do not treat it as permission to delete the spool volume.

The standard paths are:

```text
/app/data/telemetry-ingestion/spool.db
```

Compose stores that directory in a dedicated named volume:

```text
backend-telemetry-ingestion-data
central-telemetry-ingestion-data
```

The exact volume name may be prefixed by `COMPOSE_PROJECT_NAME` or `CENTRAL_RESOURCE_PREFIX`.

## Default durable spool limits

| Setting                                 |    Default | Meaning                                        |
| --------------------------------------- | ---------: | ---------------------------------------------- |
| `INGESTION_SPOOL_MAX_RECORDS`           |     500000 | Pending plus terminal records retained locally |
| `INGESTION_SPOOL_MAX_BYTES`             | 4294967296 | Retained payload bytes, approximately 4 GiB    |
| `INGESTION_SPOOL_BUSY_TIMEOUT_SECONDS`  |          5 | SQLite lock wait                               |
| `INGESTION_SPOOL_POLL_INTERVAL_SECONDS` |        0.1 | Idle FIFO worker poll interval                 |

Terminal records remain in capacity accounting until a separate approved operator workflow handles them. NEXOLAB does not silently delete terminal or pending evidence.

## Default PostgreSQL retention policy

| Data class                | Default retention | Action                                                          |
| ------------------------- | ----------------: | --------------------------------------------------------------- |
| Normalized telemetry      |          365 days | Delete rows in bounded batches                                  |
| Original raw JSON payload |           30 days | Replace raw JSON with `{}` and set `raw_payload_retained=false` |
| Dead-letter payload       |           30 days | Delete rows in bounded batches                                  |

Each scheduled cleanup processes at most `RETENTION_BATCH_SIZE` rows per data class. The default interval is one hour.

Run cleanup once manually:

```bash
cd infrastructure/compose

docker compose --env-file .env.backend -f compose.backend.yaml \
  run --rm telemetry-service python -m app.retention
```

## Health and metrics

Readiness:

```bash
curl -sS http://127.0.0.1:8082/health/ready | python3 -m json.tool
```

Prometheus exposition:

```bash
curl -fsS http://127.0.0.1:8082/metrics
```

Human-readable JSON snapshot:

```bash
curl -fsS http://127.0.0.1:8082/metrics/json | python3 -m json.tool
```

Monitor at minimum:

```text
mqtt_connected
database_ready
spool_ready
spool_pending_records
spool_terminal_records
spool_payload_bytes
spool_oldest_pending_age_seconds
spool_max_records
spool_max_bytes
spool_staged_total
spool_recovered_total
spool_replayed_total
spool_capacity_failure_total
spool_error_total
mqtt_manual_ack_total
mqtt_ack_failure_total
mqtt_stage_retry_total
database_retry_total
persistence_failure_total
database_outage_since
```

`/health/ready` remains strict: PostgreSQL and the MQTT subscription must be ready. During a PostgreSQL outage, the service may still be safely retaining telemetry in the local spool while readiness correctly returns `503`.

Alert rules are stored in `infrastructure/observability/telemetry-alerts.yaml`. A future observability Work Package may add explicit thresholds for the new spool gauges; until then, operators must inspect them directly.

## Poison or invalid MQTT payload

Invalid UTF-8, invalid JSON, non-object JSON, oversized payloads and schema validation failures are not inserted into `telemetry_samples`. They are first staged durably and later committed to `telemetry_dead_letters` with one of these reason codes:

```text
payload_too_large
invalid_utf8
invalid_json
payload_not_object
schema_validation
```

Inspect recent PostgreSQL dead letters:

```bash
cd infrastructure/compose

docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c '
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
      SELECT id, received_at, topic, reason_code,
             payload_size, payload_truncated, reason_detail
      FROM telemetry_dead_letters
      ORDER BY received_at DESC
      LIMIT 50;
    "
  '
```

A non-zero `spool_terminal_records` means the current software could not decode or safely process a durable local record. Do not delete the volume. Preserve the SQLite files, collect logs and inspect the software/version boundary.

## MQTT broker outage

Expected behavior:

1. `/health/ready` becomes `503` with `mqtt=not_ready`;
2. PostgreSQL and REST history remain available;
3. the MQTT client reconnects with bounded Paho backoff;
4. the durable client uses a persistent MQTT v3 session;
5. readiness returns after a successful `SUBACK`.

Checks:

```bash
curl -sS http://127.0.0.1:8082/health/ready | python3 -m json.tool

docker compose --env-file .env.backend -f compose.backend.yaml \
  logs --since=10m --no-color mqtt telemetry-service
```

Do not restart PostgreSQL to resolve a broker-only incident.

## PostgreSQL outage

Expected behavior with durable staging enabled:

1. valid telemetry and invalid payloads are committed to the local spool;
2. QoS 1 messages are acknowledged only after that local commit;
3. `spool_pending_records` and oldest age increase;
4. PostgreSQL retries use bounded exponential backoff;
5. `/health/ready` reports `database=not_ready`;
6. restarting the Telemetry Service does not remove pending spool rows;
7. after PostgreSQL returns, records replay in local FIFO order;
8. duplicate `event_id` delivery remains idempotent.

Checks:

```bash
curl -sS http://127.0.0.1:8082/metrics/json | python3 -m json.tool

docker compose --env-file .env.backend -f compose.backend.yaml \
  logs --since=10m --no-color telemetry-service postgres
```

Unlike the previous in-memory design, a controlled Telemetry Service restart during a PostgreSQL outage no longer abandons telemetry already staged in the SQLite spool. The named volume must remain mounted.

## Spool capacity or disk incident

Symptoms:

```text
spool_capacity_failure_total increases
spool_error_total increases
mqtt_stage_retry_total increases
spool_ready=false
oldest pending age grows
```

Response:

1. do not delete, truncate or replace the spool database;
2. verify the named volume is mounted and writable;
3. verify host free space and filesystem health;
4. restore PostgreSQL if it is unavailable;
5. observe pending records draining;
6. collect `telemetry-service` logs;
7. inspect terminal records and software compatibility;
8. increase configured limits only after capacity analysis.

When staging cannot commit locally, QoS 1 telemetry remains unacknowledged. Broker/publisher persistence and their configured limits become the upstream safety envelope. Capacity incidents are therefore urgent and visible, not silent drops.

## Inspect the spool volume

Stop the Telemetry Service before copying or directly inspecting its SQLite files.

Backend profile example:

```bash
cd infrastructure/compose

docker compose --env-file .env.backend -f compose.backend.yaml \
  stop telemetry-service

docker run --rm \
  -v nexolab-backend_backend-telemetry-ingestion-data:/source:ro \
  alpine:3.22 \
  sh -c 'ls -lah /source'
```

The resolved Docker volume name may differ. Determine it first:

```bash
docker volume ls | grep telemetry-ingestion
```

Restart after inspection:

```bash
docker compose --env-file .env.backend -f compose.backend.yaml \
  up -d telemetry-service
```

Do not open the live spool with ad-hoc write commands.

## Backup boundary

PostgreSQL logical backup remains required, but it is not sufficient while the spool contains pending or terminal records. The dedicated spool volume must be included in central backup/recovery procedures.

Before a controlled backup, inspect:

```bash
curl -fsS http://127.0.0.1:8082/metrics/json \
  | python3 -c '
import json, sys
value = json.load(sys.stdin)
print({
    "pending": value.get("spool_pending_records"),
    "terminal": value.get("spool_terminal_records"),
    "bytes": value.get("spool_payload_bytes"),
})
'
```

Create the PostgreSQL backup:

```bash
cd infrastructure/compose
mkdir -p ../../runtime/backups

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "../../runtime/backups/nexolab-telemetry-$STAMP.dump"
```

Issue #189 owns the final coordinated backup/restore proof for PostgreSQL, Mosquitto, MinIO, the ingestion spool, edge SQLite and controlled power-loss scenarios.

## Safe restart

Container recreation is safe only when named volumes are preserved:

```bash
cd infrastructure/compose

docker compose --env-file .env.backend -f compose.backend.yaml down

docker compose --env-file .env.backend -f compose.backend.yaml up -d --build

docker compose --env-file .env.backend -f compose.backend.yaml ps
curl -sS http://127.0.0.1:8082/health/ready | python3 -m json.tool
curl -fsS http://127.0.0.1:8082/metrics/json | python3 -m json.tool
```

Never use:

```text
docker compose down -v
docker volume rm ...telemetry-ingestion...
```

## Rollback

Do not roll back to an image that does not understand the durable spool while `spool_pending_records` or `spool_terminal_records` is non-zero.

Before rollback:

1. record the running image/version;
2. inspect spool pending and terminal counts;
3. confirm the target image supports ADR 0008 and the existing spool schema;
4. preserve all named volumes;
5. perform the rollback without `-v`;
6. verify replay, PostgreSQL counts, metrics and logs.

Actual-host rollback and disk-loss recovery remain unverified until the controlled evidence in Issue #189 is completed.
