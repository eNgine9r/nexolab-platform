# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline before this Work Package: `915d4c2c914ae3c3b9ef2b0f6b60fabb18f00a85`  
Active Work Package: Issue #189 software recovery slice / PR #224  
Status confidence: high for repository, linux/amd64 CI, encrypted software recovery, local operator authentication and disconnected-container evidence; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed baseline

- PR #184 — AI Development Operating Standard.
- PR #190 — verified architecture and offline boundary.
- PR #206 — stale tracker and Pull Request reconciliation.
- PR #207 — durable MQTT-to-PostgreSQL telemetry ingestion.
- PR #209 — Device Agent supply-chain hardening.
- PR #213 — dashboard security bootstrap diagnostics.
- PR #214 — live WebSocket lifecycle stabilization.
- PR #215 — verified offline installation/update bundle.
- PR #216 — fail-closed offline operator authentication.
- PR #223 — argument-safe disposable DR MinIO credential.

## Issue #189 software recovery outcome

PR #224 extends the canonical encrypted disaster-recovery boundary to the local operator-authentication state introduced by Issue #188.

Implementation head `9b85ab31d75659c024fc3f1b7191c21628a74728` verified:

- PostgreSQL, private MinIO objects, Mosquitto Dynamic Security and the local-auth RSA private/public pair are represented as five authoritative recovery assets;
- passwords, access tokens and refresh tokens remain external to the encrypted bundle;
- restored Telemetry Service fails closed without the matching signing pair;
- the restored private/public key fingerprints match before runtime startup;
- local accounts, organization memberships and refresh-session state survive logical backup and isolated restore;
- a pre-backup access session and refresh session remain valid after restore;
- refresh rotation, logout revocation and a new password login work after restore;
- restored REST and WebSocket paths require and accept the recovered local identity;
- duplicate post-restore MQTT QoS 1 publishes produce exactly one PostgreSQL row;
- wrong backup keys and modified ciphertext are rejected;
- source volumes remain unchanged and restore volumes are fresh;
- runtime token verification uses a separate UID `10001`, mode `0400` copy while the operator copy remains host-owned mode `0600`;
- temporary container-owned object files are ownership-normalized only inside the isolated `mktemp` recovery directory before cleanup.

## Exact implementation-head verification

The five workflows triggered by the focused diff passed on implementation head `9b85ab31d75659c024fc3f1b7191c21628a74728`:

- CI run `30741446834` — changed-file formatting, ESLint, strict TypeScript, all Vitest suites and production build passed.
- Telemetry Service run `30741446799` — migrations, backend tests, outage recovery, offline migration SQL and container build passed.
- Disaster Recovery Domain Completeness run `30741446796` passed.
- Disaster Recovery Acceptance run `30741446794` — recovery inventory/policy plus encrypted source-to-fresh-restore application acceptance passed.
- Offline Bundle run `30741446809` — linux/amd64 bundle build, runtime-image removal, blocked container egress, archive-only load, `--pull never` startup and update/rollback volume preservation passed.
- Review threads: 0.
- Submitted reviews: 0.

Primary evidence:

- disaster-recovery artifact ID `8831439044`, digest `sha256:83430669994463232592e082da339b0c570f6d1baa6bfe6e3910b107ccbc90e8`;
- offline-bundle artifact ID `8831520725`, digest `sha256:232f61b2c57a2c02fb48d2b183c5d227320627ce9fd683d0745bffa4501521dc`.

The sanitized recovery artifact records:

- backup duration: 4 seconds;
- restore duration: 15 seconds;
- software RPO: 0 seconds;
- two restored source telemetry rows and one exactly-once post-restore row;
- zero dead-letter rows;
- three private MinIO objects;
- four restored MQTT identities including a disabled client;
- one restored local account and one active pre-verification session;
- authenticated WebSocket handshake;
- successful refresh rotation, logout revocation and new password login;
- no source-volume mutation.

The artifact summary identifies GitHub's tested PR merge ref `51943895cc455f68722ac67afc0f420b0afb20da`; the artifact metadata binds that run to source head `9b85ab31d75659c024fc3f1b7191c21628a74728`.

## Runtime and security boundary

- Core recovery requires no internet, remote identity provider or paid runtime service.
- No password, refresh token, access token or production identity is committed or included in the recovery bundle.
- The RSA private signing key is included only inside the encrypted recovery payload and remains an operator-controlled secret.
- PostgreSQL availability remains required for local session validation and immediate revocation.
- No persistent production volume was deleted.
- No production/site deployment, Modbus write or hardware action was performed.

## Open Pull Requests

- #224 — software recovery extension; implementation is verified and project-state finalization is in progress before ready/merge.
- #192 — separate draft controlled-formatting inventory.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Remaining Issue #189 hardware scope

The software-only portion is verified. Issue #189 remains open for controlled actual-host evidence:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

These results must not be inferred from container evidence.

## Next Ready Work Package

After PR #224 reaches final exact-head GREEN and is merged, continue the next independent Ready maintenance package: Issue #191 / PR #192, the controlled formatting baseline. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
