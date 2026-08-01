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

## Final verification on main-updated head

Head `8e80b31b73b16d291747bfa5d6a5d54c0bd4d170` is `behind_by=0` and mergeable.

All 19 triggered workflows passed:

- general CI — `30696201793`;
- Telemetry Service — `30696201789`;
- Capacity Release Gate — `30696201784`;
- Observability — `30696201802`;
- Container Supply Chain — `30696201799`;
- Disaster Recovery Browser — `30696201783`;
- Disaster Recovery TLS Fleet — `30696201774`;
- Device Agent Fleet — `30696201787`;
- MQTT TLS Fleet — `30696201815`;
- MQTT Broker Security — `30696201788`;
- Broker Control — `30696201801`;
- Security Browser — `30696201772`;
- Authenticated Dashboard — `30696201767`;
- Alerts Browser — `30696201816`;
- Nodes Browser — `30696201785`;
- Refrigeration Browser — `30696201762`;
- Test Sessions Browser — `30696201773`;
- Reports Browser — `30696201822`;
- Rendered Reports Browser — `30696201770`.

The Capacity Gate proved outage readiness degradation, durable backlog, Telemetry Service/database recovery, replay, final drain and no-loss invariants. Telemetry Service passed the complete Python/PostgreSQL/MQTT/REST/WebSocket/object-storage suite, explicit PostgreSQL outage recovery, offline migration validation and container build. Observability passed policy, `promtool`, Alertmanager, production-like stack and Chromium dashboard acceptance. Supply Chain passed all three images, SBOMs, strict Trivy policy, manifests and aggregate evidence.

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

- #207 — durable central ingestion; all implementation-head workflows green, final state-head rerun pending.
- #192 — separate draft formatting inventory; not mixed into #207.

## Next action

Complete required checks on the final state-update head. If every required check remains green and review findings remain empty, mark PR #207 ready and perform a guarded squash merge. Then activate the next independent Ready Work Package.
