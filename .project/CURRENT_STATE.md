# NEXOLAB Current State

Updated: 2026-08-18

## Repository and deployed baseline

The current repository, accepted product and deployed Raspberry Pi LOCAL_LAN baseline is:

`2d7740ff1cc2e638f47f2f0787a8e0516626c61e`

This is the merge of PR #558 — **scope authenticated central smoke requests**.

Successful controlled deployment evidence:

`runtime/deployments/20260818T073437Z`

Verified deployment state:

- deployment script: `DEPLOYMENT PASSED`;
- `runtime_mode=lan`;
- `bind_address=172.18.48.34`;
- Dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- `AUTH_MODE=jwt`;
- `local_auth_overlay=true`;
- authenticated central smoke PASS;
- local `administrator` login PASS with provider `nexolab-local`;
- `/api/v1/admin/users` HTTP 200;
- Dashboard enabled and active;
- Central API ready;
- Device Agent expected/active bus workers `1/1`;
- `workers_healthy=true`;
- RS485 worker state `running`;
- telemetry freshness advanced over a 30-second acceptance window.

Deployment capacity preflight also passed:

- `free_bytes=20475432960`;
- `required_bytes=16999167491`;
- `reserve_bytes=2147483648`;
- root filesystem after deployment: 57G total, 37G used, 18G available, 68% used.

## Issues #551 and #557 — completed

Issue #551 **Make central smoke gate compatible with fail-closed LOCAL_LAN authentication** is closed `status:done`.

Issue #557 **Send organization scope before bearer-token assertion in authenticated central smoke** is closed `status:done`.

The final runtime contract is proven on Raspberry Pi:

- public readiness remains available;
- authenticated protected REST smoke sends `X-Organization-ID` first and then requires HTTP 401 when bearer credentials are absent;
- protected WebSocket smoke rejects missing bearer credentials deterministically;
- no operator password, access token, private key or auth bypass is embedded in the smoke gate.

## Issue #444 — deployment blocker cleared; functional validation remains

Issue #444 **Restore LOCAL_LAN user administration API availability** is now `status:needs-validation`, not blocked.

Runtime evidence now proves:

- local-auth overlay is active in controlled LOCAL_LAN deployment;
- `/api/v1/admin/users` is mounted;
- local administrator authentication succeeds;
- authenticated administrator receives HTTP 200 from the users API.

Remaining acceptance is limited to the end-to-end user-management flow not exercised in the deployment acceptance block, including real create/manage behavior and non-admin authorization/frontend diagnostic validation as applicable.

## Active implementation lane

Issue #548 — **Add GitHub-aware safe Raspberry Pi update orchestration** is the active product Work Package and is `status:in-progress`.

Draft PR #559 — **feat: add safe GitHub update discovery plane** — is the existing implementation lane and must be resumed after state-only Issue #562 is reconciled.

Do not create a parallel #548 implementation branch.

#548 must preserve these boundaries:

- GitHub is update-plane only;
- core LOCAL_LAN monitoring works without internet;
- no browser-to-shell bridge;
- no GitHub token in frontend payloads;
- no bypass of package/schema/capacity/backup/version-manager gates;
- no Modbus/controller/hardware writes;
- no persistent-data or named-volume deletion.

## Existing validation lanes

- #444 local user-management end-to-end acceptance remains `needs-validation`;
- #201 cumulative-energy normal operation is hardware verified; restart/power-cycle and rollover/reset/discontinuity evidence remain pending;
- #189 recovery acceptance remains hardware/evidence blocked;
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.

The previous deployment-capacity blocker is cleared by the successful 2026-08-18 preflight. Future deployments must still run the capacity guard and may not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
