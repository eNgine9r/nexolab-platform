# NEXOLAB Blockers

Updated: 2026-08-05

## Cameras outcome

Issue #273 / PR #274 was squash-merged as `93e865efdadcd1f63a0c31733b98e13f8b6eb4c1` with no remaining software blocker.

State-head verification on `adc6dec1eefe043da2813b7c59be6d39aa1e1aa6`:

- CI `30973948934` GREEN;
- Authenticated Dashboard Acceptance `30973948889` GREEN;
- Refrigeration Browser Acceptance `30973948945` GREEN;
- Offline Bundle `30973948909` GREEN;
- inline review threads: zero;
- submitted reviews: zero;
- no dependency, lockfile, backend schema, camera write, Modbus write or production cutover.

## Smart Lockers blocker

`/lockers` remains blocked. Repository and GitHub state do not provide:

- a concrete locker inventory;
- a read-only protocol or API contract;
- a defined operator workflow;
- verified physical locker evidence.

Do not create demo locker controls, guessed device states, door/lock writes or a fabricated production workflow. Resume only after the Product Owner supplies the missing inventory and protocol scope.

## Parent Issue #260

Issue #260 remains open. The page-completion sequence has one approved blocked tail (`/lockers`) and one independent Ready action: a focused cross-page consistency/completeness review across implemented routes.

## Residual risks, not blockers

- Real camera `online` state still requires a concrete read-only observation source.
- Physical Raspberry Pi, RS-485, cameras, ONVIF, RTSP media, NVR and locker hardware remain unverified.
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

Merge the control-only Issue #275 state reconciliation after state-only diff and GREEN CI, then create the focused cross-page consistency review Work Package under Issue #260. Keep `/lockers` blocked.
