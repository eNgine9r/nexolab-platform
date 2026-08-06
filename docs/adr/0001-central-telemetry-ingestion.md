# ADR-0001: Central telemetry ingestion architecture

## Status

Accepted for M2 implementation.

## Context

The production Edge node publishes one MQTT message per normalized measurement to `nexolab/telemetry`. The currently validated scope produces 34 records per polling cycle:

- XJP60D `106-03`, `106-04`;
- LE-01MP units `200`, `201`, `202`, `203` with eight metrics each.

The backend must preserve data through reconnects, avoid duplicate rows under MQTT QoS 1 redelivery, and support both historical and live dashboard views.

## Decision

Use a dedicated Python telemetry service with these boundaries:

```text
MQTT subscriber → contract validation → bounded queue → PostgreSQL
                                             ↓
                                   REST / WebSocket APIs
```

- MQTT QoS 1 is retained.
- `event_id` is the idempotency key and has a database unique constraint.
- PostgreSQL is the system of record for normalized telemetry.
- The complete raw JSON object is retained alongside normalized columns.
- Version 1 accepts additional JSON properties for forward compatibility.
- A `quality=valid` event requires a numeric `value`.
- Timestamps must be timezone-aware and are normalized to UTC.
- Liveness is process health; readiness requires both PostgreSQL and MQTT.

## Deployment boundary

The service is configurable through `MQTT_HOST`, `MQTT_PORT` and `DATABASE_URL`. M2 does not change the active Raspberry Pi Device Agent or its Modbus configuration. A secure path from the Edge-local broker to the eventual central environment will be handled as a separate deployment decision.

## Consequences

- Duplicate MQTT deliveries are safe.
- New optional producer fields do not break ingestion.
- Invalid payloads are rejected before persistence.
- Device-specific tables are avoided; equipment and metric identity remain data fields.
- Dead-letter storage, retention, REST history and WebSocket delivery remain explicit M2 backlog items.
