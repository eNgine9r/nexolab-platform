# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents starting the next software Work Package.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Resolved Work Package

### N-008 — MQTT-to-PostgreSQL durability

**Status:** Resolved by Issue #198 / PR #207.

PR #207 merged as `5851955ea9a38a9068bbab1eb0c9701722c028c5` after all 19 final-head workflows passed. Software evidence covers durable staging before acknowledgement, PostgreSQL outage plus service restart replay, capacity/no-loss behavior, named volumes, observability and supply-chain verification.

## Next Ready Work Package

### N-009 — Live WebSocket lifecycle

**Status:** Ready — Issue #199.

Start from current `main` in a dedicated feature branch. Stabilize live telemetry connection lifecycle and operator-visible states without mixing unrelated catalog, formatting or dependency changes. Historical PR #175 is reference-only.

## Open operational and hardware risks

### N-022 — Actual-host spool recovery

**Status:** Software prepared; host evidence pending under Issue #189.

Required evidence includes container recreation, rollback with pending rows, disk-full response, backup/restore and controlled power interruption on supported hosts.

### N-023 — Node health/status durability

**Status:** Explicitly outside Issue #198.

Current node health/status persistence is not claimed to have the same process-restart durability as telemetry measurements. Create a separate focused Issue only if operational evidence requires it.

### N-024 — Rollback compatibility

Do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist. Preserve named volumes and never use `docker compose down -v` during update or rollback.

### N-025 — Spool capacity policy

Software thresholds and alerts exist. Validate 70%/90% utilization and 15-minute backlog thresholds against actual-host capacity and throughput evidence. Never auto-delete pending or terminal records.

## Other open soft blockers

- **N-010 / #187 — Offline installation:** build and prove a checksummed local OCI bundle on a clean disconnected host.
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
