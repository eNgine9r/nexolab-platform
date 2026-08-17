# NEXOLAB Blockers

Updated: 2026-08-17

## Autonomous Sprint selection — hard blocker

Fresh post-merge repository audit after Issue #507 / PR #510 confirms:

- current product `main` is `ba988930ba78bc44c6ec6b003a13af79d552f9fa`;
- Issue #507 is closed completed / `status:done`;
- fresh GitHub search returns **zero open Issues labelled `status:ready`**.

Per the NEXOLAB Autonomous Sprint policy, absence of an independent Ready Work Package is a hard selection blocker. Autonomous product implementation stops here until a repository-backed priority is selected.

Do not automatically promote:

- remaining Epic #450 selector consumer integrations: session, report, alarm and equipment-map integrations are explicitly separate follow-up Work Packages, but their order is not currently defined by the repository;
- #245 while it remains `status:needs-validation` and requires real standalone Raspberry Pi acceptance;
- #444 while controlled Raspberry Pi runtime acceptance remains blocked;
- #189 while hardware/recovery evidence remains blocked.

## Issue #507 — completed; Raspberry Pi evidence remains separate

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** is completed through PR #510 / merge `ba988930ba78bc44c6ec6b003a13af79d552f9fa`.

Final exact PR head `74bdb039744d4da427adb5aacc557e148dfc2022` had GREEN:

- CI #3271 / run `32026588140`;
- Refrigeration Browser Acceptance #1782 / run `32026588024`;
- Authenticated Dashboard Acceptance #1857 / run `32026588105`;
- Offline Bundle #1250 / run `32026588165`.

Classification:

`software/browser/offline verified; Raspberry Pi operator acceptance pending`

No Raspberry Pi operator/browser acceptance is claimed without real evidence.

## Epic #450 — remaining product sequencing decision

The following Epic #450 children are closed completed:

- #451 canonical chart continuity / inspector / event provenance;
- #453 equipment-centric multi-metric charts with dynamic Y axes;
- #457 graph-first Live Data composition;
- #461 reusable hierarchical `TelemetryPointSelector`;
- #465 first consumer integration into Live Dashboard editor;
- #507 Overview graph-first full-width composition.

Epic #450 Work Package 5 explicitly leaves session/report/alarm/equipment-map selector integrations as separate follow-up Issues/PRs. Those follow-up Issues are not currently Ready and their order is not repository-defined. Do not close the Epic or fabricate the next child Work Package by assumption.

## Issue #444 — software complete, controlled Raspberry Pi runtime acceptance blocked

PR #501 is merged at `efd190a70309039d498e2a9bab2cf47c3598e8b7` with exact-head software/offline/browser verification GREEN.

Issue #444 remains open `status:blocked` because its own acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. This does not invalidate already completed software work.

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

This is an evidence/hardware blocker for #189 only.

## Independent pending physical/evidence items

These remain separate unless explicitly promoted into a focused Work Package:

- #507 Raspberry Pi operator/browser acceptance;
- #444 LOCAL_LAN user-administration runtime retest;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- Raspberry Pi version-management acceptance;
- #245 standalone loopback-only Raspberry Pi acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
