# NEXOLAB Blockers

Updated: 2026-08-18

## Current Sprint selection — not blocked

Critical deployment-auth defect #567 is software-complete and merged through PR #568 as:

`60797b22e461e3078b535aaaf5b885411eb63aef`

Exact-head CI #3491 is GREEN, including the deployment-auth regression suite, formatting, lint, typecheck, tests and production build.

The active product implementation lane remains:

**Issue #548 / draft PR #559 — Add GitHub-aware safe Raspberry Pi update orchestration.**

State-only Issue #569 is reconciling the #567/#568 result before #548 resumes. No parallel #548 branch should be created.

## Issue #566 / #560 — permanent-fix Raspberry Pi runtime validation pending

This is an evidence and deployment-approval boundary, not a software blocker for unrelated repository work.

The separately approved Issue #566 deployment of target `0bfc4fcc56f7a669545be166c585573550f2fb44` completed with `DEPLOYMENT PASSED` and evidence:

`runtime/deployments/20260818T083157Z`

Backend local auth, API and Device Agent were healthy, but the generated dashboard environment omitted `NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local` and organization scope. Operator login therefore entered the Supabase path.

The operator applied a temporary `.env.local` correction and rebuilt/restarted the dashboard; local `administrator` login then succeeded. That manual correction confirms the diagnosis but is not repository-backed acceptance of the permanent #567 fix.

The permanent fix is now in `60797b22...`. Full #566/#560 runtime acceptance still requires a separately approved controlled deployment of `60797b22...` or newer plus observation through at least one complete local access-token rotation window with no `401 invalid_bearer_token` recurrence.

Do not claim permanent-fix Pi acceptance from CI or from the manual frontend correction.

## Deployment capacity — current blocker cleared

The latest controlled deployment capacity guard passed:

- `free_bytes=20475432960`;
- `required_bytes=16999167491`;
- `reserve_bytes=2147483648`;
- root filesystem was 68% used at the recorded preflight.

Future deployments must still run the same guard. Do not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Issue #444 — end-to-end user-management validation pending

Issue #444 remains `status:needs-validation`.

The LOCAL_LAN runtime has already proven local-auth overlay availability and local administrator authentication. Remaining validation is the actual create/manage user flow and non-admin authorization/frontend diagnostic behavior as applicable.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified. Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance.

## Issue #189 — recovery hardware evidence pending

Issue #189 remains blocked pending controlled central-host and Raspberry Pi recovery evidence. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Other pending physical/evidence lanes

- #566 / #560 permanent-fix LOCAL_LAN token-rotation runtime acceptance;
- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- future Raspberry Pi version-management acceptance for #548.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
