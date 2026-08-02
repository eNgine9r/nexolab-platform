# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing and merging Issue #196.

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

**Status:** Resolved by Issue #191 / PR #192.

Verified baseline:

- exact debt: 46 files;
- Prettier: `3.9.6`;
- line endings: 46 LF, 0 CRLF, 0 mixed, 0 lone CR;
- generated/vendor candidates: 0;
- justified new `.prettierignore` exclusions: 0.

### N-034 — Controlled formatting child sequence

**Status:** In progress.

Completed:

- Issue #193 / PR #225 — 3 documentation files;
- Issue #194 / PR #226 — 6 E2E/root tooling files;
- Issue #195 / PR #227 — 10 telemetry/dashboard files, merged as `c5fa0fdcca6d86f54ba7430b5ca8efd7ffc39f8c`.

Issue #196 / PR #228 is formatting-only and pending final exact-head CI after project-state updates.

Verified Issue #196 evidence:

- exact scope: 10 refrigeration domain/repository paths;
- Prettier generation workflow `30748758550`;
- artifact `8833742334`;
- digest `sha256:7b0a538fec903beb1e2440422a7abbcbcf7cea1a48103e74d894259e0690e56f`;
- verified staging workflow `30748882865` passed;
- source AST remained identical;
- transpiled runtime AST remained identical;
- exact comment-token sequences remained identical;
- targeted climate catalog repository, layout draft storage and sensor placement management tests passed;
- all ten patches were reviewed;
- REST paths and methods, request payloads, `If-Match`, `X-Audit-Reason`, ETag/version handling, validation predicates, identifiers, error strings and assertions are unchanged;
- clean commit `24eb015513f28780fcf1d1ee919ef1db41908e72` was created directly from merged `main` using only verified formatted blob SHA values;
- final source diff contains exactly the ten allowlisted files before mandatory state updates;
- temporary generation/write workflow is absent from final branch history and diff.

No behavior, schema, migration, dependency, UI, deployment, hardware or Modbus change is included.

Remaining sequence after #196:

1. Issue #197 — 17 refrigeration UI files.

Each Issue must use one focused branch and PR, run Prettier only on its exact file list, contain no product/refactor/dependency changes and update project state independently.

## Next Ready Work Package

### Issue #197 — Format refrigeration UI component files

**Status:** Ready after PR #228 merge.

Do not combine this group with product fixes, domain/repository changes, schema changes, dependencies, deployment or hardware work.

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
