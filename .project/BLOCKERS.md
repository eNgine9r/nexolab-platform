# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #265 — Equipment Layouts catalog

No product, architecture, repository-access, browser, review, offline or hardware blocker prevents PR #266 from being marked ready for review after its final exact-head gate.

Verified executable source head: `ac0e02f9911e3b299a21931315d6ff5a8d3cf0a2`.

Executable evidence is GREEN:

- CI `30901392247`;
- Authenticated Dashboard Acceptance `30901391302`;
- Refrigeration Browser Acceptance `30901391433`;
- Offline Bundle `30901391342`;
- browser evidence artifact `8889283540`.

Verified state-only head: `08fd834f564480a83c2207eba4f356fb520a2f6c`.

State-head evidence is GREEN:

- CI `30902446556`;
- Authenticated Dashboard Acceptance `30902446578`;
- Refrigeration Browser Acceptance `30902446647`;
- Offline Bundle `30902446601`.

Review and scope audit:

- inline review threads: zero;
- submitted reviews: zero;
- exactly four `.project` files changed after the executable source head;
- final Pull Request diff contains 15 focused files;
- no temporary workflow, package/lockfile, backend, database migration or unrelated page change remains.

The focused authenticated browser gate proved:

- real PostgreSQL fixtures for published-current, newer unpublished draft, draft-only, no-image/retired and partial-summary-failure states;
- authenticated and organization-scoped read-only equipment/layout requests;
- URL filter reload and deterministic clear-filter navigation;
- successful signed MinIO image loading;
- normalized sensor markers at the expected percentages;
- canonical navigation to `/refrigeration/[equipmentId]`;
- zero catalog mutation requests;
- one injected summary failure remained local while successful catalog items stayed visible.

The disconnected Offline Bundle proved archive load/start with egress blocked and `--pull never`, plus update/rollback persistence preservation without deleting named volumes.

Temporary formatter and focused-fix workflows removed themselves and are absent from the final Pull Request diff.

## Residual risks, not blockers

- The existing layout repository methods own their bounded request timeouts and do not accept an external `AbortSignal`. Catalog orchestration stops scheduling new summaries and suppresses stale commits; already-started requests complete under the repository timeout.
- Signed image URLs can expire independently. The preview keeps this failure local and exposes an explicit image error state.
- Physical Raspberry Pi and RS-485 acceptance is not inferred from browser, container or disconnected bundle evidence.
- Squash merge remains appropriate because PR #266 contains multiple recoverable implementation and verification commits.

## Product-page priority

Issue #265 remains the active Work Package until PR #266 is merged. After merge, the next queued route is `/equipment`.

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

Complete the final exact-head gate for this factual readiness update, mark PR #266 ready for review without merging it and retain `/equipment` as the next queued product-page Work Package after merge.
