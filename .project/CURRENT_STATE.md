# NEXOLAB Current State

Updated: 2026-08-18

## Repository and accepted software baseline

The current repository and accepted software baseline is:

`4cf20a173c793f67b7befb239d8489977d0df4b5`

This is the squash merge of PR #561 — **preserve LOCAL_LAN bearer-token rotation**.

Issue #560 is closed `status:done` after exact-head software, browser and offline verification.

The fix routes the established legacy frontend runtime credential provider through the existing LOCAL_LAN refresh-token provider when `NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local`. Protected clients therefore resolve a current bearer token instead of reusing an expired in-memory access token. Missing local API configuration fails closed with no bearer token.

Exact-head evidence on PR #561 head `4ee47fddb9ec903361dd5382ec40cb0d9eb1e9ac`:

- CI #3473 PASS: formatting, lint, typecheck, full tests and production build;
- Security Browser Acceptance #1197 PASS;
- Authenticated Dashboard Acceptance #1988 PASS;
- Offline Auth Acceptance #527 PASS;
- Nodes Browser Acceptance #703 PASS;
- Alerts Browser Acceptance #866 PASS;
- Test Sessions Browser Acceptance #889 PASS;
- Reports Browser Acceptance #889 PASS;
- Rendered Reports Browser Acceptance #734 PASS;
- Offline Bundle #1398 PASS, including disconnected startup and update/rollback persistent-data preservation.

## Deployed Raspberry Pi baseline

The currently accepted deployed Raspberry Pi LOCAL_LAN baseline remains:

`2d7740ff1cc2e638f47f2f0787a8e0516626c61e`

Successful controlled deployment evidence:

`runtime/deployments/20260818T073437Z`

That deployed baseline verified:

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

Deployment capacity preflight passed with `free_bytes=20475432960`, `required_bytes=16999167491`, `reserve_bytes=2147483648`; root filesystem was 68% used.

## Issue #560 — software/offline complete; post-fix Pi runtime unverified

The operator-observed Energy Monitoring failure after roughly 1–2 minutes was classified as a stale LOCAL_LAN bearer-token path, not a Modbus acquisition failure:

`401 invalid_bearer_token / bearer token validation failed`

Software and disconnected-runtime verification are complete in `4cf20a173c793f67b7befb239d8489977d0df4b5`.

The Raspberry Pi has **not** been deployed to `4cf20a...` in this Work Package. Therefore post-fix physical/runtime acceptance remains unverified. The deployed `2d7740...` system may continue to reproduce the 401 until a separately approved controlled deployment is performed and Energy Monitoring is observed through at least one complete local access-token rotation window.

## Active implementation lane

Issue #548 — **Add GitHub-aware safe Raspberry Pi update orchestration** remains the active product Work Package and is `status:in-progress`.

Draft PR #559 — **feat: add safe GitHub update discovery plane** — is the existing implementation lane. Resume this same branch/PR after state-only Issue #564 is merged; do not create a parallel #548 implementation branch.

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
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence;
- #560 post-fix Raspberry Pi token-rotation runtime acceptance is pending a separately approved deployment of `4cf20a...` or newer containing the fix.

Future deployments must continue to run the capacity guard and may not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
