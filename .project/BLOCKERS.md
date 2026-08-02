# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing and merging Issue #194.

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

**Status:** Verified and merged through PR #224 as `f54cd7b6f6db580f3931a40889f5b4e33af3cc30`.

### N-012B — Actual-host and physical recovery evidence

**Status:** Soft blocker; Issue #189 remains open.

The following require controlled central-host and Raspberry Pi access and remain unverified:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

Do not claim these from container or CI evidence.

## Formatting maintenance status

### N-033 — Historical Prettier debt inventory

**Status:** Resolved by Issue #191 / PR #192, merged as `16f1c04616541e7d2391a13eb9eb6b8fb955567c`.

Verified baseline:

- exact debt: 46 files;
- Prettier: `3.9.6`;
- line endings: 46 LF, 0 CRLF, 0 mixed, 0 lone CR;
- generated/vendor candidates: 0;
- justified new `.prettierignore` exclusions: 0.

### N-034 — Controlled formatting child sequence

**Status:** In progress.

Completed:

- Issue #193 / PR #225 — three Markdown files, merged as `75fb9f2921053d39187bbf216057913be2c7fe43`.

Issue #194 / PR #226 is verified as formatting-only and pending final exact-head CI and merge.

Exact Issue #194 scope:

- `e2e/nodes.production.e2e.ts`;
- `e2e/observability.production.e2e.ts`;
- `e2e/refrigeration-layout.production.e2e.ts`;
- `e2e/security-rbac.production.e2e.ts`;
- `eslint.config.mjs`;
- `playwright.observability.config.ts`.

Evidence:

- Prettier `3.9.6` generation workflow `30743441993` passed;
- artifact `8832069755`;
- digest `sha256:0b3816f36eb2d2e01605e55f17d0f2be08b2f976cff02397b1d02d29651370e1`;
- allowlisted semantic apply workflow `30743671286` passed;
- TypeScript AST fingerprints and exact comment-token sequences are identical before and after formatting;
- ESLint flat config imported successfully;
- Playwright observability config generated a non-empty test list without executing production/site E2E;
- patch review shows line wrapping, collection layout and optional trailing-comma formatting only;
- temporary generation/write workflow removed before final review.

Remaining sequence after #194:

1. Issue #195 — ten telemetry/dashboard files;
2. Issue #196 — ten refrigeration domain/repository files;
3. Issue #197 — seventeen refrigeration UI files after #196.

Each Issue must use one focused branch and PR, run Prettier only on its exact file list, contain no product/refactor/dependency changes and update project state independently.

## Next Ready Work Package

### Issue #195 — Format telemetry and dashboard frontend files

**Status:** Ready after PR #226 merge.

Do not combine this group with other formatting, feature, reliability or hardware work.

## Resolved Work Packages

### N-011 — Offline operator authentication

Resolved by Issue #188 / PR #216, merged as `94d111855e727fd0a74af0618c099b11123348cf`.

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
