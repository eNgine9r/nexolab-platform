# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #267 — Equipment and metrology registry

No product, architecture, repository-access, authenticated-browser, regression, offline or hardware blocker prevents PR #268 from being marked ready for review after its exact state-only checkpoint gate and final review audit.

Verified executable source head: `ad3aae9d8419d21082aabc8c19565953848671cb`.

Executable evidence is GREEN:

- CI `30927620394`;
- Authenticated Dashboard Acceptance `30927615108` — five of five production browser flows passed;
- Refrigeration Browser Acceptance `30927615177`;
- Offline Bundle `30927620159`;
- browser evidence artifact `8899868692`.

The focused authenticated browser gate proved:

- 287 organization-scoped registry assets loaded from the authenticated local contracts;
- active, maintenance and retired refrigeration lifecycle states;
- connected, disconnected and unknown measurement-device states;
- current, due, expired and untracked physical-sensor calibration states;
- combined URL filters persisted through reload and cleared deterministically;
- four injected chamber-summary failures remained isolated while successful assets stayed usable;
- read-only details did not fabricate unsupported calibration dates, certificates, laboratory or uncertainty;
- canonical navigation reached `/refrigeration/66600000-0000-4000-8000-000000000001`;
- all observed registry API requests were authenticated, organization-scoped and GET-only;
- zero registry mutations were observed.

The five-flow gate also re-verified dashboard, Energy Monitoring, Live Data and Equipment Layouts. Equipment Layouts derived the shared total of eight equipment records while retaining all five focused layout lifecycle assertions.

The disconnected Offline Bundle proved archive load/start with egress blocked and `--pull never`, plus update/rollback persistence preservation without deleting named volumes.

Temporary formatter and focused-fix workflows removed themselves and are absent from the executable Pull Request diff.

## Residual risks, not blockers

- The registry composes existing refrigeration and per-chamber measurement APIs. Request volume grows with chamber count; bounded concurrency limits pressure but does not replace a future dedicated summary endpoint if measured scale requires one.
- Existing repositories own bounded request timeouts and do not accept an external `AbortSignal`. Registry orchestration suppresses stale commits and stops new scheduling, while already-started requests complete under repository timeout.
- Calibration status is not a complete metrology record. Dates, next-due dates, certificate metadata/files, calibration laboratory and uncertainty remain unsupported and are shown honestly as unavailable.
- Physical Raspberry Pi and RS-485 acceptance is not inferred from browser, container or disconnected bundle evidence.
- Squash merge remains appropriate because PR #268 contains multiple recoverable implementation and verification commits.

## Product-page priority

Issue #267 remains the active Work Package until PR #268 is merged. After merge, the next queued route is `/settings`, followed by `/cameras`.

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

Validate the exact state-only checkpoint, complete the PR review and focused-diff audit, mark PR #268 ready for review without merging it and retain `/settings` as the next queued product-page Work Package after merge.
