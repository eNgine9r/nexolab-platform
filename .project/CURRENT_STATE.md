# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `8371ee59e76e64963405706be79fc4a909f9fac9`  
Status confidence: high for repository/code/configuration boundaries; partial for environment-specific operational acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Central data: local PostgreSQL
- Edge continuity: local SQLite outbox until MQTT broker acknowledgement
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

## Confirmed telemetry durability boundary

The Device Agent removes an edge SQLite row after the configured MQTT broker returns a QoS 1 acknowledgement. The central consumer then submits the payload to a bounded in-memory persistence queue before PostgreSQL commit.

Therefore, the current pipeline does not provide end-to-end durability after broker acknowledgement. A Telemetry Service termination during a PostgreSQL outage can lose an acknowledged payload that is no longer present at the edge. Issue #198 owns the durable local staging/replay correction. Until it is implemented and evidenced, operators must avoid restarting the Telemetry Service during PostgreSQL outages.

## Implementation and acceptance boundary

### Repository-backed implementation

- Next.js live dashboard with explicit demo/live and stale/offline/error states.
- FastAPI ingestion, PostgreSQL persistence, REST, WebSocket, retention and metrics.
- Sessions, attribution, audit, alerts, reports, nodes, refrigeration equipment and KK1/KK2 catalog code.
- Local Mosquitto, PostgreSQL and MinIO Compose topology.
- Device Agent with simulator and read-only Modbus modes.
- Edge SQLite outbox and MQTT QoS 1 delivery to the broker boundary.
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

This evidence is limited to that scope and does not close the central durability gap.

### Not yet accepted as complete

- end-to-end durable MQTT-to-PostgreSQL handoff across PostgreSQL outage and Telemetry Service restart;
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
- Issue #183 is the active reconciliation Work Package in PR #190.
- Issue #198 records the confirmed MQTT-to-PostgreSQL durability gap discovered during PR #190 review.
- Issue #185 remains a separate formatting-only track; child Issue #191 is represented by draft PR #192.
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
- NEXOLAB-186 / Issue #186 — Queued; activate only after PR #190 merges and #183 is marked Done.
- NEXOLAB-198 / Issue #198 — Queued for classification and sequencing by #186; high-priority data-integrity risk.
- NEXOLAB-187 / Issue #187 — Queued after source-of-truth cleanup.
- NEXOLAB-188 / Issue #188 — Queued after source-of-truth cleanup.
- NEXOLAB-189 / Issue #189 — Blocked for final evidence on controlled hosts and depends on the durability correction.
- NEXOLAB-185 / Issue #185 — Separate maintenance track in progress through #191 / PR #192.

## Next action

Resolve PR #190 review findings and require final CI to pass. After squash merge, execute Issue #186 in a new branch, mark #183 Done, and classify Issue #198 before resuming PR #175 or starting another product feature.
