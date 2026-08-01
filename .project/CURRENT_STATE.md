# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `ee950e632702135231f1f4349e87529b39d16181`  
Active review: Issue #198 / PR #207  
Status confidence: high for repository and software-CI boundaries; partial for actual-host recovery and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed source-of-truth and security baseline

- PR #184 merged the AI Development Operating Standard.
- PR #190 merged the verified architecture and offline boundary.
- PR #206 reconciled stale Pull Requests, trackers and successor Issues.
- PR #209 merged Issue #208 as `ee950e632702135231f1f4349e87529b39d16181`.
- The historical Device Agent `pyasn1` result was not reproducible in the runtime, rootfs, exact-image target or production-equivalent Trivy sequence.
- Wrong scan target and sequential CycloneDX/SPDX contamination were ruled out.
- Strict HIGH/CRITICAL and stale-exception enforcement remains enabled; five obsolete Expat exceptions were removed.

## Issue #198 / PR #207 implementation

The durability Work Package is in final review on a branch updated from `main`.

Implemented operator outcome:

- MQTT telemetry is validated and committed to a local SQLite WAL spool before QoS 1 acknowledgement;
- SQLite uses `synchronous=FULL`;
- pending records survive Telemetry Service/container restart;
- replay is FIFO with PostgreSQL `event_id` idempotency;
- invalid telemetry is durably staged as dead-letter evidence before acknowledgement;
- capacity, disk, integrity and acknowledgement failures remain visible and do not silently drop records;
- backend and central Compose profiles use dedicated named spool volumes;
- Prometheus metrics and alerts cover readiness, pending depth/bytes, age, capacity, terminal records, I/O and ACK failures;
- rollback guidance preserves the spool volume and prohibits `docker compose down -v`.

Targeted gates already passed before the `main` update:

- Core Software Capacity — `30690434122`;
- Telemetry Service — `30690434121`;
- general CI — `30690434123`;
- Observability — `30690434103`;
- Backend Integration — `30690434125`;
- Offline Disaster Recovery — `30690434116`.

The branch now inherits PR #209 supply-chain hardening from `main`. All required workflows must rerun on the updated head before PR #207 can leave draft or merge.

## Evidence boundary

Software verified:

- local spool reopen, FIFO, deduplication, conflict, terminal and capacity behavior;
- manual MQTT acknowledgement boundary;
- PostgreSQL outage plus Telemetry Service restart replay;
- Compose named-volume topology;
- capacity, observability and recovery acceptance in GitHub CI.

Still unverified:

- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.

## Open Pull Requests

- #207 — durable central ingestion; updated from `main`, final checks pending.
- #192 — separate draft formatting inventory; not mixed into #207.

## Next action

Run all required workflows on the main-updated #207 head. If every required check is green and review findings remain empty, update the checkpoint, mark PR #207 ready and perform a guarded squash merge. Then activate the next independent Ready Work Package.
