# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents finalizing Issue #188 or starting the software-only preparation portion of Issue #189 after merge.

Stop before:

- destructive database or persistent-volume operation;
- restore over production data without an isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized signing-key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Verified Work Package awaiting merge

### N-011 — Offline operator authentication

**Status:** Software and disconnected-container acceptance verified in Issue #188 / PR #216 on implementation head `e02a830b2ca413b3dd35b5e60c6647681dd0c02b`.

Verified boundaries:

- fail-closed local identity authority inside Telemetry Service;
- PostgreSQL accounts, memberships and revocable sessions;
- `scrypt` password hashing;
- externally mounted RS256 signing keys;
- access-token session validation and immediate revocation;
- viewer/operator/administrator server-side RBAC;
- immutable local actor audit attribution;
- migration upgrade/downgrade/re-upgrade consistency;
- disconnected browser login, refresh and logout;
- blocked Telemetry Service container egress;
- preserved account, membership and session fingerprints through update-style and rollback-style recreation;
- local-auth overlay and runbook included in the offline bundle;
- no bundled password, private key, refresh token or production identity data.

Key runs:

- CI `30737691025`;
- Telemetry Service `30737691020`;
- Offline Auth Acceptance `30737691023`;
- Offline Bundle `30737691007`.

## Next Ready Work Package

### N-012 — Backup, restore, rollback and recovery

**Status:** Issue #189 is ready for software-only preparation after Issue #188 merges.

Independent software scope:

- fresh checksummed logical backup;
- isolated PostgreSQL and MinIO restore targets;
- domain row/object/relationship comparison;
- central service restart and readiness recovery;
- rollback with named-volume preservation;
- explicit stale/offline/recovery browser states;
- sanitized evidence and RPO/RTO observations.

### Actual-host recovery evidence

**Status:** Soft blocker for final Issue #189 acceptance.

The following require controlled central-host and Raspberry Pi access and remain unverified:

- host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

Do not claim these from container or CI evidence.

## Resolved Work Packages

### N-010 — Offline installation and update bundle

Resolved by Issue #187 / PR #215, merged as `4c980781ff1beb0afb89f1779c82750a06e8eb7e`.

### N-009 — Live WebSocket lifecycle

Resolved by Issue #199 / PR #214, merged as `8bcf67131ce6900b3513e840661d3cf82934c7eb`.

### N-030 — Dashboard security bootstrap

Resolved by Issue #210 / PR #213, merged as `729139a20b2bd5464aca2291dc4002f514896eee`.

### N-008 — MQTT-to-PostgreSQL durability

Resolved by Issue #198 / PR #207, merged as `5851955ea9a38a9068bbab1eb0c9701722c028c5`.

## Open operational and hardware risks

### N-023 — Node health/status durability

Current node health/status persistence is not claimed to have the same process-restart durability as telemetry measurements.

### N-024 — Rollback compatibility

Do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist. Preserve named volumes and never use the volume-removal flag during update or rollback.

### N-025 — Spool capacity policy

Software thresholds and alerts exist. Validate them against actual-host capacity and throughput evidence. Never auto-delete pending or terminal records.

### N-032 — ARM64 and operator-host offline evidence

The bundle contract supports `linux/arm64`, but complete archive/load/start/update/rollback execution on an actual Raspberry Pi 5 or operator-owned disconnected host remains unverified.

## Other open soft blockers

- **N-031 / Issue #210 evidence — Affected-PC session bootstrap:** actual host/network cause remains unverified.
- **N-013 / #185, #191, PR #192 — Formatting baseline:** keep separate from product and reliability work.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked; read-only evidence required.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; display/load correlation required.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked; representative KK1/KK2 evidence required.
- **N-017 / #17 — Versioned device profiles:** blocked until #200–#202 evidence exists.
- **N-018 / #108 — Optional Tailscale acceptance:** requires controlled hosts.
- **N-019 / #203 — Production dependency updates:** queued maintenance.
- **N-020 / #204 — Major frontend toolchain:** queued maintenance.
- **N-021 / #205 — GitHub Actions runtime dependencies:** queued maintenance.

Missing actual-host or hardware evidence remains unverified. A green software, disconnected-container or scanner result does not authorize image publication, hardware write or site deployment.
