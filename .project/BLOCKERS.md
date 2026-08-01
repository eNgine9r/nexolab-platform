# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents merging Issue #199 or activating the next independent software Work Package.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Verified Work Package

### N-009 — Live WebSocket lifecycle

**Status:** GREEN and ready to merge — Issue #199 / PR #214.

Verified software boundary:

- bounded socket-open, authentication and heartbeat timeouts;
- one bounded reconnect loop without duplicate timers;
- browser-valid private client close codes;
- live state only after authenticated acknowledgement, heartbeat or sample evidence;
- fresh credentials on reconnect;
- terminal unauthorized, forbidden and configuration states;
- preserved resume cursor and event deduplication;
- stale snapshots remain visible but never receive live presentation.

CI run `30704096637` and Authenticated Dashboard Acceptance run `30704096614` passed on verified code head `5edad95e6fa76ab52a0dfdbcf74e8607b0bfe568`.

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

- **N-010 / #187 — Offline installation:** next software Work Package after PR #214; build and prove a checksummed local OCI bundle on a clean disconnected host.
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
