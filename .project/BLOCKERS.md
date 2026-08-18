# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #548 / PR #559 — software merged, no software blocker

Issue #548 is closed with `status:done`. PR #559 is squash-merged into the accepted product baseline:

`9732b68b0d14e4056e5773e0a9bec3f3741e267f`

Final PR exact head `76120bef1108086fdc1648cddbcf9bd293502e6e` passed all 13 triggered workflows. The software/security/offline boundary is accepted; Raspberry Pi runtime acceptance remains pending the controlled deployment now approved under Issue #566.

## Raspberry Pi deployment — approval granted

The Product Owner explicitly approved the post-#548 controlled Raspberry Pi deployment on 2026-08-18 at 16:03 Europe/Uzhgorod.

Issue #566 is no longer blocked on approval. The controlled deployment may proceed on the existing Raspberry Pi in `lan` mode using `scripts/deploy-current-head-raspberry-pi.sh --runtime-mode lan`.

The current pre-deployment Raspberry Pi baseline is:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Existing evidence:

`runtime/deployments/20260818T083157Z`

The deployment must stop on any failed clean-tree, capacity, backup, build, health or smoke gate. No bypass by deleting product data, PostgreSQL history, named volumes or protected evidence is authorized.

## Remaining evidence for Issue #566 / #560 / #548

- exact deployed SHA and repository-backed deployment evidence;
- local administrator login without manual auth-provider correction;
- access-token rotation continuity for Energy Monitoring/history requests;
- no recurrence of `401 invalid_bearer_token`;
- #548 automatic-update policy default OFF;
- safe manual update discovery and truthful offline/update-plane behavior;
- installed 02:00 host-local scheduler/policy state;
- version-management capacity/backup/package-validation/runtime-verification/rollback evidence where exercised;
- API/Dashboard readiness, Device Agent health and advancing telemetry.

## Other evidence lanes

- #444 end-to-end local user-management acceptance;
- #201 approved restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
