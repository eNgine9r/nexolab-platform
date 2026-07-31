# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `01f2a5fcfc929127d4a7b3d9c068944cd65d8636`  
Status confidence: high for repository and GitHub boundaries; partial for environment-specific operational and hardware acceptance.

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

## Verified architecture and evidence boundary

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

Implemented and repository-backed:

- live Next.js REST/WebSocket workflows;
- FastAPI ingestion, PostgreSQL, sessions, alerts, reports, nodes and refrigeration domains;
- local Mosquitto, PostgreSQL and MinIO Compose topology;
- read-only XJP60D and LE-01MP Device Agent drivers;
- edge SQLite outbox and MQTT QoS 1 delivery to the broker boundary;
- encrypted fresh-volume central software disaster recovery from merged PR #144.

Actual hardware evidence remains limited to the 2026-07-23 pilot scope:

- XJP60D `106-03` and `106-04`;
- LE-01MP units `200–203`;
- 34 records per complete cycle;
- edge MQTT outage, SQLite queue growth, reconnect and drain;
- Device Agent restart and rollback to simulator;
- no established Modbus write, CRC or serial failure.

## Confirmed data-integrity gap

The Device Agent removes an edge SQLite row after the configured MQTT broker returns a QoS 1 acknowledgement. The central consumer then submits the payload to a bounded in-memory persistence queue before PostgreSQL commit.

A Telemetry Service termination during PostgreSQL outage can therefore lose an acknowledged payload that is no longer present at the edge. Issue #198 is the highest-priority next Work Package and owns durable local central staging/replay.

## GitHub source of truth

### Completed reconciliation

- PR #184 merged the operating standard as `8371ee59e76e64963405706be79fc4a909f9fac9`.
- PR #190 merged Issue #183 as `01f2a5fcfc929127d4a7b3d9c068944cd65d8636`.
- M4 tracker #74 now matches closed child #82 and is closed with a scoped completion boundary.
- Refrigeration foundation Issue #94 is closed because current `main` contains and surpasses its image-backed editor outcome.
- Historical M1 Issues #11–#15 and tracker #18 are closed as superseded, not falsely completed.
- Issue #16 remains completed as the evidence standard.
- Issue #17 remains open as the versioned-profile consolidation gate.

### Closed superseded Pull Requests

- #53 — obsolete fixture-era central deployment/client branch;
- #109 — stale Tailscale branch; optional outcome remains in blocked Issue #108;
- #111 — obsolete parallel auth/RBAC branch; offline identity remains #188;
- #175 — mixed stale defect branch; focused WebSocket outcome is #199;
- #159 — grouped production dependencies; focused maintenance owner is #203;
- #160 — grouped major toolchain migrations; owner is #204;
- #1 and #2 — independent action v7 bot branches; combined compatibility owner is #205.

### Open Pull Requests

- PR #206 is the active, non-draft source-of-truth reconciliation PR for Issue #186. Its final diff is limited to project state and roadmap files and must pass CI/review before squash merge.
- PR #192 is the only other open PR. It is a valid draft formatting-inventory Work Package under #191/#185. It must remain draft until updated or recreated from the post-#186 `main` baseline with mandatory project-state/checkpoint changes and fresh green CI.

## Residual Work Packages created by Issue #186

- #199 — live telemetry WebSocket lifecycle and operator states;
- #200 — physical RS-485 topology and safe polling envelope;
- #201 — LE-01MP cumulative energy, scale and rollover;
- #202 — extended XJP60D semantics and firmware portability;
- #203 — staged production dependency updates;
- #204 — separated major frontend toolchain migrations;
- #205 — GitHub Actions v7 compatibility and least-privilege proof.

## Current Work Package status

- NEXOLAB-182 / #182 — Done through PR #184.
- NEXOLAB-183 / #183 — Done through PR #190.
- NEXOLAB-186 / #186 — In review in PR #206 on `chore/186-source-of-truth-reconciliation`.
- NEXOLAB-198 / #198 — Ready as the next primary data-integrity Work Package; dependency #186 prevents execution before merge.
- NEXOLAB-199 / #199 — Queued focused live-connection defect after #186.
- NEXOLAB-187 / #187 — Queued offline installation/update bundle.
- NEXOLAB-188 / #188 — Queued offline operator authentication.
- NEXOLAB-189 / #189 — Blocked for final controlled-host/Raspberry Pi evidence and depends on #198/#187/#188.
- NEXOLAB-200–202 — Blocked on controlled read-only hardware evidence.
- NEXOLAB-17 — Blocked on #200–#202.
- NEXOLAB-185/#191/PR #192 — Separate maintenance track, draft pending post-#186 rebase/update.
- NEXOLAB-203–205 — Queued maintenance work, not mixed into product/data-integrity PRs.

## Not yet accepted as complete

- end-to-end durable MQTT-to-PostgreSQL handoff across PostgreSQL outage and Telemetry Service restart;
- clean disconnected installation/update bundle;
- secure fully local production operator login;
- actual-host backup scheduling, encrypted off-host copies and measured production RPO/RTO;
- edge/central power-loss recovery;
- full RS-485 topology and firmware portability;
- LE-01MP cumulative energy;
- XJP60D setpoint/input/output and extended alarm semantics;
- optional Tailscale actual-host/operator-workstation acceptance;
- production/site cutover.

## Next action

Require PR #206 to pass changed-file formatting, ESLint, strict typecheck, Vitest, production build and review. After squash merge, mark #186 Done and start Issue #198 from current `main` as the next primary Work Package. Keep PR #192 and all maintenance/hardware work separate.
