# NEXOLAB Blockers

Updated: 2026-08-05

## Issue #277 outcome

Issue #277 / PR #278 has no remaining software or CI blocker on verified source head `4a86247ff6db1e4a0bee0d3a2d01a2fcb5bee0aa`.

Exact-source verification:

- CI `30977006748` GREEN;
- Authenticated Dashboard Acceptance `30977006760` GREEN;
- Nodes Browser Acceptance `30977006754` GREEN;
- Alerts Browser Acceptance `30977006749` GREEN;
- Reports Browser Acceptance `30977006747` GREEN;
- Refrigeration Browser Acceptance `30977006752` GREEN;
- Offline Bundle `30977006753` GREEN, including disconnected runtime and update/rollback persistent-data preservation.

The remaining control action is final state-only boundary validation, focused diff/review audit, PR summary update and Ready transition without merge.

## Smart Lockers blocker

`/lockers` remains blocked. Repository and GitHub state do not provide:

- a concrete locker inventory;
- a read-only protocol or API contract;
- a defined operator workflow;
- verified physical locker evidence.

Do not create demo locker controls, guessed device states, door/lock writes or a fabricated production workflow. Resume only after the Product Owner supplies the missing inventory and protocol scope.

## Parent Issue #260

Issue #260 remains open with one approved blocked tail: `/lockers`. The independent cross-page consistency review is implemented and verified in Issue #277 / PR #278.

## Residual risks, not blockers

- Physical Raspberry Pi, RS-485, cameras, ONVIF, RTSP media, NVR and locker hardware remain unverified.
- Real camera `online` state still requires a concrete read-only observation source.
- Deferred toolchain Issues #252–#257 remain outside active product scope unless they become a concrete security or delivery blocker.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other unsafe hardware writes;
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

Validate the final Issue #277 state-only boundary, audit PR #278 diff and reviews, update its summary, and mark it Ready without merge. Keep `/lockers` blocked.
