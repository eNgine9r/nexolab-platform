# NEXOLAB verified architecture baseline

**Baseline date:** 2026-07-31  
**Verified `main`:** `8371ee59e76e64963405706be79fc4a909f9fac9`  
**Project profile:** `LOCAL_LAN`

This document replaces the earlier fixture-only frontend description. It records the architecture that is present in code and runtime configuration. A component is marked operationally accepted only where repository evidence exists; code, documentation and a closed Issue are not substitutes for real-host or real-device evidence.

## 1. System boundary

```text
Local operator browser
        │
        │ HTTP / WebSocket on the trusted LAN
        ▼
Next.js dashboard
        │
        │ typed REST and WebSocket contracts
        ▼
FastAPI Telemetry Service
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

The browser, dashboard, API, MQTT, PostgreSQL, object storage and edge acquisition path can be hosted entirely inside the local network. Internet connectivity is not part of the core data path.

## 2. Frontend

### Verified implementation

- Next.js 16 App Router, React 19, TypeScript and Tailwind CSS.
- Explicit `demo` and `live` modes.
- Typed REST and WebSocket clients with runtime payload validation.
- Feature modules for telemetry, sessions, alerts, reports, nodes, security and refrigeration workflows.
- Explicit live connection states; stale or unavailable data must not be relabeled as live.
- Demo data is isolated and must not silently replace a failed live path.
- Root layout uses local CSS and system fonts; no remote font loader is configured.
- No mandatory CDN, analytics SDK or external browser telemetry was found in the inspected frontend configuration.

### Runtime boundary

The dashboard requires only a reachable local API/WebSocket origin in live mode. Its example configuration points to local addresses. Browser access through Tailscale or another tunnel is an optional remote-access layer, not a core runtime dependency.

### Authentication boundary

The frontend contains:

- an optional Supabase Auth adapter;
- an acceptance-only credential provider;
- a generic bearer-token integration with the backend.

When Supabase variables are absent, no Supabase client is created. This keeps Supabase optional, but a secure production operator login that is fully local and offline has not yet been accepted. `AUTH_MODE=disabled` is not a production security solution. The remaining decision and acceptance work is tracked in Issue #188.

## 3. Telemetry Service

### Verified implementation

The FastAPI service owns the central application and telemetry boundary:

- MQTT ingestion;
- schema and payload validation;
- PostgreSQL persistence through SQLAlchemy and Alembic;
- latest/history REST APIs;
- bounded WebSocket fan-out;
- sessions, stages, bindings, limits and audit records;
- refrigeration equipment, climate catalog and layout data;
- alert, report and node-management APIs;
- local S3-compatible object storage integration;
- retention, health, readiness and metrics.

### Data invariants

Repository rules and code preserve these invariants:

- repeated telemetry `event_id` values are deduplicated;
- the newest `captured_at` wins when selecting latest state;
- migrations complete before application readiness;
- stale values are represented explicitly;
- PostgreSQL is not published to the host by the standard central Compose profile;
- MQTT, PostgreSQL, API and WebSocket failures remain separately diagnosable.

### Central outage and durability limitation

The edge SQLite outbox guarantees local persistence only until the configured MQTT broker acknowledges the QoS 1 publish. After that acknowledgement, the Device Agent deletes the edge row. The central MQTT consumer then submits the payload to a bounded in-memory persistence queue, and PostgreSQL durability occurs later.

Consequently, if PostgreSQL is unavailable and the Telemetry Service terminates after broker delivery but before database commit, the acknowledged payload can be lost: it is no longer present in the edge SQLite outbox and the central queue is not durable. The current contract is at-least-once delivery to the MQTT boundary, not end-to-end durability in PostgreSQL. Operators must avoid terminating the Telemetry Service during a PostgreSQL outage. Issue #198 owns the durable central staging/replay correction; Issue #189 must include the resulting restart and recovery evidence.

## 4. Device Agent and hardware boundary

### Verified implementation

The Device Agent supports:

- `simulator`, `xjp60d`, `le01mp` and combined `modbus` modes;
- sequential read-only polling through one serial client;
- SQLite `outbound_queue` persistence with unique `event_id`;
- MQTT QoS 1 publication and retry;
- node health/status streams;
- HTTP health/readiness;
- mounted MQTT credentials and optional local TLS;
- stable stream sequence allocation.

### Hardware safety

Production hardware mode is opt-in through `compose.hardware.yaml`.

The hardware contract requires:

- a host path under `/dev/serial/by-id/...`;
- no parallel Modbus master on the same bus;
- FC03 read operations only for the validated drivers;
- one 16-bit register per request;
- no Modbus write functions;
- no automatic promotion of newly discovered devices into continuous polling.

### Verified narrow hardware scope

Repository evidence dated 2026-07-23 records a controlled smoke and soak for:

- XJP60D `106-03` and `106-04`;
- LE-01MP units `200`, `201`, `202`, `203`;
- 34 records per complete cycle;
- MQTT interruption, edge SQLite queue growth, reconnect and drain;
- Device Agent restart;
- rollback to simulator;
- no established CRC, serial or Modbus errors;
- no Modbus writes.

This evidence does not prove every XJP60D channel, cumulative-energy register, all future buses, long-duration site operation or power-loss recovery. LE-01MP register `7` remains excluded pending scale and rollover validation.

## 5. MQTT and PostgreSQL

### Edge MQTT

The edge profile runs a local Mosquitto broker bound to loopback. The Device Agent publishes locally, allowing acquisition and queuing to continue while the central system is unavailable. Edge-to-central bridging is a separate, reversible operation.

### Central MQTT

The central profile runs Mosquitto with persistent storage. Authentication and TLS profiles exist, but their actual deployment state must be evidenced per environment. Remote access is not required for the local data path.

### PostgreSQL

PostgreSQL 16 is the central source of truth for normalized telemetry and application domains. The standard central profile:

- uses a named volume;
- does not publish the database port to the host;
- gates the API on database health and migrations;
- runs an idempotent climate-catalog seed after migration.

## 6. Local object storage

The Telemetry Service can disable object storage or use S3-compatible storage. The standard central profile uses local MinIO with:

- a named volume;
- a private bucket;
- loopback host binding by default;
- locally generated signed URLs.

External S3 services are not required. Remote signed-URL delivery through Tailscale or another trusted proxy is optional.

## 7. Local infrastructure and network exposure

The inspected central Compose profile contains local Mosquitto, PostgreSQL, MinIO, migration and Telemetry Service containers. Default host exposure is limited to loopback for MQTT, API and MinIO; PostgreSQL remains internal.

The inspected edge profile contains local Mosquitto, Device Agent, MQTT persistence and edge SQLite persistence. Hardware access is absent until the explicit override is applied.

Named volumes are part of the rollback contract. Operational procedures must not use `docker compose down -v`.

## 8. Internet and cloud classification

### Local and mandatory at runtime

- local browser;
- Next.js dashboard runtime;
- FastAPI Telemetry Service;
- PostgreSQL;
- Mosquitto;
- edge SQLite;
- serial/Modbus libraries;
- MinIO when image-backed workflows are enabled;
- Docker/Compose or an equivalent packaged local runtime.

### Optional online

- GitHub and GitHub Actions;
- GHCR/Docker Hub during connected installation;
- Supabase Auth;
- external OIDC/JWKS;
- Tailscale remote access;
- external S3-compatible storage.

Optional services must have an explicit disabled/offline state and may not own the only copy of laboratory data.

### Development-only network access

- npm and PyPI dependency installation;
- upstream container registries;
- security advisory and dependency metadata;
- CI artifact publication.

### Prohibited for core runtime

- mandatory CDN assets or remote fonts;
- mandatory cloud authentication;
- hidden external telemetry;
- online license checks;
- required paid APIs or storage;
- a cloud-only database or message broker.

## 9. Installation, update and rollback boundary

The runtime topology is local, but the current installation path is not yet independently offline-complete:

- Compose files reference images from GHCR and Docker Hub by default;
- source builds require npm/PyPI dependencies unless already cached;
- no versioned, checksummed OCI image bundle has been accepted on a clean disconnected host.

Issue #187 owns the offline bundle, disconnected installation, update and rollback proof.

## 10. Backup and recovery boundary

The repository contains runbooks and scripts for:

- PostgreSQL logical backup;
- isolated restore drills;
- service restart;
- MQTT and PostgreSQL outage diagnosis;
- edge-to-central rollback;
- preservation of named volumes.

The narrow edge MQTT outage/restart drill has evidence. A single current acceptance package covering PostgreSQL, MinIO, MQTT, edge SQLite, host reboot, version rollback and power interruption has not been verified in this reconciliation. The current MQTT-to-PostgreSQL handoff also has a confirmed non-durable loss window until Issue #198 is implemented. Issue #189 owns the consolidated recovery evidence after that durability boundary is corrected.

## 11. Implementation versus acceptance

| Area                                                | Code/configuration present | Repository evidence                                               | Current boundary                                                                                        |
| --------------------------------------------------- | -------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Frontend live adapter and explicit states           | Yes                        | Unit/build/browser tooling exists                                 | Current CI must validate each change; actual site browser state is environment-specific                 |
| Telemetry ingestion, REST, WebSocket and PostgreSQL | Yes                        | Automated tests and operations tooling exist                      | Known MQTT-to-PostgreSQL durability gap is tracked in #198; controlled-host evidence remains incomplete |
| Edge SQLite, MQTT and read-only Modbus drivers      | Yes                        | 2026-07-23 smoke and soak evidence for 34-series scope            | Accepted only for that narrow scope; broader hardware remains unverified                                |
| Laboratory sessions                                 | Yes                        | Issue #82 is closed and a real-hardware acceptance harness exists | Parent tracker #74 is stale and must be reconciled                                                      |
| Refrigeration/climate catalog                       | Yes                        | Merged implementation and automated acceptance claims exist       | Open PR #175 contains a current live/availability defect and is non-mergeable                           |
| Reports, alerts and node management                 | Yes                        | Code and browser acceptance tooling exist                         | Not a substitute for site recovery/offline acceptance                                                   |
| Production authentication                           | Partial                    | JWT/RBAC code and optional Supabase adapter exist                 | Secure offline operator login is not accepted                                                           |
| Offline installation                                | Partial                    | Local topology exists                                             | Clean disconnected installation bundle is missing                                                       |
| Backup/restore/rollback                             | Partial                    | Procedures and focused scripts exist                              | Full current-host acceptance package is missing                                                         |
| Power-loss recovery                                 | Partial                    | Restart handling exists                                           | Controlled power-loss evidence is missing                                                               |

## 12. Architectural decisions preserved

- Offline-first edge acquisition.
- Local PostgreSQL, local MQTT and edge SQLite are first-class.
- Modbus is read-only.
- One Issue maps to one branch and one focused Pull Request.
- Cloud functionality is optional and isolated.
- Persistent data survives container recreation and rollback.
- Hardware and operational acceptance require actual evidence.
