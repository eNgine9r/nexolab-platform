# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #576 — software GREEN, Raspberry Pi metadata acceptance pending

PR #579 implements a fail-closed trusted source-deployment lineage adopter. Implementation head `994c2e66cd05e161172fc76654173805cea72c75` passed CI #3560 and Telemetry service #1740, including the new targeted adoption tests and existing update-orchestrator/version-manager contracts.

The software does not treat a source deployment as a validated package. It creates no catalog entry and keeps activation blocked until genuine package authority exists.

The remaining #576 gate is physical/runtime acceptance on the controlled Raspberry Pi. Running the adopter writes bounded version-management metadata (`/var/lib/nexolab/version-management/current.json`) and therefore requires a new separate Product Owner approval after PR #579 is GREEN/merged.

Until that approval/action, the Pi remains at repository SHA `7a19f53950492a40255c53b1d2018bbdff9466e2`, evidence `runtime/deployments/20260818T131726Z`, and manual update discovery continues to report `current_revision_unknown`.

Do not hand-edit `current.json`, manufacture a catalog package identity, enable automatic updates, or reuse the earlier Issue #566 approval for this new host-state mutation.

## Issue #575 — LE-01MP Unit 201 runtime connectivity

Device Agent reports Unit ID 201 timeout/cooldown while the shared bus worker is healthy, MQTT is connected and neighboring devices continue producing telemetry. Issue #575 remains Ready for read-only diagnosis. Any cable/power/address or other physical intervention requires separate approval.

## Remaining evidence lanes

- #576 Raspberry Pi source-lineage metadata acceptance;
- #575 Unit 201 read-only connectivity diagnosis;
- #444 end-to-end local user-management acceptance;
- #201 approved restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
