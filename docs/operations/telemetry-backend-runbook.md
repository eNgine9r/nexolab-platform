# NEXOLAB telemetry backend operations runbook

## Scope

This runbook covers the central telemetry stack:

```text
MQTT → validation → bounded persistence queue → PostgreSQL
                                           ├→ REST
                                           └→ WebSocket
```

It does not change the production Raspberry Pi Modbus polling configuration.

## Default retention policy

| Data class | Default retention | Action |
| --- | ---: | --- |
| Normalized telemetry | 365 days | Delete rows in bounded batches |
| Original raw JSON payload | 30 days | Replace raw JSON with `{}` and set `raw_payload_retained=false` |
| Dead-letter payload | 30 days | Delete rows in bounded batches |

Each scheduled cleanup processes at most `RETENTION_BATCH_SIZE` rows per data class. The default interval is one hour. This prevents cleanup from creating an unbounded transaction or long database lock.

Run cleanup once manually:

```bash
cd infrastructure/compose

docker compose --env-file .env.backend -f compose.backend.yaml \
  run --rm telemetry-service python -m app.retention
```

A successful run prints JSON containing:

```json
{
  "dead_letters_deleted": 0,
  "raw_payloads_redacted": 0,
  "telemetry_deleted": 0
}
```

## Health and metrics

Readiness:

```bash
curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
```

The response distinguishes:

- `database` readiness;
- `mqtt` subscription readiness after broker `SUBACK`;
- `database_outage_since`;
- `database_error`;
- `mqtt_error`;
- queue depth and ingestion lag.

Prometheus exposition:

```bash
curl -fsS http://127.0.0.1:8082/metrics
```

Human-readable JSON snapshot:

```bash
curl -fsS http://127.0.0.1:8082/metrics/json | python3 -m json.tool
```

Alert rules are stored in `infrastructure/observability/telemetry-alerts.yaml`.

## Poison or invalid MQTT payload

Invalid UTF-8, invalid JSON, non-object JSON, oversized payloads and schema validation failures are not inserted into `telemetry_samples`. They are retained in `telemetry_dead_letters` with one of these reason codes:

```text
payload_too_large
invalid_utf8
invalid_json
payload_not_object
schema_validation
```

Inspect recent records:

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

A rising `dead_letter_dropped_total` means the bounded persistence queue was full and a rejected payload could not be retained. Treat this as a capacity incident.

## MQTT broker outage

Expected behavior:

1. `/health/ready` becomes `503` with `mqtt=not_ready`.
2. `mqtt_error` identifies connection or subscription failure.
3. PostgreSQL and REST history remain available.
4. The client reconnects with bounded Paho MQTT backoff.
5. Readiness returns only after a successful `SUBACK`.

Checks:

```bash
curl -sS http://127.0.0.1:8082/health/ready | python3 -m json.tool

docker compose --env-file .env.backend -f compose.backend.yaml \
  logs --since=10m --no-color mqtt telemetry-service
```

Do not restart PostgreSQL to resolve a broker-only incident.

## PostgreSQL outage

Expected behavior:

1. the current telemetry or dead-letter item remains active in the persistence worker;
2. subsequent work accumulates in the bounded in-memory queue;
3. retries use exponential backoff from `DATABASE_RETRY_INITIAL_SECONDS` to `DATABASE_RETRY_MAX_SECONDS`;
4. `/health/ready` reports `database=not_ready` and the outage timestamp;
5. after PostgreSQL returns, the active item and queued items are persisted in order;
6. duplicate `event_id` delivery remains idempotent.

Checks:

```bash
curl -sS http://127.0.0.1:8082/metrics/json | python3 -m json.tool
```

Watch:

```text
queue_size
database_retry_total
persistence_failure_total
database_outage_since
database_recovery_total
```

Avoid restarting the telemetry-service container while PostgreSQL is unavailable. The retry queue is intentionally bounded and in-memory; a process termination during the outage can abandon uncommitted work.

## Bounded queue incident

When `queue_size` approaches `INGESTION_QUEUE_MAXSIZE`:

1. restore PostgreSQL first;
2. verify `database_ready=true`;
3. observe the queue draining;
4. verify `queue_dropped_total` is no longer increasing;
5. investigate storage latency and database saturation before raising the queue limit.

Increasing the limit consumes additional memory and does not fix a persistent database outage.

## Backup

Create a compressed logical backup:

```bash
cd infrastructure/compose
mkdir -p ../../runtime/backups

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "../../runtime/backups/nexolab-telemetry-$STAMP.dump"
```

Verify the archive is non-empty:

```bash
ls -lh ../../runtime/backups/nexolab-telemetry-*.dump
```

## Restore drill

Restore into a separate database. Do not overwrite production as the first validation step.

```bash
cd infrastructure/compose

BACKUP="../../runtime/backups/nexolab-telemetry-YYYYMMDDTHHMMSSZ.dump"

docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c \
  'createdb -U "$POSTGRES_USER" nexolab_restore_test'

docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d nexolab_restore_test --clean --if-exists' \
  < "$BACKUP"

docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c '
    psql -U "$POSTGRES_USER" -d nexolab_restore_test -c "
      SELECT COUNT(*) AS telemetry_samples FROM telemetry_samples;
      SELECT COUNT(*) AS dead_letters FROM telemetry_dead_letters;
    "
  '
```

Drop the drill database after verification:

```bash
docker compose --env-file .env.backend -f compose.backend.yaml \
  exec -T postgres sh -c \
  'dropdb -U "$POSTGRES_USER" nexolab_restore_test'
```

## Safe restart

```bash
cd infrastructure/compose

docker compose --env-file .env.backend -f compose.backend.yaml down

docker compose --env-file .env.backend -f compose.backend.yaml up -d --build

docker compose --env-file .env.backend -f compose.backend.yaml ps
curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
```

Apply migrations before starting an older image against a newer schema. Database downgrade is not the normal rollback path; application rollback must preserve compatibility with migration `20260723_0003`.
