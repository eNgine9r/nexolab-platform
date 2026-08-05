# NEXOLAB Blockers

Updated: 2026-08-05

## Issue #269 — operator-safe Settings workspace

PR #270 has no remaining implementation, CI, authenticated-browser, offline-runtime or review blocker.

Verified source head `434224191f914e5ca884ac838a2ce66e4a30f6ea`:

- CI `30953948950` GREEN;
- Authenticated Dashboard Acceptance `30953948970` GREEN;
- Refrigeration Browser Acceptance `30953948956` GREEN;
- Offline Bundle `30953948928` GREEN;
- focused source files: 13;
- inline review threads: zero;
- submitted reviews: zero;
- zero backend mutation requests observed by the Settings acceptance;
- no dependency, lockfile, backend schema, Modbus, hardware or production-cutover change.

The source implementation is ready for the final state-only head audit and PR Ready transition. It must not be merged until the state-only commit is confirmed to contain only `.project/**` changes and the PR remains mergeable with required checks satisfied.

## Residual risks, not blockers

- Physical Raspberry Pi and RS-485 acceptance is not relevant to this software-only workspace and remains unverified.
- Public runtime variables are client-visible by design; the implemented diagnostics display only sanitized origins and explicit invalid/mixed-content states.
- Browser-local preferences affect presentation only and do not alter acquisition, alarms, retention, authentication, nodes or devices.
- `/cameras` is the next queued page after Issue #269 merges.
- `/lockers` remains blocked pending a concrete inventory, read-only protocol and operator workflow.
- Deferred toolchain Issues #252–#257 remain outside the page-completion sequence unless a security, support or concrete product blocker appears.

## Explicitly unsupported and out of scope for Issue #269

- organization or membership CRUD;
- node provisioning, credentials or deployment changes;
- Modbus/RS-485 parameters or device writes;
- alarm-rule, retention, backup or restore mutation;
- CORS, TLS, DNS, VPN or secret rotation;
- database migration or universal settings API;
- dependency upgrade or unrelated design-system refactor;
- production/site cutover.

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

Validate the state-only PR head, repeat the final review and focused-diff audit, update PR #270 summary and mark the PR Ready without merging.
