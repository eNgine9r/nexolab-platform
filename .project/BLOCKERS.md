# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents merging Issue #187 or activating the next independent software Work Package.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Verified Work Package

### N-010 — Offline installation and update bundle

**Status:** GREEN and ready to merge — Issue #187 / PR #215.

Verified software boundary on `linux/amd64`:

- seven-image versioned bundle;
- archive and file SHA-256 verification;
- CycloneDX and SPDX SBOMs;
- exact source-commit provenance;
- clean-host image removal and archive-only `docker load`;
- blocked container egress;
- Compose startup with `--no-build --pull never`;
- dashboard, REST, WebSocket, MQTT, PostgreSQL, MinIO and edge simulator smoke checks;
- update and rollback container recreation;
- six required persistent-data volume identities unchanged;
- PostgreSQL, retained MQTT, MinIO object and edge-volume markers preserved.

Offline Bundle run `30708470343`, CI run `30708470342` and Telemetry Service run `30708470344` passed on verified code head `f21d9effe079e07ad3d8d163f029f26d06292556`.

### N-032 — ARM64 and operator-host offline evidence

**Status:** Soft blocker for actual-host acceptance; software work may continue.

The bundle contract supports `linux/arm64`, but this Work Package has not executed the complete archive/load/start/update/rollback drill on an actual Raspberry Pi 5 or operator-owned disconnected host. Do not claim ARM64, physical-media or Raspberry Pi acceptance until that evidence exists.

## Next Ready Work Package

### N-011 — Offline operator authentication

**Status:** Queued for activation after PR #215 — Issue #188.

The Work Package must define and prove fail-closed local operator identity, session management and RBAC without making the core runtime depend on a cloud identity provider. It must remain separate from the installation bundle and must not introduce authentication bypasses or bundled secrets.

## Resolved Work Packages

### N-009 — Live WebSocket lifecycle

Resolved by Issue #199 / PR #214, merged as `8bcf67131ce6900b3513e840661d3cf82934c7eb`.

### N-030 — Dashboard security bootstrap

Resolved by Issue #210 / PR #213, merged as `729139a20b2bd5464aca2291dc4002f514896eee`.

### N-008 — MQTT-to-PostgreSQL durability

Resolved by Issue #198 / PR #207, merged as `5851955ea9a38a9068bbab1eb0c9701722c028c5`.

## Open operational and hardware risks

### N-022 — Actual-host spool recovery

**Status:** Software prepared; host evidence pending under Issue #189.

### N-023 — Node health/status durability

Current node health/status persistence is not claimed to have the same process-restart durability as telemetry measurements.

### N-024 — Rollback compatibility

Do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist. Preserve named volumes and never use the volume-removal flag during update or rollback.

### N-025 — Spool capacity policy

Software thresholds and alerts exist. Validate them against actual-host capacity and throughput evidence. Never auto-delete pending or terminal records.

## Other open soft blockers

- **N-031 / Issue #210 evidence — Affected-PC session bootstrap:** actual host/network cause remains unverified.
- **N-012 / #189 — Recovery and power loss:** final evidence requires controlled central-host and Raspberry Pi access.
- **N-013 / #185, #191, PR #192 — Formatting baseline:** keep separate from product and reliability work.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked; read-only evidence required.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; display/load correlation required.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked; representative KK1/KK2 evidence required.
- **N-017 / #17 — Versioned device profiles:** blocked until #200–#202 evidence exists.
- **N-018 / #108 — Optional Tailscale acceptance:** requires offline-auth decision and controlled hosts.
- **N-019 / #203 — Production dependency updates:** queued maintenance.
- **N-020 / #204 — Major frontend toolchain:** queued maintenance.
- **N-021 / #205 — GitHub Actions runtime dependencies:** queued maintenance.

Missing actual-host or hardware evidence remains unverified. A green software, disconnected-container or scanner result does not authorize image publication, hardware write or site deployment.
