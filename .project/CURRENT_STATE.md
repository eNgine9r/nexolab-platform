# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `bd286690f94bdf06adf3fc630bdee69c5019ebce`  
Active branch: `feat/198-durable-central-ingestion`  
Active Pull Request: #207  
Status confidence: high for repository and software-CI boundaries; partial for actual-host recovery and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Central data: local PostgreSQL
- Edge continuity: local SQLite outbox until MQTT acknowledgement
- Central continuity under implementation: local SQLite ingestion spool until PostgreSQL commit
- Device transport: read-only Modbus RTU and MQTT QoS 1
- User interface: local Next.js web application
- Local object storage: MinIO when image workflows are enabled
- Optional online layers: Supabase Auth, external OIDC/JWKS, Tailscale, registries and CI

## Verified source-of-truth baseline

Completed reconciliation:

- PR #184 merged the AI Development Operating Standard.
- PR #190 merged the verified architecture/offline baseline.
- PR #206 merged Issue #186 as `bd286690f94bdf06adf3fc630bdee69c5019ebce`.
- stale milestone trackers and superseded PRs are classified with focused successor Issues;
- Issue #198 is the active primary data-integrity Work Package;
- draft formatting PR #192 remains a separate maintenance track.

## Active data-integrity Work Package

Issue #198 / draft PR #207 corrects the previous MQTT-to-PostgreSQL loss window.

Previous path:

```text
edge SQLite
  → MQTT broker QoS 1 acknowledgement
  → edge row deletion
  → central in-memory queue
  → PostgreSQL
```

A Telemetry Service termination during PostgreSQL outage could lose already acknowledged telemetry.

Selected path, recorded in ADR 0008:

```text
MQTT QoS 1 delivery
  → validate/classify
  → local SQLite WAL spool (`synchronous=FULL`)
  → manual MQTT acknowledgement
  → FIFO PostgreSQL replay
  → idempotent `event_id` result
  → spool-row deletion
```

## Scope implemented in PR #207

- local SQLite durable ingestion spool;
- WAL/FULL durability settings;
- strict FIFO pending order;
- telemetry and dead-letter staging;
- `event_id` and MQTT delivery-key deduplication;
- payload-conflict detection;
- record and byte capacity limits;
- retry metadata and terminal quarantine;
- process/container restart replay;
- manual MQTT QoS acknowledgement after local durable commit;
- persistent MQTT v3 consumer session in durable mode;
- named spool volumes in backend and central Compose profiles;
- writable non-root container directory;
- spool/acknowledgement health and metrics;
- unit, idempotency, manual-ACK and PostgreSQL-outage restart tests;
- ADR, architecture and operations runbook updates.

## Current verification evidence

On the first PR #207 implementation head:

- changed-file formatting — passed;
- ESLint — passed;
- strict TypeScript typecheck — passed;
- Vitest — passed;
- Next.js production build — passed;
- Telemetry Service compile — passed;
- central Compose/recovery contract validation — passed;
- PostgreSQL migrations — passed;
- Python telemetry test suite — passed;
- PostgreSQL outage/restart tests — passed;
- offline migration SQL — passed.

That Telemetry Service run was superseded by later documentation/state commits while its container build was executing, so the final-head container build and full required workflows remain pending.

Targeted local software smoke evidence also covers:

- SQLite reopen and FIFO persistence;
- duplicate key/payload conflict handling;
- capacity and terminal records;
- simulated process restart with pending telemetry;
- replay after database recovery.

## Explicit evidence boundary

Not yet claimed:

- final green CI on the latest PR #207 head;
- actual central-host restart with the named spool volume;
- rollback with pending spool records;
- disk-full behavior on a real filesystem;
- abrupt host power interruption;
- physical disk-loss recovery;
- long-duration capacity/throughput acceptance;
- equivalent process-restart durability for node health/status streams;
- any new Raspberry Pi or Modbus hardware acceptance.

## Existing hardware evidence

Retained 2026-07-23 evidence remains limited to:

- XJP60D `106-03` and `106-04`;
- LE-01MP `200–203`;
- 34 records per complete polling cycle;
- edge MQTT outage, SQLite growth, reconnect and drain;
- Device Agent restart and simulator rollback;
- no established Modbus write, CRC or serial failure.

## Open Pull Requests

- #207 — active draft durable-ingestion Work Package for #198.
- #192 — separate draft formatting inventory under #191/#185; it must not be mixed into #207.

## Ordered next work

1. Finish final-head CI, review and merge for #198 / PR #207.
2. Start #199 from the new `main`: live WebSocket lifecycle and operator states.
3. Continue #187: verified offline installation/update bundle.
4. Continue #188: secure offline operator authentication.
5. Complete #189 only with controlled host/Raspberry Pi recovery evidence.

Maintenance and hardware tracks remain separate:

- #200–#202 and #17 — read-only hardware evidence/profile consolidation;
- #185/#191/#192 — formatting baseline;
- #203–#205 — focused dependency/toolchain/Actions maintenance.

## Next action

Require all latest-head PR #207 workflows to complete successfully. Address any Python, Compose, container, review or recovery findings. Then update the checkpoint with exact run IDs, move the PR out of draft, verify mergeability and squash-merge only with all required checks green and review threads resolved.
