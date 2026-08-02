# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing and merging Issue #230 / PR #233.

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
- generated/vendor candidates: 0;
- justified new `.prettierignore` exclusions: 0.

### N-034 — Controlled formatting child sequence

**Status:** All formatting children are merged.

Completed:

- Issue #193 / PR #225 — 3 documentation files;
- Issue #194 / PR #226 — 6 E2E/root tooling files;
- Issue #195 / PR #227 — 10 telemetry/dashboard files;
- Issue #196 / PR #228 — 10 refrigeration domain/repository files;
- Issue #197 / PR #229 — 17 refrigeration UI files, merged as `786f4568650f5a8bbb3efa5e22445d3f88b706b0`.

Zero paths remain in the historical 46-file formatting inventory.

### N-035 — Final repository-wide Prettier gate

**Status:** Verified on the initial PR #233 head; final exact-head CI pending after state updates.

Evidence:

- Issue #230 / PR #233;
- initial head `b978a1cdee95c6ab1f8e566b787e6ba7997ed8de`;
- CI run `30751629252`;
- `npm run format:check` resolved to `prettier --check .`;
- output: `All matched files use Prettier code style!`;
- ESLint, strict TypeScript, 39 Vitest files / 181 tests and production build passed;
- the workflow uses `set -euo pipefail` before piping diagnostics through `tee`;
- no source formatting or runtime code change is included.

Parent Issue #185 remains open until the updated final PR head repeats the repository-wide gate and PR #233 merges.

## Existing test-output risks

The full suite remains GREEN but emits pre-existing warnings:

- React state updates not wrapped in `act(...)` in several tests;
- non-boolean attributes reaching mocked DOM elements;
- duplicate React keys in one temperature-chart test fixture.

These warnings are outside Issue #230 because the Work Package only restores the formatting gate and updates durable state. They should be handled through a separate focused defect/test-quality Issue rather than mixed into PR #233.

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

## Next Ready Work Package

After PR #233 reaches final exact-head GREEN and merges, close Issue #230 and parent Issue #185. Then select the next independent queued maintenance Work Package from #203–#205.
