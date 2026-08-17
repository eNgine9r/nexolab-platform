# NEXOLAB Blockers

Updated: 2026-08-17

## Issue #444 — software complete, controlled Raspberry Pi runtime acceptance blocked

PR #501 is merged at `efd190a70309039d498e2a9bab2cf47c3598e8b7` with exact-head software/offline/browser verification GREEN.

Issue #444 remains open `status:blocked` because its own acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. This does not block independent software Work Packages.

Two boundaries apply:

- the next controlled redeploy is stopped by the existing deployment-capacity preflight constraint;
- local signing-key generation/activation/rotation or secret exposure is not authorized. If final runtime acceptance requires such a change, Product Owner action is required.

Do not claim #444 Raspberry Pi runtime acceptance until real deployment evidence exists.

## Deployment capacity — operational constraint before next redeploy

The currently running Raspberry Pi `LOCAL_LAN` product/runtime is healthy on exact accepted product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0`.

A controlled redeploy stopped safely at deployment capacity preflight **before runtime mutation**:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational blocker for the next controlled redeploy only. Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or runtime acceptance evidence.

## Issue #189 — complete recovery acceptance requires controlled hardware evidence

Issue #189 remains open `status:blocked`.

Its final acceptance requires controlled central-host and Raspberry Pi evidence for isolated restore, restart/reboot, edge outbox preservation, rollback and approved power-loss behavior. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

This is an evidence/hardware blocker for #189 only. It does not block independent software work.

## Closed work packages removed from the blocker/Ready queue

- #355 is closed `completed` / `status:done`; its Live Dashboard canonical inventory software work is no longer pending.
- #357 is closed `completed` / `status:done`; its refrigeration hydration software work is no longer pending.

Any remaining Raspberry Pi latency observations for these areas must be recorded as evidence or as a newly reproduced defect, not as stale future software work.

## Issue #507 — independently actionable

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** is the next critical software Work Package after state reconciliation.

It requires no Raspberry Pi redeploy, secret changes, database mutation or hardware writes to begin implementation. Its Raspberry Pi operator/browser acceptance remains a separate evidence step.

## Independent pending physical/evidence items

These remain separate unless promoted into a focused Work Package:

- #444 LOCAL_LAN user-administration runtime retest;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
