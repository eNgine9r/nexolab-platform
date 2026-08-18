# NEXOLAB Current State

Updated: 2026-08-18

## Accepted product baseline

The current accepted NEXOLAB product baseline remains:

`9732b68b0d14e4056e5773e0a9bec3f3741e267f`

This is the squash merge of PR #559 — **feat: add safe GitHub update discovery plane**, closing Issue #548. Repository commits after that baseline through the deployed `7a19f53950492a40255c53b1d2018bbdff9466e2` are project-state-only and do not change product/runtime code.

## Current Raspberry Pi runtime

The approved LOCAL_LAN deployment under Issue #566 completed successfully on 2026-08-18.

Deployed repository SHA:

`7a19f53950492a40255c53b1d2018bbdff9466e2`

Deployment evidence:

`runtime/deployments/20260818T131726Z`

Verified runtime facts:

- controlled deployment reported `DEPLOYMENT PASSED`;
- capacity preflight PASS (`free_bytes=20393951232`, `required_bytes=17093875203`, `reserve_bytes=2147483648`);
- PostgreSQL pre-upgrade backup completed before runtime mutation;
- runtime mode `lan`;
- authentication mode `jwt`;
- fail-closed local-auth overlay enabled;
- Dashboard auth provider `local` with the canonical organization scope;
- Dashboard and Telemetry API readiness PASS;
- Device Agent bus worker invariant PASS: `expected_bus_workers=1`, `active_bus_workers=1`, `workers_healthy=true`;
- MQTT remained connected and telemetry timestamps continued advancing.

## Issue #560 token-rotation runtime acceptance

The local access-token lifetime is 300 seconds. After deployment, Energy Monitoring remained operational beyond a complete token-rotation window. `/api/v1/auth/local/refresh` returned HTTP 200 and the Product Owner confirmed Energy Monitoring continued working correctly without the previous `invalid_bearer_token` failure.

Two generic HTTP 401 access-log lines were observed at the deployment/startup boundary before a successful refresh. They did not contain `invalid_bearer_token` and the protected Energy Monitoring flow remained correct after rotation. Issue #560 post-fix Raspberry Pi runtime acceptance is therefore PASS.

## Issue #548 update-plane Raspberry Pi evidence

The host update plane is installed and active:

- `nexolab-version-manager.path` enabled/active;
- `nexolab-update-request.path` enabled/active;
- `nexolab-update-check.timer` enabled/active;
- automatic-update policy remains OFF by default;
- fixed local schedule remains `02:00`;
- manual `check-now` executed non-destructively while policy was OFF.

The manual check returned the truthful fail-closed state:

`current_revision_unknown`

because the source-based deployment does not yet have trusted `/var/lib/nexolab/version-management/current.json` package evidence. No restart, product-data mutation or update activation occurred. Issue #576 owns the focused follow-up to establish trusted current-release evidence without fabricating bundle identity or weakening package/schema/backup gates.

## Independent runtime defect: LE-01MP Unit 201

Device Agent overall health is `degraded` because LE-01MP Unit ID 201 currently returns timeout-only outcomes and is in cooldown. This does not invalidate the deployment: the shared bus worker is healthy, MQTT is connected, telemetry advances, LE-01MP Units 200/202/203 return successful reads, and XJP60D acquisition continues.

Issue #575 owns read-only diagnosis. Previous real-device evidence in Issue #201 showed Unit 201 responding successfully on 2026-08-17, so it must not be silently disabled or classified as absent.

## Current execution boundary

Issue #566 controlled deployment and token-rotation acceptance are complete. The update-plane manual check-path is verified fail-closed, with current-release initialization explicitly deferred to Issue #576.

Open Ready Work Packages were audited after acceptance. The next Ready Work Package is Issue #576 because it is the direct dependency for making the already installed GitHub-aware 02:00 maintenance plane operational without weakening offline/runtime safety. Issue #575 remains an independent Ready hardware-connectivity diagnostic lane.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
