# NEXOLAB Current State

Updated: 2026-08-02  
Verified product baseline: `main` at `d4b5971a0abb31a571be1540512c8694485967d7` plus Issue #188 implementation head `e02a830b2ca413b3dd35b5e60c6647681dd0c02b` in PR #216  
Next Ready Work Package: Issue #189 software-only recovery preparation  
Status confidence: high for repository, linux/amd64 CI, local operator authentication and disconnected-container evidence; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

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
- PR #223 — argument-safe disposable DR MinIO credential.

## Issue #188 verified outcome

PR #216 implements a fail-closed local identity authority inside Telemetry Service while preserving the provider-neutral JWT, organization-membership, RBAC and immutable audit boundaries.

Implemented runtime behavior:

- PostgreSQL local accounts linked to existing security identities and memberships;
- standard-library `scrypt` password hashes with bounded parameters and malformed-hash rejection;
- RS256 access JWTs signed only by an externally mounted private key;
- matching local public-key validation through the existing JWT boundary;
- opaque refresh tokens with SHA-256 hashes persisted in PostgreSQL;
- PostgreSQL session identifier validation on every local authenticated request;
- bounded database-backed failed-login lockout;
- login, refresh rotation, logout and immediate post-revocation rejection;
- explicit CLI key generation, account bootstrap, password reset and session revocation;
- local browser credential provider and generic login page;
- optional Supabase/external JWT behavior remains isolated and non-mandatory;
- offline bundle includes the local-auth Compose overlay and operator documentation, but no accounts, passwords or signing keys.

## Verification on implementation head

Implementation head `e02a830b2ca413b3dd35b5e60c6647681dd0c02b` passed all 19 Pull Request workflows.

Key runs:

- CI: `30737691025` — changed-file formatting, ESLint, strict TypeScript, all Vitest suites and production build passed.
- Telemetry Service: `30737691020` — PostgreSQL migrations, backend tests, outage recovery, offline migration SQL and container build passed.
- Offline Auth Acceptance: `30737691023` — migration round-trip, disconnected browser/API authentication, RBAC, refresh/logout/revocation, blocked container egress and persistence recreation passed.
- Offline Bundle: `30737691007` — linux/amd64 bundle build, archive-only load, `--pull never` startup, smoke checks and update/rollback volume preservation passed.
- Container Supply Chain, Capacity Release, MQTT TLS Fleet, Device Agent Fleet, Security, Authenticated Dashboard, Nodes, Refrigeration, Sessions, Alerts, Reports and Disaster Recovery acceptance workflows passed.

Offline-auth evidence artifact:

- artifact ID: `8830202764`;
- size: `218992` bytes;
- digest: `sha256:437b86732aaa6dacf9656541a0d0f9f6caeb625f31557e064e458705b47eaccd`.

Evidence proves:

- migration revision `20260801_0021` upgrades, downgrades to `20260731_0021`, and upgrades again;
- auth tables are present after upgrade, absent after downgrade, and present after re-upgrade;
- viewer and operator are denied `audit.read`, administrator is permitted;
- three accounts and three membership-role bindings retain identical fingerprints through update-style and rollback-style recreation;
- the same PostgreSQL volume identity is preserved;
- the access session remains valid through both recreations and returns `401` after logout;
- audit records identify the local actor and server-side role;
- Telemetry Service public egress is blocked during acceptance.

Offline bundle artifact:

- artifact ID: `8830269134`;
- size: `558463050` bytes;
- digest: `sha256:6d72d2f43872ae3f4a441d0d3d0d3110721eb0c07ba798d72eba9849744d75ce`.

## Runtime and security boundary

- Production-intended `LOCAL_LAN` authentication is local and fail-closed; `AUTH_MODE=disabled` remains development/isolated-validation only.
- No password, private signing key, refresh token or production identity is committed or bundled.
- Core login, session validation and RBAC require no internet, remote JWKS, Supabase or paid service.
- PostgreSQL availability is required for local session validation and revocation.
- Signing-key backup and controlled rotation remain operator responsibilities documented in the security runbook.
- No persistent production volume was deleted.
- No production/site deployment, Modbus write or hardware action was performed.

## Open Pull Requests

- #216 — Issue #188 implementation, verified and pending final state/merge guard.
- #192 — separate draft formatting inventory.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

Issue #189 — prepare and prove the software-only portion of backup, isolated restore, rollback and recovery acceptance.

Allowed immediate scope without Raspberry Pi access:

- fresh logical backup and checksums;
- isolated PostgreSQL and MinIO restore targets;
- row, object and relationship comparison;
- central service restart and readiness recovery;
- version rollback with named-volume preservation;
- explicit stale/offline/recovery dashboard states;
- exact evidence and RPO/RTO observations.

Actual central-host reboot, Raspberry Pi reboot, edge power interruption and physical power-loss acceptance remain soft-blocked until controlled host access exists. They must not be inferred from container evidence.

## Remaining unverified areas

- linux/arm64 bundle execution on an actual Raspberry Pi 5;
- physical-media transfer and installation on an operator-owned disconnected host;
- actual central-host and Raspberry Pi reboot/power interruption;
- physical disk-full and disk-loss behavior;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
