# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `5851955ea9a38a9068bbab1eb0c9701722c028c5`  
Next Ready Work Package: Issue #199  
Status confidence: high for repository and software-CI boundaries; partial for actual-host recovery and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed baseline

- PR #184 merged the AI Development Operating Standard.
- PR #190 merged the verified architecture and offline boundary.
- PR #206 reconciled stale Pull Requests, trackers and successor Issues.
- PR #209 hardened Device Agent supply-chain evidence and merged as `ee950e632702135231f1f4349e87529b39d16181`.
- PR #207 completed durable central telemetry ingestion and merged as `5851955ea9a38a9068bbab1eb0c9701722c028c5`.

## Issue #198 completed outcome

Telemetry accepted from MQTT is now committed to a local SQLite WAL spool before QoS 1 acknowledgement.

Implemented behavior:

- SQLite WAL with `synchronous=FULL`;
- manual MQTT acknowledgement only after durable staging;
- persistent MQTT session in durable mode;
- FIFO replay with PostgreSQL `event_id` idempotency;
- durable dead-letter staging before acknowledgement;
- record and byte capacity with visible capacity, I/O, integrity and ACK failures;
- pending, bytes, age, replay, terminal and acknowledgement metrics;
- dedicated named spool volumes for central and backend profiles;
- Prometheus and Alertmanager coverage for spool health;
- rollback-safe operations that preserve the spool volume.

## Final verification

Final PR head `0bbb7a2e0e50c8cab3371c8f80266772304f96c1` passed all 19 triggered workflows:

- CI — `30696463171`;
- Telemetry Service — `30696463209`;
- Capacity Release Gate — `30696463199`;
- Observability — `30696463210`;
- Container Supply Chain — `30696463203`;
- Disaster Recovery Browser — `30696463198`;
- Disaster Recovery TLS Fleet — `30696463172`;
- Device Agent Fleet — `30696463202`;
- MQTT TLS Fleet — `30696463177`;
- MQTT Broker Security — `30696463169`;
- Broker Control — `30696463195`;
- Security Browser — `30696463200`;
- Authenticated Dashboard — `30696463186`;
- Alerts Browser — `30696463190`;
- Nodes Browser — `30696463205`;
- Refrigeration Browser — `30696463192`;
- Test Sessions Browser — `30696463180`;
- Reports Browser — `30696463187`;
- Rendered Reports Browser — `30696463196`.

The Capacity Gate proved outage readiness degradation, durable backlog, Telemetry Service/database recovery, replay, final zero backlog and no-loss invariants. Telemetry Service passed the complete Python/PostgreSQL/MQTT/REST/WebSocket/object-storage suite, explicit PostgreSQL outage recovery, offline migration validation and container build. Observability passed policy, `promtool`, Alertmanager, production-like recovery and Chromium acceptance. Supply Chain passed all three images, SBOMs, strict Trivy policy, manifests and aggregate evidence.

## Evidence boundary

Software verified:

- spool reopen, FIFO, deduplication, conflict, terminal and capacity behavior;
- manual MQTT acknowledgement boundary;
- PostgreSQL outage plus Telemetry Service restart replay;
- Compose named-volume topology;
- capacity, observability, security and recovery acceptance in CI.

Still unverified:

- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.

## Open Pull Requests

- #192 — separate draft formatting inventory; not mixed into completed durability work.

## Next Ready Work Package

Issue #199 — stabilize live telemetry WebSocket lifecycle and operator states. Start from current `main` in a dedicated feature branch and focused Pull Request; historical PR #175 is reference-only.
