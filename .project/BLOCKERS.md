# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #576 — completed

Issue #576 Raspberry Pi source-adoption acceptance is PASS and the Issue is closed `status:done`.

The host version-management state now knows the exact deployed source revision without fabricating validated package authority:

- `source_commit=7a19f53950492a40255c53b1d2018bbdff9466e2`;
- `deployment_authority=controlled_source_deployment`;
- `known_packaged_release=false`;
- `runtime_state_known=true`;
- `schema_head=20260807_0024`;
- deployment evidence `runtime/deployments/20260818T131726Z`.

Manual discovery now reports `candidate_discovered` instead of `current_revision_unknown`, with current `7a19f539...`, target `20221323...`, target GREEN verified, and activation correctly blocked at `current_release_unverified` because no validated local package authority exists.

Automatic updates remain OFF and the fixed timer remains 02:00. Monitoring remained uninterrupted during acceptance: API/database/MQTT ready, Device Agent bus workers 1/1 healthy and telemetry advanced. The deployed Raspberry Pi HEAD remained unchanged.

There is no remaining Issue #576 blocker.

## Issue #575 — LE-01MP Unit 201 runtime connectivity

Issue #575 is the only current product `status:ready` Work Package.

Current evidence:

- Device Agent overall status `degraded`;
- shared bus worker remains healthy (`expected=1`, `active=1`, `workers_healthy=true`);
- MQTT and telemetry continue advancing;
- LE-01MP Unit 201 targets return timeout-only outcomes and enter cooldown;
- neighboring LE-01MP Units 200/202/203 and XJP60D acquisition continue responding;
- Issue #201 contains real hardware evidence that Unit 201 responded successfully on 2026-08-17.

The next phase is read-only diagnosis. Do not disable Unit 201 to clear health state and do not assume it is physically absent.

Any meter address/configuration change, Modbus write, reset, power-cycle, cable/power intervention or other hardware mutation is a hard boundary requiring separate explicit approval.

## Remaining evidence lanes

- #575 Unit 201 read-only connectivity diagnosis;
- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest.

Open Dependabot PRs remain isolated dependency lanes and are not selected ahead of the current product/runtime defect.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
