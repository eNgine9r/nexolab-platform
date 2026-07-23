# NEXOLAB Telemetry Service

First backend vertical slice for M2 Backend Telemetry Ingestion.

## Responsibilities

- subscribe to `nexolab/telemetry` with MQTT QoS 1;
- validate version-1 telemetry events;
- persist samples idempotently by `event_id`;
- preserve the raw JSON payload for audit and forward compatibility;
- expose liveness, readiness and ingestion counters.

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

Health endpoints:

```bash
curl http://127.0.0.1:8082/health/live
curl http://127.0.0.1:8082/health/ready
curl http://127.0.0.1:8082/metrics
```

The service is transport-configurable and is not yet deployed on the production Raspberry Pi. The current Edge hardware polling remains unchanged.
