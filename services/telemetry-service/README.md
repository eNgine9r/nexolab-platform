# NEXOLAB Telemetry Service

Central backend service for M2 Backend Telemetry Ingestion.

## Responsibilities

- subscribe to `nexolab/telemetry` with MQTT QoS 1;
- validate version-1 telemetry events;
- persist samples idempotently by `event_id`;
- preserve the raw JSON payload for audit and forward compatibility;
- expose liveness, readiness and ingestion counters;
- return latest values and bounded telemetry history through REST.

## Run locally

```bash
cd infrastructure/compose
cp .env.backend.example .env.backend
docker compose --env-file .env.backend -f compose.backend.yaml up --build
```

Apply migrations:

```bash
docker compose --env-file .env.backend -f compose.backend.yaml \
  run --rm telemetry-service alembic upgrade head
```

## Health and OpenAPI

```bash
curl http://127.0.0.1:8082/health/live
curl http://127.0.0.1:8082/health/ready
curl http://127.0.0.1:8082/metrics
```

Interactive OpenAPI documentation is available at `http://127.0.0.1:8082/docs`.

## Latest telemetry

The latest endpoint returns one newest sample for each unique combination of node, equipment, channel and metric. Results are ordered by `captured_at` and `event_id` descending.

```bash
curl -G http://127.0.0.1:8082/api/v1/telemetry/latest \
  --data-urlencode 'node_id=edge-01' \
  --data-urlencode 'equipment_id=K106'
```

Supported filters:

- `node_id`;
- `equipment_id`;
- `channel_id`;
- `metric`;
- `quality`;
- `alarm`;
- `limit` and `offset`.

## Telemetry history

History requires timezone-aware `from` and `to` timestamps. The interval is inclusive at `from` and exclusive at `to`. The default maximum range is 31 days, and the maximum page size is 1000 records.

```bash
curl -G http://127.0.0.1:8082/api/v1/telemetry/history \
  --data-urlencode 'from=2026-07-23T00:00:00+00:00' \
  --data-urlencode 'to=2026-07-24T00:00:00+00:00' \
  --data-urlencode 'channel_id=106-03' \
  --data-urlencode 'limit=200'
```

Responses include `next_offset` when another page is available. Ordering is deterministic: `captured_at DESC, event_id DESC`.

The service is transport-configurable and is not yet deployed on the production Raspberry Pi. The current Edge hardware polling remains unchanged.
