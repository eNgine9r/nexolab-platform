# NEXOLAB Blockers

Updated: 2026-08-05

## Issue #273 — operator-safe local Cameras workspace

PR #274 has no remaining implementation, CI, authenticated-browser, refrigeration-regression or offline-runtime blocker.

Verified source head `3b39d9e9f1a8e15c0cb66d0fd8924c25ffba390b`:

- CI `30973348158` GREEN;
- Authenticated Dashboard Acceptance `30973348163` GREEN;
- Refrigeration Browser Acceptance `30973348162` GREEN;
- Offline Bundle `30973348151` GREEN;
- focused source files: 8;
- zero non-GET camera requests in focused production acceptance;
- fabricated Overview `LIVE` evidence removed;
- temporary formatting workflow removed from final diff;
- no dependency, lockfile, backend schema, camera-write, Modbus, hardware or production-cutover change.

Only the state-only boundary validation, final review audit, PR summary update and Ready transition remain.

## Residual risks, not blockers

- A real `online` camera state still requires a concrete read-only observation source.
- Raw RTSP is not a safe browser playback contract and remains explicitly unavailable without a local gateway.
- Physical cameras, ONVIF, RTSP media, NVR and LAN/VPN camera access remain unverified.
- The current production reader intentionally returns an unconfigured inventory instead of fabricating devices or silently using demo data.
- `/lockers` remains blocked pending concrete inventory and read-only protocol scope.
- Deferred toolchain Issues #252–#257 remain outside the page-completion sequence unless a concrete blocker appears.

## Explicitly unsupported and out of scope for Issue #273

- camera CRUD or database migration;
- ONVIF discovery;
- RTSP-to-WebRTC/HLS transcoding;
- recording, archive, playback timeline or retention;
- PTZ, microphone or speaker control;
- camera firmware/configuration writes;
- credentials or secret rotation;
- cloud video hosting;
- physical camera acceptance;
- doors, locks, Smart Lockers or unrelated pages;
- dependency upgrades and unrelated refactors;
- production/site cutover.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera or other unsafe hardware writes;
- credential exposure or unauthorized secret rotation;
- materially different product or architecture choices;
- any operation that cannot preserve local laboratory data.

## Hardware and operational risks

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending.
- **N-037:** Sharp compatibility override remains monitored.
- **N-023:** node health durability is not claimed equal to telemetry process-restart durability.
- **N-024:** rollback must preserve named volumes and spool compatibility.
- **N-025:** actual-host spool capacity evidence remains required.
- **N-032:** actual Raspberry Pi ARM64 archive/load/start/update/rollback remains unverified.
- **#200:** physical RS-485 topology hardware-blocked.
- **#201:** cumulative LE-01MP energy hardware-blocked.
- **#202:** extended XJP60D semantics hardware-blocked.

## Next Ready action

Validate the state-only head against source head `3b39d9e9f1a8e15c0cb66d0fd8924c25ffba390b`, repeat the review and focused-diff audit, update PR #274 summary and mark Ready without merging.
