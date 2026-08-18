# NEXOLAB Current State

Updated: 2026-08-18

## Accepted product baseline

The current accepted NEXOLAB product baseline is:

`dc4e3186d115d7e2877c0a02c5f315df5946da7e`

This is the squash merge of PR #579 — **fix: add trusted source deployment lineage evidence**.

Final PR #579 head `cbb0dfba44d8d6cce256ffbf45b8577a9d114629` passed CI #3564 and Telemetry service #1744.

Repository `main` before this state-only reconciliation is:

`20221323fe891e3111cf4af3f51d4e182ba67ce3`

## Current Raspberry Pi runtime

The Raspberry Pi runtime remains deployed at:

`7a19f53950492a40255c53b1d2018bbdff9466e2`

Deployment evidence:

`runtime/deployments/20260818T131726Z`

Issue #566 deployment and Issue #560 token-rotation acceptance remain PASS. Energy Monitoring survived the complete 300-second access-token rotation window without recurrence of `invalid_bearer_token`.

## Issue #576 — Raspberry Pi source-adoption acceptance PASS

The approved source-adoption acceptance completed successfully on the Raspberry Pi without changing the deployed runtime revision.

Trusted version-management evidence now records:

- `deployment_authority=controlled_source_deployment`;
- `source_commit=7a19f53950492a40255c53b1d2018bbdff9466e2`;
- `source_deployment_evidence=runtime/deployments/20260818T131726Z`;
- `runtime_mode=lan`;
- `platform=linux/arm64`;
- `schema_head=20260807_0024`;
- `runtime_state_known=true`;
- `known_packaged_release=false`.

Manual GitHub-aware discovery after adoption returned:

- `status=completed`;
- `result_code=candidate_discovered`;
- current commit `7a19f53950492a40255c53b1d2018bbdff9466e2`;
- target commit `20221323fe891e3111cf4af3f51d4e182ba67ce3`;
- `candidate_available=true`;
- `green_revision_verified=true`;
- `activation_eligible=false`;
- `blocked_reason=current_release_unverified`.

This is the intended fail-closed boundary: source lineage is now known, but the running source deployment is not misrepresented as a validated local package and cannot authorize update/rollback activation.

Automatic updates remain OFF and the fixed host timer remains 02:00.

Runtime verification during adoption remained healthy at the monitoring boundary: Telemetry API/database/MQTT were ready, Device Agent bus workers were `1/1` with `workers_healthy=true`, and `last_attempt_at` advanced from `2026-08-18T16:47:24.997523+00:00` to `2026-08-18T16:47:39.152635+00:00`. Final Raspberry Pi HEAD remained `7a19f53950492a40255c53b1d2018bbdff9466e2`.

Issue #576 is closed `status:done`.

## Independent runtime defect: Issue #575

LE-01MP Unit 201 remains the only current product `status:ready` Work Package. Device Agent overall health is `degraded` because Unit 201 has timeout-only/cooldown behavior, while the shared bus worker remains healthy and neighboring LE-01MP/XJP60D telemetry continues advancing.

Previous real-device evidence in Issue #201 showed Unit 201 responding successfully on 2026-08-17, so it must not be silently disabled or treated as absent.

## Current execution boundary

Next Ready Work Package: **Issue #575 — Diagnose LE-01MP Unit 201 communication timeouts after Raspberry Pi deployment**.

The first phase is read-only evidence collection and software/configuration comparison. No Modbus write, meter address change, reset, power-cycle, cable/power intervention or other physical hardware mutation is authorized without a new explicit approval.

Open Dependabot PRs remain separate dependency lanes and do not supersede this product/runtime defect.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
