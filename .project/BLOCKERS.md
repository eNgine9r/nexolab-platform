# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #566 / #560 — controlled Raspberry Pi deployment completed

The approved LOCAL_LAN deployment completed successfully on Raspberry Pi at:

`7a19f53950492a40255c53b1d2018bbdff9466e2`

Evidence:

`runtime/deployments/20260818T131726Z`

Verified PASS facts include capacity preflight, PostgreSQL pre-upgrade backup, fail-closed JWT/local-auth preservation, Dashboard/API readiness, healthy Device Agent bus-worker invariant, advancing telemetry and Energy Monitoring continuity through the 300-second access-token rotation window.

Issue #560 runtime acceptance is PASS: `/api/v1/auth/local/refresh` returned HTTP 200 and the previous `invalid_bearer_token` Energy Monitoring failure did not recur after rotation.

## Issue #576 — current-release evidence blocks update candidate eligibility

The #548 host update plane is installed, active and safe. Automatic updates remain OFF and the fixed scheduler remains 02:00.

A manual non-mutating `check-now` executed successfully as an update-plane request but returned the fail-closed eligibility state:

`current_revision_unknown`

The controlled source-based deployment has no trusted version-management `current.json` package evidence. This is not a monitoring outage and did not restart or mutate runtime data. Issue #576 is Ready and owns the evidence-backed initialization/adoption path. Do not write `current.json` manually or fabricate a bundle identity.

## Issue #575 — LE-01MP Unit 201 runtime connectivity

Device Agent reports one degraded/cooldown endpoint group: LE-01MP Unit ID 201 has timeout-only outcomes in the current runtime. The shared bus worker remains healthy, MQTT is connected, telemetry advances and Units 200/202/203 plus XJP60D continue returning successful reads.

Issue #575 is Ready for read-only diagnosis. Previous hardware evidence in Issue #201 confirmed Unit 201 worked on 2026-08-17, so it must not be silently disabled. Any physical power/cable/address intervention requires separate approval.

## Remaining evidence lanes

- #576 trusted current-release evidence for GitHub-aware update eligibility;
- #575 Unit 201 read-only connectivity diagnosis;
- #444 end-to-end local user-management acceptance;
- #201 approved restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
