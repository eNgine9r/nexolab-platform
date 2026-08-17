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

After an operator reboot, the existing central/edge containers auto-started healthy and the final #289 disconnected-browser acceptance passed on that runtime.

A redundant controlled redeploy on the same head stopped safely at deployment capacity preflight **before runtime mutation**:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational blocker for the **next controlled redeploy** only. Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or runtime acceptance evidence. Any future capacity recovery must be bounded to explicitly disposable artifacts and independently verified before deployment.

## Ready-work boundary

After closing #493, #289 and #282, repository audit found **0 open `status:ready` Issues**.

This becomes the Sprint hard stop after state-only Issue #497 is merged: no independent Ready Work Package exists. Open Dependabot pull requests are separate dependency lanes and must not be selected as product work without their governing Issue/status and required migration/verification policy.

## Independent pending physical/evidence items

These remain separate from the completed #282/#289 acceptance sequence unless explicitly promoted into a focused Ready Work Package:

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
