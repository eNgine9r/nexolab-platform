# NEXOLAB Current State

Updated: 2026-08-18

## Repository and accepted software baseline

The current repository and accepted software baseline is:

`60797b22e461e3078b535aaaf5b885411eb63aef`

This is the squash merge of PR #568 — **preserve LOCAL_LAN dashboard auth provider during controlled Raspberry Pi deployment**.

Issue #567 is closed `status:done` after exact-head software verification.

The fix keeps the generated dashboard build contract aligned with the active backend local-auth overlay:

- when the controlled deployment enables local operator authentication, `NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local` is generated before the frontend build;
- the frontend organization id is taken from the canonical backend `AUTH_DEFAULT_ORGANIZATION_ID`;
- the deployment fails closed before the dashboard build if the generated local-auth contract is inconsistent;
- the provider and organization scope are passed explicitly into the production build;
- non-secret dashboard auth provider/organization facts are included in deployment evidence;
- deterministic deployment-auth regression coverage now runs through the existing CI standalone Raspberry Pi runtime-contract gate.

Exact-head evidence on PR #568 head `1fd470e54f9d420e864950aeaf9e27cfb9996d2c`:

- CI #3491 PASS;
- standalone Raspberry Pi runtime-contract gate PASS, including the deployment-auth regression suite;
- ADR registry PASS;
- dependency update policy PASS;
- exact Node baseline PASS;
- formatting PASS;
- lint PASS;
- typecheck PASS;
- tests PASS;
- production build PASS.

Authenticated Dashboard, Security Browser, Offline Auth and Offline Bundle were not triggered by the scripts-only #568 diff under their repository path filters. Their previously accepted GREEN auth/offline baseline remains unchanged because #568 did not modify frontend/backend runtime code or dependencies.

## Current Raspberry Pi runtime

The Raspberry Pi code checkout deployed during acceptance Issue #566 is:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Controlled deployment evidence:

`runtime/deployments/20260818T083157Z`

That deployment reported `DEPLOYMENT PASSED` and verified:

- `runtime_mode=lan`;
- `bind_address=172.18.48.34`;
- Dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- `AUTH_MODE=jwt`;
- `AUTH_LOCAL_ENABLED=true` / local-auth overlay enabled;
- central backend healthy;
- Device Agent healthy;
- expected/active bus workers `1/1`;
- telemetry services running.

However that `0bfc4fcc...` deployment exposed the defect fixed by #567: the generated `.env.local` omitted the local frontend auth provider and organization scope, so the login page incorrectly entered the Supabase path and displayed `Supabase Auth не налаштовано для цього середовища.`

The operator then applied a temporary local `.env.local` correction, rebuilt the dashboard and restarted only the dashboard service. Local `administrator` login succeeded afterward. This is valid runtime evidence for the diagnosis, but it is **not repository-backed deployment acceptance of `60797b22...`** and must not be represented as such.

## Issue #560 / #566 — permanent-fix Raspberry Pi acceptance still pending

Issue #560 fixed the stale LOCAL_LAN bearer-token rotation path in software. Issue #566 performed the separately approved deployment of target `0bfc4fcc...`, but the deployment-auth defect discovered during that acceptance prevented the run from closing the final token-rotation evidence boundary cleanly.

The permanent deployment-auth correction is now merged in `60797b22...`.

Full runtime acceptance still requires a separately approved controlled Raspberry Pi deployment of `60797b22...` or newer containing both fixes, followed by:

- successful local `administrator` login without any manual `.env.local` correction;
- Energy Monitoring remaining active through at least one complete local access-token rotation window;
- protected history/consumption requests continuing to succeed;
- no recurrence of `401 invalid_bearer_token`;
- deployment evidence recording `dashboard_auth_provider=local` and the canonical organization id.

Do not claim #560/#566 runtime completion before that evidence exists.

## Active implementation lane

Issue #548 — **Add GitHub-aware safe Raspberry Pi update orchestration** remains the active product Work Package and draft PR #559 remains its single implementation lane.

State-only Issue #569 reconciles the #567/#568 result. After #569 is GREEN and merged, resume Issue #548 on existing PR #559; do not create a parallel #548 branch.

#548 must preserve these boundaries:

- GitHub is update-plane only;
- core LOCAL_LAN monitoring works without internet;
- no browser-to-shell bridge;
- no GitHub token in frontend payloads;
- no bypass of package/schema/capacity/backup/version-manager gates;
- no Modbus/controller/hardware writes;
- no persistent-data or named-volume deletion.

## Existing validation lanes

- #566 / #560 permanent-fix Raspberry Pi token-rotation acceptance remains in progress and requires a separately approved deployment;
- #444 local user-management end-to-end acceptance remains `needs-validation`;
- #201 cumulative-energy normal operation is hardware verified; restart/power-cycle and rollover/reset/discontinuity evidence remain pending;
- #189 recovery acceptance remains hardware/evidence blocked;
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.

Future deployments must continue to run the capacity guard and may not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
