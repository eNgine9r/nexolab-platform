# NEXOLAB Telemetry Service

Central backend service for M2 Backend Telemetry Ingestion.

## Responsibilities

- subscribe to `nexolab/telemetry` with MQTT QoS 1;
- validate version-1 telemetry events;
- persist samples idempotently by `event_id`;
- preserve the raw JSON payload for audit and forward compatibility;
- expose liveness, readiness and ingestion counters;
- return latest values and bounded telemetry history through REST;
- stream successfully committed telemetry through filtered WebSocket clients.

## Run locally

```bash
cd infrastructure/compose
cp .env.backend.example .env.backend
docker compose --env-file .env.backend -f compose.backend.yaml up --build
```

The command starts Mosquitto, PostgreSQL, the migration job and the telemetry service. Clean shutdown and repeatable restart use the same Compose project:

```bash
docker compose --env-file .env.backend -f compose.backend.yaml down
docker compose --env-file .env.backend -f compose.backend.yaml up --build
```

Apply migrations explicitly:

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

## Live telemetry WebSocket

Connect to:

```text
ws://127.0.0.1:8082/api/v1/telemetry/live
```

The endpoint accepts server-side filters using the same names as the REST API:

```bash
npx wscat -c \
  'ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01&equipment_id=K106&channel_id=106-03'
```

Only events committed successfully to PostgreSQL are broadcast. Duplicate MQTT deliveries are not broadcast again. Telemetry messages use the canonical event payload. Idle connections receive heartbeat objects:

```json
{ "type": "heartbeat", "server_time": "2026-07-23T13:00:00+00:00" }
```

Resume after reconnect by supplying a timezone-aware `after` timestamp. Persisted matching events are replayed oldest first before new live events:

```text
ws://127.0.0.1:8082/api/v1/telemetry/live?channel_id=106-03&after=2026-07-23T12:00:00%2B00:00
```

Each client has a bounded queue. A slow client is isolated and closed with WebSocket code `1013`; ingestion and other clients continue without waiting for it.

## End-to-end CI gate

The Telemetry service workflow starts isolated PostgreSQL 16 and Mosquitto 2.0.22 instances, applies Alembic migrations, then verifies:

```text
MQTT QoS 1 fixture
  → validation
  → PostgreSQL persistence
  → WebSocket delivery
  → latest REST
  → history REST
  → duplicate idempotency
```

The service is transport-configurable and is not yet deployed on the production Raspberry Pi. The current Edge hardware polling remains unchanged.
