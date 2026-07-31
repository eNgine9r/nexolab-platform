# NEXOLAB Current State

Updated: 2026-07-31  
Verified baseline: `main` at `8371ee59e76e64963405706be79fc4a909f9fac9`  
Status confidence: high for repository/code/configuration boundaries; partial for environment-specific operational acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Central data: local PostgreSQL
- Edge continuity: local SQLite outbox
- Device transport: read-only Modbus RTU and MQTT QoS 1
- User interface: local Next.js web application
- Local object storage: MinIO when image workflows are enabled
- Optional online layers: Supabase Auth, external OIDC/JWKS, Tailscale, registries and CI

## Verified architecture

The current local data path is:

```text
XJP60D / LE-01MP
        ↓ read-only Modbus RTU
Device Agent + edge SQLite
        ↓ local MQTT / MQTT QoS 1
Central Mosquitto
        ↓
FastAPI Telemetry Service
        ↓
PostgreSQL + local MinIO
        ↓ REST / WebSocket
Next.js dashboard
```

The frontend is no longer fixture-only. It contains live REST/WebSocket integrations and feature workflows for telemetry, sessions, alerts, reports, nodes, security and refrigeration. `docs/architecture.md` has been replaced with the verified current boundary.

## Implementation and acceptance boundary

### Repository-backed implementation

- Next.js live dashboard with explicit demo/live and stale/offline/error states.
- FastAPI ingestion, PostgreSQL persistence, REST, WebSocket, retention and metrics.
- Sessions, attribution, audit, alerts, reports, nodes, refrigeration equipment and KK1/KK2 catalog code.
- Local Mosquitto, PostgreSQL and MinIO Compose topology.
- Device Agent with simulator and read-only Modbus modes.
- Edge SQLite outbox and MQTT QoS 1 delivery.
- Backup, restore, cutover and rollback procedures/tooling.

### Real evidence available

A controlled 2026-07-23 hardware smoke and soak covers:

- XJP60D `106-03` and `106-04`;
- LE-01MP units `200–203`;
- 34 records per complete cycle;
- edge MQTT interruption;
- SQLite queue growth, reconnect and drain;
- Device Agent restart;
- rollback to simulator;
- no established Modbus write, CRC or serial failure.

This evidence is limited to that scope.

### Not yet accepted as complete

- clean disconnected installation from a local bundle;
- disconnected update and rollback package;
- secure production operator login without Supabase/external identity dependency;
- consolidated PostgreSQL, MinIO, MQTT and edge backup/restore evidence;
- current controlled central-host restart and rollback package;
- approved power-loss recovery;
- all historical XJP60D channels/register semantics and cumulative energy;
- production/site cutover for any unverified environment.

## GitHub state

- PR #184 was squash-merged into `main` as `8371ee59e76e64963405706be79fc4a909f9fac9`.
- Issue #183 is the active reconciliation Work Package.
- Issue #185 remains a separate formatting-only track.
- Issues #186–#189 define the next source-of-truth, offline installation, authentication and recovery outcomes.
- PR #175 is a current defect branch but is draft and non-mergeable.
- PRs #53, #109 and #111 are old non-mergeable branches requiring supersession/unique-diff review.
- Tracking Issue #74 is stale because child Issue #82 is closed while still shown active.
- Legacy M1 Issues #11–#18 mix already implemented narrow scope with residual hardware gaps.

## Current Sprint outcome

Publish a verified architecture, offline-readiness and roadmap baseline before resuming product work.

### Work Package status

- NEXOLAB-182 / Issue #182 — Done through PR #184.
- NEXOLAB-183 / Issue #183 — In review on `docs/183-architecture-reconciliation`.
- NEXOLAB-186 / Issue #186 — Ready next.
- NEXOLAB-187 / Issue #187 — Ready after source-of-truth cleanup.
- NEXOLAB-188 / Issue #188 — Ready for architecture/discovery.
- NEXOLAB-189 / Issue #189 — Preparation Ready; final evidence requires controlled hosts.
- NEXOLAB-185 / Issue #185 — Separate maintenance track.

## Next action

Complete review and CI for Issue #183. After merge, execute Issue #186 to reconcile stale trackers and superseded PRs before continuing PR #175 or starting another product feature.
