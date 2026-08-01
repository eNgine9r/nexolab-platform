# NEXOLAB verified architecture baseline

**Baseline date:** 2026-08-01  
**Verified `main`:** `bd286690f94bdf06adf3fc630bdee69c5019ebce`  
**Project profile:** `LOCAL_LAN`

This document records the repository-backed NEXOLAB architecture. Implementation, software acceptance, actual-host acceptance and real-hardware acceptance are separate evidence levels.

## 1. System boundary

```text
Local operator browser
        │ HTTP / WebSocket on trusted LAN
        ▼
Next.js dashboard
        │ typed REST and WebSocket contracts
        ▼
FastAPI Telemetry Service
        ├── local SQLite durable ingestion spool
        ├── PostgreSQL 16
        ├── local S3-compatible object storage (MinIO)
        └── central Eclipse Mosquitto
                    ▲
                    │ MQTT QoS 1
                    │
          edge Eclipse Mosquitto
                    ▲
                    │
             Device Agent
        ├── SQLite outbound queue
        ├── health/readiness endpoint
        └── read-only Modbus RTU
                    ▲
                    │ FC03, one register per request
                    │
       XJP60D and LE-01MP devices
```

The core data path can run entirely inside the local network. Internet connectivity and paid cloud services are not runtime requirements.

## 2. Frontend boundary

The frontend uses Next.js App Router, React, TypeScript and local CSS/Tailwind assets. It provides explicit demo and live modes, typed REST/WebSocket clients and feature modules for telemetry, sessions, alerts, reports, nodes, security and refrigeration.

Rules preserved:

- stale or unavailable telemetry is not relabeled as live;
- demo data does not silently replace a failed live path;
- no mandatory CDN, remote font, analytics SDK or browser telemetry owns the local runtime;
- Tailscale and Supabase remain optional layers;
- secure fully local operator authentication remains Issue #188.

## 3. Central telemetry ingestion

### 3.1 Durable acknowledgement boundary

ADR 0008 defines the telemetry measurement contract:

```text
MQTT QoS 1 delivery
        ↓
payload validation or dead-letter classification
        ↓
SQLite WAL spool transaction (`synchronous=FULL`)
        ↓
manual MQTT acknowledgement
        ↓
FIFO PostgreSQL persistence
        ↓
`event_id` insert or idempotent duplicate result
        ↓
delete local spool record
```

The local spool closes the previous loss window between broker acknowledgement and PostgreSQL commit.

When durable staging succeeds, the MQTT callback may acknowledge the QoS message even while PostgreSQL is unavailable because the payload is recoverable from local storage. When staging fails because of disk, capacity or integrity problems, the service leaves the message unacknowledged and retries with bounded backoff.

### 3.2 Storage and restart semantics

The spool uses:

- SQLite WAL;
- `synchronous=FULL`;
- a dedicated named Compose volume;
- strict local FIFO by spool record ID;
- unique telemetry `event_id` values;
- MQTT delivery-key deduplication with payload equality checks;
- pending, retry and terminal states;
- record and payload-byte capacity limits.

Pending records survive process and container recreation. PostgreSQL `event_id` idempotency makes replay safe if the PostgreSQL write succeeded but deleting the spool record did not.

Normal shutdown stops MQTT intake before the worker exits. Pending rows remain durable. Operational procedures must never use `docker compose down -v`.

### 3.3 Ordering boundary

The spool preserves local arrival order. MQTT reconnects, multiple edge publishers and network timing can produce bounded inter-node reordering before staging. Event time and node sequence fields remain the semantic ordering sources.

A failed oldest record blocks later records to preserve strict FIFO. Queue depth and oldest-pending-age metrics expose this condition.

### 3.4 Invalid payloads

Invalid UTF-8, JSON, object shape, size and schema payloads are committed as durable dead-letter work before MQTT acknowledgement. PostgreSQL outage or service restart therefore does not silently discard rejected input.

### 3.5 Scope exclusion

Issue #198 and ADR 0008 cover the telemetry measurement stream handled by `TelemetryIngestor`. Node health/status streams retain their existing persistence worker. Equivalent process-restart durability for those streams is not claimed by this Work Package.

## 4. Central application boundary

The FastAPI service owns:

- telemetry and dead-letter ingestion;
- PostgreSQL persistence through SQLAlchemy/Alembic;
- latest/history REST APIs;
- bounded WebSocket fan-out;
- sessions, stages, bindings, limits and audit records;
- refrigeration equipment, climate catalog and layout data;
- alert, report and node-management APIs;
- local MinIO integration;
- retention, health, readiness and metrics.

Data invariants:

- repeated telemetry `event_id` values are deduplicated;
- newest `captured_at` wins for latest state;
- migrations complete before readiness;
- PostgreSQL is internal in the standard central profile;
- MQTT, local spool, PostgreSQL, API and WebSocket failures remain independently diagnosable.

Readiness remains strict: PostgreSQL and the MQTT subscription must be ready. During PostgreSQL outage the service may safely stage telemetry while readiness returns `503`.

## 5. Metrics and failure visibility

The runtime exposes:

- spool readiness;
- pending and terminal records;
- retained payload bytes;
- oldest pending age;
- configured record/byte capacities;
- staged, recovered and replayed totals;
- capacity and spool-error totals;
- MQTT manual acknowledgements and acknowledgement failures;
- staging retries;
- PostgreSQL retries, outage timestamps and recovery totals.

Capacity or disk failure does not trigger destructive cleanup. The message remains unacknowledged and the incident is visible through metrics/logs.

## 6. Device Agent and hardware boundary

The Device Agent supports simulator, XJP60D, LE-01MP and combined read-only Modbus modes. It persists outbound telemetry in edge SQLite, publishes through MQTT QoS 1 and exposes health/readiness.

Hardware constraints:

- production serial paths use `/dev/serial/by-id/...`;
- no parallel Modbus master on one RTU bus;
- validated drivers use FC03 reads only;
- no Modbus write functions;
- no newly discovered endpoint enters continuous polling without explicit configuration/evidence.

Retained real-hardware evidence dated 2026-07-23 covers only:

- XJP60D `106-03` and `106-04`;
- LE-01MP `200–203`;
- 34 records per complete cycle;
- edge MQTT interruption, queue growth, reconnect and drain;
- Device Agent restart and simulator rollback;
- no established Modbus write, CRC or serial failure.

Broader topology, cumulative energy and extended XJP60D semantics remain Issues #200–#202.

## 7. MQTT and PostgreSQL

### Edge MQTT

The edge profile runs a local Mosquitto broker. Device acquisition and edge queuing continue while the central system is unavailable. Edge-to-central bridging is reversible and independently diagnosable.

### Central MQTT

The central profile runs Mosquitto with persistent storage. The durable Telemetry Service consumer uses a persistent MQTT v3 session and manual QoS acknowledgements for the telemetry stream.

Authentication and TLS profiles exist, but each actual environment requires evidence. Remote access is not part of the local runtime requirement.

### PostgreSQL

PostgreSQL remains the normalized telemetry and application source of truth. Standard central Compose:

- uses a named volume;
- does not expose PostgreSQL to the host;
- gates startup on database health and migrations;
- seeds the climate catalog idempotently.

The local spool is not a query database and does not replace PostgreSQL. It owns only work awaiting central persistence or operator review.

## 8. Local object storage

The Telemetry Service can disable object storage or use local S3-compatible MinIO. The standard central profile provides a private named-volume bucket and loopback host exposure. External S3 is optional and may not own the only copy of evidence.

## 9. Local infrastructure and persistent volumes

Central persistent state includes:

- Mosquitto data;
- PostgreSQL data;
- MinIO objects;
- Telemetry Service ingestion spool.

Edge persistent state includes MQTT persistence and the Device Agent SQLite outbox.

All update, rollback, backup and restore procedures must preserve named volumes unless a separately approved destructive operation is explicitly scoped.

## 10. Internet and cloud classification

### Local mandatory runtime

- local browser and dashboard;
- FastAPI Telemetry Service;
- local SQLite ingestion spool;
- PostgreSQL;
- Mosquitto;
- edge SQLite;
- read-only serial/Modbus libraries;
- MinIO when image workflows are enabled.

### Optional online

- GitHub/GitHub Actions;
- connected container registries;
- Supabase Auth;
- external OIDC/JWKS;
- Tailscale;
- external S3-compatible storage.

### Prohibited core dependencies

- mandatory CDN or remote fonts;
- mandatory cloud identity/database/message broker;
- hidden external telemetry;
- online licence checks;
- required paid APIs or storage.

## 11. Installation, update and rollback boundary

The runtime topology is local, but a clean checksummed disconnected OCI bundle is still Issue #187.

Images that predate ADR 0008 must not be used while the ingestion spool contains pending or terminal records. Rollback must preserve the spool volume and use a compatible image until records are drained or an explicit recovery/migration procedure is approved.

## 12. Backup and recovery boundary

Merged PR #144 verifies encrypted fresh-volume software recovery for PostgreSQL, MinIO and Mosquitto. The ingestion spool becomes an additional central persistent resource.

Issue #189 must extend recovery evidence to include:

- ingestion spool backup and replay;
- actual-host scheduling and off-host copies;
- update rollback with pending work;
- edge SQLite recovery;
- controlled host/power interruption;
- physical disk loss;
- measured production RPO/RTO.

Software CI for Issue #198 verifies the corrected process-restart path but does not prove actual-host power-loss or disk-loss recovery.

## 13. Implementation versus acceptance

| Area | Code/configuration | Software evidence | Remaining boundary |
| --- | --- | --- | --- |
| Frontend live states | Present | Unit/build/browser workflows | Site-specific browser/network evidence |
| Durable telemetry ingestion | Present in Issue #198 | Spool, duplicate, MQTT ACK, PostgreSQL outage/restart and container checks | Actual-host capacity, rollback, power/disk loss |
| Edge read-only acquisition | Present | Narrow 2026-07-23 hardware evidence | Full physical topology and device semantics |
| Sessions/reports/alerts/nodes | Present | Automated and browser workflows | Site recovery/offline acceptance |
| Production authentication | Partial | JWT/RBAC and optional adapters | Secure offline operator identity (#188) |
| Offline installation | Partial | Local topology | Clean disconnected bundle (#187) |
| Backup/restore | Partial | PR #144 software gate | Spool/edge/actual-host/power evidence (#189) |

## 14. Architectural decisions preserved

- Offline-first edge acquisition.
- Local PostgreSQL, MQTT and SQLite are first-class.
- MQTT acknowledgement never outruns the accepted local durability boundary.
- Modbus is read-only.
- Cloud functions are optional and isolated.
- Persistent data survives container recreation and rollback.
- Hardware and operational acceptance require actual evidence.
