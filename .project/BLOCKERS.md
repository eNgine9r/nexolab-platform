# NEXOLAB Blockers

Updated: 2026-08-17

## Issue #444 — software complete, controlled Raspberry Pi runtime acceptance blocked

PR #501 is merged at `efd190a70309039d498e2a9bab2cf47c3598e8b7` with exact-head software/offline/browser verification GREEN.

Issue #444 is intentionally reopened as `status:blocked` because the issue's own acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. This is not a software implementation blocker for independent Work Packages.

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

Classification: soft operational blocker for the next controlled redeploy only. Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or runtime acceptance evidence. Any capacity recovery must be bounded to explicitly disposable artifacts and independently verified before deployment.

## Issue #355 — independently actionable

Issue #355 is the next critical Ready Work Package.

Its software implementation does not require Raspberry Pi redeploy, secret changes or hardware writes. Work may proceed on the canonical measurement-catalog inventory API, bounded PostgreSQL behavior and Live Dashboard editor integration while #444 runtime acceptance remains blocked.

Raspberry Pi latency/query-plan acceptance for #355 remains a separate evidence step and must not be inferred from CI.

## Independent pending physical/evidence items

These remain separate unless promoted into a focused Ready Work Package:

- #444 LOCAL_LAN user-administration runtime retest;
- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
