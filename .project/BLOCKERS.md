# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing and merging the software-only portion of Issue #189.

Stop before:

- destructive database or persistent-volume operation;
- restore over production data without an isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized signing-key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Issue #189 recovery status

### N-012A — Software backup, restore and rollback evidence

**Status:** Verified on implementation head `9b85ab31d75659c024fc3f1b7191c21628a74728` in PR #224.

Verified software scope:

- fresh checksummed and encrypted recovery bundle;
- five authoritative assets: PostgreSQL, private MinIO objects, Mosquitto Dynamic Security, local-auth private key and local-auth public key;
- fresh-volume PostgreSQL, MinIO and MQTT restore;
- local account, membership and refresh-session recovery;
- fail-closed startup without the restored signing pair;
- matching restored signing pair;
- pre-backup access and refresh session continuity;
- refresh rotation, logout revocation and new password login after restore;
- authenticated REST and WebSocket recovery;
- exactly-once PostgreSQL persistence after duplicate MQTT QoS 1 publication;
- wrong-key and ciphertext-tamper rejection;
- source-volume immutability;
- disconnected linux/amd64 bundle load/start/update/rollback with container egress blocked.

Evidence:

- Disaster Recovery Acceptance run `30741446794`, artifact `8831439044`, digest `sha256:83430669994463232592e082da339b0c570f6d1baa6bfe6e3910b107ccbc90e8`;
- Offline Bundle run `30741446809`, artifact `8831520725`, digest `sha256:232f61b2c57a2c02fb48d2b183c5d227320627ce9fd683d0745bffa4501521dc`.

### N-012B — Actual-host and physical recovery evidence

**Status:** Soft blocker; Issue #189 remains open after the software PR.

The following require controlled central-host and Raspberry Pi access and remain unverified:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

Do not claim these from container or CI evidence.

## Next Ready Work Package

### N-013 — Controlled formatting baseline

**Status:** Ready after PR #224 merge.

Resume Issue #191 / PR #192 as a separate maintenance Work Package. Do not mix formatting changes into reliability, frontend, backend or hardware feature Pull Requests.

## Resolved Work Packages

### N-011 — Offline operator authentication

Resolved by Issue #188 / PR #216, merged as `94d111855e727fd0a74af0618c099b11123348cf`.

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
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked; read-only evidence required.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; display/load correlation required.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked; representative KK1/KK2 evidence required.
- **N-017 / #17 — Versioned device profiles:** blocked until #200–#202 evidence exists.
- **N-018 / #108 — Optional Tailscale acceptance:** requires controlled hosts.
- **N-019 / #203 — Production dependency updates:** queued maintenance.
- **N-020 / #204 — Major frontend toolchain:** queued maintenance.
- **N-021 / #205 — GitHub Actions runtime dependencies:** queued maintenance.

Missing actual-host or hardware evidence remains unverified. A green software, disconnected-container or scanner result does not authorize image publication, hardware write or site deployment.
