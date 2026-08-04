# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #265 — Equipment Layouts catalog

No product, architecture, repository-access or hardware blocker prevents continuation in PR #266.

The first executable implementation slice is verified on source head `f61d6de5231ab9326901c0bc005e572ae1735bf2`:

- CI `30892831371` GREEN;
- formatting, ESLint, strict TypeScript, full Vitest and production build passed;
- focused tests verify explicit layout-state derivation, combined filtering, bounded concurrency, partial failure preservation and cancellation;
- `/equipment-layouts` is wired to an authenticated live runtime and never silently falls back to demo data;
- the preview is read-only and all mutations remain in `/refrigeration/[equipmentId]`;
- temporary formatter workflows were removed and are absent from the branch diff.

State and checkpoint verification are also GREEN:

- CI `30893471962` GREEN on the four-file state-only checkpoint;
- CI `30893835781` GREEN after recording state-gate evidence;
- CI `30894064784` GREEN on final metadata head `b7af7086ffe9b74a0deca70c46a86aebe1850f14`.

Browser/API/MinIO acceptance has not run yet, so PR #266 must remain draft and the Work Package is not complete.

## Remaining verification risks inside Issue #265

- Prove the catalog against production Next.js, authenticated FastAPI, PostgreSQL layout records and MinIO signed images.
- Prove URL-backed filter reload and canonical navigation in Chromium.
- Seed published-current, newer unpublished draft, draft-only/no-image and partial-summary-failure cases without adding demo fallback.
- Confirm a broken or expired signed image affects only the preview and remains retryable.
- The existing repository interfaces do not accept an external AbortSignal. The catalog cancels stale orchestration, stops scheduling new summaries and suppresses stale state commits, while already-started repository requests complete under their existing bounded timeout. This is acceptable for the current read-only slice but must be observed during browser acceptance.
- Retired equipment remains read-only and must expose no catalog mutation controls.

These are verification risks, not blockers. A narrow read-only summary endpoint remains unauthorized unless measured browser/runtime evidence proves the current contracts insufficient.

## Product-page priority

Issue #265 remains the active page-completion Work Package. After it merges, the next queued route is `/equipment`.

Deferred toolchain Issues #252–#257 remain outside the page-completion sequence unless a security, support or concrete product blocker appears.

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

Add a focused Equipment Layouts browser acceptance in PR #266, prove the authenticated read-only catalog and signed-image preview against the real local stack, then complete final exact-head and state-only verification.
