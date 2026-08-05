# Telemetry delivery and physical acquisition boundary

Issue: #286  
Profile: `LOCAL_LAN`  
Runtime rule: offline-first, no hardware writes

## Decision

NEXOLAB separates telemetry into two one-way planes:

```text
Device Agent registry + adaptive scheduler
                ↓ read-only hardware acquisition
        MQTT telemetry event
                ↓ validation and persistence
     telemetry_samples committed row
                ↓
 PersistedTelemetryReadModel
        ├── REST latest/history
        └── WebSocket replay/fan-out
```

The Device Agent is the only owner of physical cadence. REST requests, page refreshes,
WebSocket connections, filters and reconnects are delivery-plane activity only.

## Acquisition plane

The Device Agent owns:

- registry eligibility;
- high, medium and low priority selection;
- monotonic deadlines;
- one serialized worker per physical bus;
- endpoint cooldown and fairness;
- Modbus driver calls;
- local latest-value acquisition persistence;
- MQTT publication or offline queueing.

Only an explicit registry mutation can reconcile recurring scheduler jobs. Client
subscriptions have no reference to the registry, scheduler, bus locks or hardware
drivers.

## Delivery plane

The telemetry service owns:

- MQTT ingress validation;
- durable staging and database persistence;
- idempotent committed telemetry rows;
- persisted latest/history queries;
- bounded WebSocket queues and filtering;
- committed-event fan-out;
- restart replay from the database.

The `PersistedTelemetryReadModel` is the REST and WebSocket replay source. Live
fan-out is invoked only from the ingestion callback that runs after a successful
database insert. Duplicate or rejected events are not broadcast.

## Truthful latest-state metadata

Every REST and WebSocket sample exposes:

- `received_at` — delivery persistence observation time;
- `age_seconds` — age of `captured_at` when projected;
- `quality` — source measurement quality;
- `state_source: persisted` — proof that delivery did not read hardware;
- `stale_after_seconds` — source-owned freshness threshold when supplied;
- `is_stale` and `staleness` — `fresh`, `stale` or explicit `unknown`.

The telemetry service does not duplicate scheduler intervals or infer a freshness
threshold from UI activity. When the source event does not carry a threshold,
staleness is reported as `unknown` rather than fabricating a fresh state.

## Invariants

1. REST handlers never import or call Device Agent drivers.
2. WebSocket handlers never mutate registry eligibility or scheduler priority.
3. Registering or unregistering clients changes only bounded fan-out state and
   WebSocket metrics.
4. Refresh and reconnect do not submit telemetry, create scheduler jobs or acquire
   a bus lock.
5. Service restart restores latest/history and WebSocket resume state from the
   telemetry database without triggering acquisition.
6. Physical acquisition remains FC03-only; this boundary adds no Modbus or hardware
   write path.

## Verification

Automated coverage includes:

- persisted read-model age, quality and staleness projection;
- repeated REST reads with an unchanged telemetry row count and zero ingestion;
- WebSocket connection churn with zero accepted or persisted telemetry;
- WebSocket churn changing only fan-out metrics;
- static proof that scheduler and registry code have no client-subscription inputs;
- restart latest and replay from the same database;
- static coupling scan for scheduler, registry, Modbus and driver references in
  delivery-plane modules.

Physical Raspberry Pi and RS-485 request-counter evidence remains a separate
hardware acceptance activity. Software tests prove architectural non-coupling but
do not replace measurements on the installed bus.
