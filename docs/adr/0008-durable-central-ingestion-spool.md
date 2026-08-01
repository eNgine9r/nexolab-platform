# ADR 0008: Durable local staging between MQTT and PostgreSQL

- **Status:** Proposed in Issue #198 / PR #207
- **Date:** 2026-08-01
- **Profile:** `LOCAL_LAN`

## Context

The Device Agent stores telemetry in edge SQLite until its configured MQTT broker returns a QoS 1 acknowledgement. It then removes the edge outbox row. Before this decision, the central MQTT callback placed the payload in a bounded in-memory Telemetry Service queue and PostgreSQL commit happened later.

A PostgreSQL outage followed by Telemetry Service termination could therefore lose a payload that had already been acknowledged to the edge. MQTT QoS 1 proved delivery to the broker/consumer boundary, not recoverability until PostgreSQL commit.

The correction must:

- work without internet, paid services or cloud queues;
- preserve `event_id` idempotency;
- survive Telemetry Service/container restart;
- preserve pending data across image rollback and container recreation;
- fail visibly on disk, capacity or integrity errors;
- avoid any Modbus or hardware write path.

## Decision

Use a local SQLite ingestion spool owned by the Telemetry Service.

The central telemetry path becomes:

```text
MQTT QoS 1 delivery
        ↓
Telemetry Service validates the payload
        ↓
SQLite WAL spool transaction (`synchronous=FULL`)
        ↓
manual MQTT acknowledgement
        ↓
FIFO PostgreSQL persistence worker
        ↓
`event_id` insert or idempotent duplicate result
        ↓
delete the spool record
```

The spool is stored in a dedicated named Compose volume and uses:

- SQLite WAL mode;
- `synchronous=FULL`;
- one FIFO sequence across telemetry and dead-letter records;
- unique telemetry `event_id` values;
- a delivery key for MQTT redelivery deduplication;
- payload equality checks when a deduplication key is reused;
- configured record and payload-byte capacities;
- retry metadata and terminal quarantine;
- pending depth, retained bytes, oldest age, replay, capacity, terminal and error metrics.

When durable mode is active, the Paho MQTT client uses a persistent MQTT v3 session and manual acknowledgements. A QoS 1 message is acknowledged only after the local spool transaction succeeds. When staging fails because of capacity, disk or integrity problems, the callback keeps the message unacknowledged and retries with bounded exponential backoff. This creates backpressure instead of silently dropping evidence.

After PostgreSQL successfully inserts an event—or reports an existing `event_id`—the worker deletes the corresponding spool row. If deleting the row fails, replay is safe because PostgreSQL persistence is idempotent by `event_id`.

Invalid telemetry is represented as a durable dead-letter spool record before acknowledgement. Schema-invalid input is therefore not lost during a PostgreSQL outage or service restart.

## Scope boundary

This decision covers the telemetry measurement stream handled by `TelemetryIngestor`.

Node health and status streams continue to use their existing persistence worker and are not claimed to have the same process-restart durability in this Work Package. Extending the common durable envelope to those streams requires a separate scoped Issue if operational evidence shows it is necessary.

## Ordering

Pending spool records are processed by monotonically increasing local spool ID. This preserves arrival order inside one Telemetry Service spool. MQTT reconnects and multiple publishers may already produce bounded inter-node reordering before local staging; `captured_at`, node sequence fields and `event_id` remain the authoritative event semantics.

One unavailable or repeatedly failing PostgreSQL write holds later spool records behind it. This deliberate head-of-line behavior preserves strict local FIFO. The queue age and depth metrics make the condition observable.

## Capacity and disk-full behavior

Terminal records remain in the same capacity accounting until an explicit future operator workflow handles them. They are not silently deleted.

When record or byte capacity is reached:

- the payload is not acknowledged to MQTT;
- capacity/error metrics increase;
- readiness/metrics expose the spool state;
- the publisher/broker retains responsibility for redelivery subject to its configured persistence and limits.

This Work Package does not automate destructive cleanup of terminal or pending records.

## Shutdown, restart and rollback

Normal shutdown stops MQTT intake before stopping the persistence worker. Pending rows remain in SQLite and replay after restart.

The named spool volume must not be deleted during update or rollback. Operational procedures must never use `docker compose down -v`.

Rollback to an image that does not understand the spool is unsafe while pending or terminal records exist. Operators must inspect spool metrics and use a compatible image until the spool is empty or an explicit migration/recovery procedure is approved.

## Alternatives considered

### Broker persistence with acknowledgement delayed until PostgreSQL commit

Rejected as the only mechanism. It would keep application callbacks blocked for the full PostgreSQL outage, complicate shutdown/restart ownership and still rely on broker/client-session behavior as the only local application recovery boundary.

### PostgreSQL inbox table

Rejected for this failure mode because PostgreSQL is the unavailable component. It cannot be the only staging layer for its own outage.

### External queue or cloud service

Rejected because the core `LOCAL_LAN` runtime must work without internet, mandatory payment or external infrastructure.

### Existing bounded in-memory queue

Rejected because it cannot survive process or container restart.

## Consequences

### Positive

- MQTT-acknowledged telemetry remains locally recoverable until PostgreSQL persistence.
- PostgreSQL outage plus Telemetry Service restart no longer creates the previous silent-loss window.
- The design uses standard-library SQLite and local named volumes only.
- Failure and backlog are observable.
- Existing PostgreSQL `event_id` idempotency makes replay safe.

### Trade-offs

- Local disk capacity becomes part of the ingestion safety envelope.
- Strict FIFO can cause head-of-line blocking.
- The spool volume must be included in backup, restore and rollback procedures.
- Manual MQTT acknowledgement may hold an MQTT network callback during local staging failures; this is intentional backpressure but requires operational monitoring.
- Actual-host power-loss, disk-loss and long-duration capacity evidence remain part of Issue #189 and are not proven by software CI alone.

## Verification required

- unit tests for reopen, FIFO, capacity, conflict and terminal records;
- process-restart replay tests;
- PostgreSQL outage plus Telemetry Service restart integration test;
- MQTT acknowledgement boundary tests;
- duplicate-delivery/idempotency tests;
- Compose configuration and named-volume validation;
- container build;
- metrics/readiness inspection;
- controlled actual-host restart/rollback evidence before production acceptance.
