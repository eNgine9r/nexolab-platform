# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `99c3785f073f37e9c4c131ca68b4c6df3c219114`  
Active Work Package: Issue #237 / PR #238 — make generated DR object-storage credentials argument-safe  
Status confidence: high for repository state, GitHub-hosted CI, deterministic credential regression and encrypted software recovery; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and physical hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`.
- Development internet is allowed; core runtime internet and paid cloud services are not required.
- Local PostgreSQL, MQTT, edge SQLite, logs, backup and restore remain first-class.
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed reliability and maintenance baseline

- PR #184 — AI Development Operating Standard.
- PR #190 — verified architecture and offline boundary.
- PR #206 — stale tracker and Pull Request reconciliation.
- PR #207 — durable MQTT-to-PostgreSQL telemetry ingestion.
- PR #209 — Device Agent supply-chain hardening.
- PR #213 — dashboard security bootstrap diagnostics.
- PR #214 — live WebSocket lifecycle stabilization.
- PR #215 — verified offline installation/update bundle.
- PR #216 — fail-closed offline operator authentication.
- PR #224 — encrypted local-auth disaster-recovery extension.
- PR #225–#229 and #233 — controlled formatting baseline and permanent repository-wide Prettier gate.
- PR #234 / Issue #205 — GitHub Actions runtime compatibility, merged as `99c3785f073f37e9c4c131ca68b4c6df3c219114` after a 26-of-26 GREEN workflow sweep.

## Issue #237 / PR #238 outcome

The nondeterministic MinIO CLI failure is fixed at the credential generator boundary instead of changing the shared Compose credential contract.

Implementation:

- `compose.disaster-recovery.yaml` is unchanged from `main`.
- `run-disaster-recovery-acceptance.sh` prefixes generated MinIO credentials with `nxl_` while preserving the full random payload.
- a deterministic self-test proves `-leading-option-like` becomes `nxl_-leading-option-like` and cannot begin with `-`.
- Disaster Recovery Acceptance invokes the self-test before policy and encrypted runtime verification.

Verified implementation head:

- `1ddd0bf128aed310596b05b0a3da2f150b54ed91`;
- CI run `30760710838` — formatting, lint, typecheck, full tests and production build GREEN;
- Disaster Recovery Acceptance run `30760710828` — policy and encrypted source-to-restore runtime GREEN on the first attempt, without rerun;
- sanitized evidence artifact `8837371547`, digest `sha256:3c4f07f86c704db683c7ddce1397858ed08b6d696cbc73398a4f6d5a09a6c8d1`;
- exact changed paths before state update: the DR script and DR Acceptance workflow only.

## Open Pull Requests

- #238 — verified software fix, pending final exact-head CI, review audit and merge.

## Open risks and blockers

- No hard blocker prevents completing PR #238.
- Issue #189 actual-host reboot, power-loss and physical-media recovery evidence remains unverified.
- Hardware Issues #200–#202 remain blocked pending controlled read-only physical evidence.
- Complete `linux/arm64` offline archive/load/start/update/rollback execution on an actual Raspberry Pi 5 remains unverified.
- Existing frontend test warnings remain outside this DR scripting Work Package.

## Next Ready Work Package

After PR #238 reaches exact-head GREEN and merges, start Issue #203: focused review of production dependency updates. Major frontend migrations remain isolated in Issue #204.
