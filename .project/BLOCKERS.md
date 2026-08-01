# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents starting Issue #187, the next independent software Work Package.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Resolved Work Package

### N-009 — Live WebSocket lifecycle

**Status:** Resolved by Issue #199 / PR #214, merged as `8bcf67131ce6900b3513e840661d3cf82934c7eb`.

Final head `921fba3f1af382f471b614ab5d2cc71952fad0db` passed CI run `30704859884` and Authenticated Dashboard Acceptance run `30704859869`. Stale snapshots remain visible without Live presentation, reconnect is bounded and timer-safe, and terminal auth/configuration states remain distinct.

## Next Ready Work Package

### N-010 — Offline installation and update bundle

**Status:** Ready — Issue #187.

The Work Package must:

- build a checksummed local OCI/application bundle;
- prove installation and update on a clean disconnected host;
- preserve named volumes and local laboratory data;
- document rollback compatibility;
- keep offline operator authentication in separate Issue #188;
- avoid production/site deployment without explicit approval.

## Resolved operator-access Work Package

### N-030 — Dashboard security bootstrap

**Software status:** Resolved by Issue #210 / PR #213, merged as `729139a20b2bd5464aca2291dc4002f514896eee`.

### N-031 — Affected-PC session bootstrap configuration

**Status:** Soft blocker for actual-host acceptance; software work may continue.

The exact cause of the original screenshot remains unverified until the operator runs `docs/operations/dashboard-security-bootstrap.md` against the affected PC and central host. Do not infer whether the cause is API availability, loopback/LAN addressing, CORS, mixed content or another browser transport failure until those checks are returned.

## Resolved data-integrity Work Package

### N-008 — MQTT-to-PostgreSQL durability

**Status:** Resolved by Issue #198 / PR #207, merged as `5851955ea9a38a9068bbab1eb0c9701722c028c5`.

## Open operational and hardware risks

### N-022 — Actual-host spool recovery

**Status:** Software prepared; host evidence pending under Issue #189.

### N-023 — Node health/status durability

Current node health/status persistence is not claimed to have the same process-restart durability as telemetry measurements.

### N-024 — Rollback compatibility

Do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist. Preserve named volumes and never use `docker compose down -v` during update or rollback.

### N-025 — Spool capacity policy

Software thresholds and alerts exist. Validate them against actual-host capacity and throughput evidence. Never auto-delete pending or terminal records.

## Other open soft blockers

- **N-011 / #188 — Offline authentication:** prove fail-closed local operator identity and RBAC.
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

Missing actual-host or hardware evidence remains unverified. A green software or scanner result does not authorize image publication, hardware write or site deployment.
