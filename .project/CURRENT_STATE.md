# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `bd286690f94bdf06adf3fc630bdee69c5019ebce`  
Active review: Issue #208 / PR #209  
Related review: Issue #198 / PR #207  
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
- Stale Pull Requests and trackers have focused successor Issues.

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

PR #207 remains unmerged until Issue #208 / PR #209 is integrated into `main` and its aggregate Container Supply Chain gate is rerun.

## Issue #208 / PR #209 verified outcome

The initial supply-chain run associated with PR #207 reported `pyasn1 0.6.2` / CVE-2026-33230 for Device Agent.

Focused diagnostics and repeated production-equivalent runs proved:

- Device Agent requirements contain only `paho-mqtt==2.1.0` and `pyserial==3.5`;
- `pyasn1` is not importable and is absent from Python package metadata, exported runtime rootfs and Debian package metadata;
- the workflow scans the exact locally built Device Agent image with matching OCI revision and digest;
- CycloneDX and SPDX invocations disable vulnerability scanning and cannot contaminate the later JSON vulnerability report;
- repeated JSON scans using the shared Trivy cache did not reproduce `pyasn1`;
- the only reproducible blocker was strict stale-exception enforcement for five obsolete `libexpat1` decisions.

The historical `pyasn1` result is classified as a non-reproducible scanner/advisory-state event. Wrong image target and sequential SBOM contamination are ruled out. No runtime dependency or waiver was added.

PR #209 now:

- uses `pull: true` for exact-commit evidence and multi-platform publish builds;
- moves only Device Agent to `supply-chain-v2-device-agent` cache scope;
- preserves unrelated image cache scopes;
- retains strict HIGH/CRITICAL and stale-exception enforcement;
- emits target, class/type, package path, layer digest and data source for policy findings;
- removes five stale `libexpat1` exceptions while preserving active decisions;
- includes regression tests for Buildx and Trivy provenance;
- contains no temporary diagnostic workflow.

Final-head verification for `0e6ecc08b1caea4a313e4f39ab4029a3500d1f91` is green:

- general CI — run `30695154014`;
- Container Supply Chain — run `30695154012`;
- image inventory and exception policy — green;
- Device Agent, Telemetry Service and MQTT security image builds — green;
- CycloneDX and SPDX SBOM generation — green;
- strict Trivy policy for all images — green;
- digest-bound manifests and aggregate release manifest — green;
- secret/private-key evidence checks — green;
- review threads and submitted reviews — none.

## Open Pull Requests

- #209 — security-maintenance PR for #208; final checks green and ready for final review transition.
- #207 — durable central-ingestion PR, waiting for #209 integration and final aggregate rerun.
- #192 — separate draft formatting inventory; not mixed into either active Work Package.

## Evidence boundary

Not claimed by #208:

- changes to Device Agent runtime packages;
- new Raspberry Pi or Modbus hardware evidence;
- production image publication;
- production/site deployment;
- actual-host power-loss, rollback or disk-loss recovery.

## Next action

Mark PR #209 ready, perform final head/mergeability review and squash-merge only while all required checks remain green. Then update PR #207 from `main`, rerun its final aggregate Gate, refresh the Issue #198 checkpoint and merge only after all required checks pass.
