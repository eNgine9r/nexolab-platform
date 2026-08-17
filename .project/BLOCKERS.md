# NEXOLAB Blockers

Updated: 2026-08-17

## No active #493 / #289 product blocker

Issue #493 is closed `completed` and hardware verified on deployed product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0`.

Post-fix Phase 12B evidence:

`runtime/evidence/issue-289-20260817T080201Z-phase12b-postfix-r2`

Issue #289 is closed `completed` after the final disconnected `LOCAL_LAN` browser-route acceptance passed:

`runtime/evidence/issue-289-20260817T082747Z-disconnected-browser-routes-r2`

Parent performance/data-acquisition Epic #282 is also closed `completed`.

## Deployment capacity — operational constraint before next redeploy

The currently running Raspberry Pi `LOCAL_LAN` product/runtime is healthy on exact accepted product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0`.

A redundant controlled redeploy on the same head stopped safely at deployment capacity preflight **before runtime mutation**:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational blocker for the **next controlled redeploy** only. Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or runtime acceptance evidence. Any future capacity recovery must be bounded to explicitly disposable artifacts and independently verified before deployment.

## Issue #444 — implementation is independently actionable

Issue #444 is selected as the next critical Ready Work Package.

Current defect: the LOCAL_LAN Users & Access screen can receive HTTP 404 for `/api/v1/admin/users` when local-user administration routes are not mounted in the effective runtime composition.

Software implementation and verification are independently actionable without touching secrets. The following boundary remains explicit:

- code may add full-app route-composition tests, deployment/runtime fail-closed checks and explicit frontend diagnostics;
- code may preserve existing local-auth behavior and administrator permission boundaries;
- local signing-key generation/activation, secret rotation or secret exposure is **not authorized** as part of software implementation;
- if final Raspberry Pi acceptance requires enabling/changing secrets, that step becomes a hard blocker requiring Product Owner action/approval.

## Superseded state trackers

Issues #416 and #449 are stale state-only reconciliation trackers whose factual baselines have been superseded by later accepted merges and state. They should be closed as `not_planned`/superseded and must not consume Sprint capacity.

## Independent pending physical/evidence items

These remain separate unless promoted into a focused Ready Work Package:

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
