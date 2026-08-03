# NEXOLAB Blockers

Updated: 2026-08-03

## Issue #261 — Energy Monitoring

No product, software, runtime or hardware blocker prevents finalization of PR #262.

Verified implementation head `0f2cf40dbb0a4d7763cf2ee8948770910fbbb03d` passed:

- CI run `30843193403` — formatting, ESLint, strict TypeScript, full Vitest suite and production build;
- Authenticated Dashboard Acceptance run `30843193556` — energy latest/history, meter selection, WebSocket update and evidence upload;
- Refrigeration Browser Acceptance run `30843192945` — existing refrigeration operator flow remains intact.

Review corrections include:

- stable captured-time cursor pagination with overlapping page-boundary timestamps;
- renderable-only absolute-bucket downsampling with first/latest endpoint preservation;
- source-derived outage segments from raw communication-error records and cadence gaps;
- persistent pending break state across separate WebSocket error and recovery callbacks;
- transfer of a first-bucket outage marker to the next retained point without losing the earliest endpoint;
- permission gating before telemetry REST and WebSocket traffic starts;
- requested-window scaling, per-metric freshness, metric/unit validation and production node scope;
- incremental WebSocket history, wall-clock pruning and future-skew rejection.

Remaining administrative actions: validate the state-only head, resolve addressed review threads and merge PR #262 with expected-head protection.

Cumulative active energy remains blocked under Issue #201 until the physical register, scale, unit, word order and rollover behavior are confirmed. Do not display guessed `kWh`.

## Product-page priority

After PR #262, Issue #263 is Ready and replaces `/live` with the universal authenticated telemetry explorer.

Deferred toolchain Issues #252–#257 may resume only for a relevant security fix, end-of-support condition or concrete blocker for an active product Work Package.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production device behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Hardware and operational risks

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending controlled access.
- **N-037:** Sharp compatibility override remains monitored.
- **N-023:** node health durability is not claimed equal to telemetry process-restart durability.
- **N-024:** rollback must preserve named volumes and spool compatibility.
- **N-025:** actual-host spool capacity evidence remains required.
- **N-032:** actual Raspberry Pi ARM64 archive/load/start/update/rollback remains unverified.
- **#200:** physical RS-485 topology hardware-blocked.
- **#201:** cumulative LE-01MP energy hardware-blocked.
- **#202:** extended XJP60D semantics hardware-blocked.

## Next Ready action

Finalize and merge PR #262, then start Issue #263. Do not insert deferred dependency migrations between these product pages.
