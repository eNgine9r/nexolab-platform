# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `bd286690f94bdf06adf3fc630bdee69c5019ebce`  
Active implementation: Issue #208 / draft PR #209  
Related review: Issue #198 / draft PR #207  
Status confidence: high for repository and software-CI boundaries; partial for actual-host recovery and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed source-of-truth baseline

- PR #184 merged the AI Development Operating Standard.
- PR #190 merged the verified architecture and offline boundary.
- PR #206 merged Issue #186 as `bd286690f94bdf06adf3fc630bdee69c5019ebce`.
- stale Pull Requests and trackers have focused successor Issues.

## Issue #198 / PR #207 status

The durable MQTT-to-PostgreSQL implementation is in review.

Verified targeted outcomes include:

- local SQLite WAL spool with `synchronous=FULL`;
- manual MQTT QoS acknowledgement only after local durable commit;
- persistent MQTT session;
- FIFO replay and `event_id` idempotency;
- capacity, terminal, replay and acknowledgement metrics;
- backend/central named volumes;
- PostgreSQL outage plus Telemetry Service restart recovery;
- updated capacity, observability and recovery acceptance.

Latest #198-specific gates are green:

- Core Software Capacity — run `30690434122`;
- Telemetry Service — run `30690434121`;
- general CI — run `30690434123`;
- Observability — run `30690434103`;
- Backend Integration — run `30690434125`;
- Offline Disaster Recovery — run `30690434116`.

PR #207 is not merged because its aggregate Container Supply Chain run exposed an independent Device Agent evidence anomaly. The telemetry-service image, SBOM, Trivy result and immutable manifest were green.

## Issue #208 / PR #209

The original supply-chain run reported `pyasn1 0.6.2` / CVE-2026-33230 for Device Agent.

Focused diagnostics proved:

- Device Agent requirements contain only `paho-mqtt==2.1.0` and `pyserial==3.5`;
- `pyasn1` is not importable from the runtime;
- exported final rootfs contains no `pyasn1` file, dpkg stanza or nested archive;
- a plain exact Trivy scan is clean;
- current GHA-cached and `pull: true` Buildx images are byte-identical and both Trivy-clean.

The finding is therefore classified as stale/transient image or scan provenance, not an application dependency.

PR #209 now implements the narrow remediation:

- exact-commit evidence builds use `pull: true`;
- multi-platform publish builds use `pull: true`;
- only Device Agent moves to `supply-chain-v2-device-agent` cache scope;
- unrelated image cache scopes remain unchanged;
- a regression test enforces the provenance contract;
- the temporary diagnostic workflow is removed;
- no dependency, runtime or hardware code changes are included.

## Open Pull Requests

- #209 — active focused security-maintenance PR for #208.
- #207 — durable central-ingestion PR, review-blocked until the aggregate supply-chain gate reruns from updated `main`.
- #192 — separate draft formatting inventory; not mixed into either active Work Package.

## Evidence boundary

Not claimed by #208:

- changes to Device Agent runtime packages;
- new Raspberry Pi or Modbus hardware evidence;
- production image publication;
- production/site deployment;
- actual-host power-loss, rollback or disk-loss recovery.

## Next action

Require PR #209 to pass changed-file formatting, policy regression tests, Device Agent checks and the complete Container Supply Chain workflow. Resolve all review findings and squash-merge. Then update PR #207 from `main`, rerun its final aggregate Gate, update the #198 checkpoint and merge only when all required checks are green.
