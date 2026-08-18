# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #576 — software merged, Raspberry Pi approval required

PR #579 is squash-merged at:

`dc4e3186d115d7e2877c0a02c5f315df5946da7e`

Final PR head `cbb0dfba44d8d6cce256ffbf45b8577a9d114629` passed CI #3564 and Telemetry service #1744.

The remaining gate is real Raspberry Pi acceptance. The bounded adopter writes only version-management source-lineage metadata to `/var/lib/nexolab/version-management/current.json`, but this is a new host-state mutation and requires separate explicit Product Owner approval. The earlier Issue #566 deployment approval must not be reused.

Until approved and executed:

- Raspberry Pi remains at `7a19f53950492a40255c53b1d2018bbdff9466e2`;
- deployment evidence remains `runtime/deployments/20260818T131726Z`;
- monitoring runtime remains healthy;
- manual update discovery remains fail-closed at `current_revision_unknown`;
- automatic updates remain OFF;
- fixed timer remains 02:00.

Do not hand-edit `current.json`, fabricate a validated package identity, enable automatic updates or run update/rollback merely to satisfy acceptance.

## Issue #575 — LE-01MP Unit 201 runtime connectivity

Issue #575 remains independently Ready for read-only diagnosis. Unit 201 is timeout/cooldown while the shared bus worker remains healthy and neighboring telemetry advances. Any physical cable/power/address intervention requires separate approval.

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
