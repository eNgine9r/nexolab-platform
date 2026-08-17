# NEXOLAB Blockers

Updated: 2026-08-17

## Autonomous Sprint selection — resolved for Issue #513

The previous post-#507 hard selection blocker was resolved by an explicit Product Owner decision to continue Epic #450 with the Test Sessions selector integration.

Issue #513 **Integrate canonical TelemetryPointSelector into Test Sessions** is now the active Work Package through PR #514. Exact product head `b884bf2e531e1eb6f3dbd99fbeef0ec9de77f21a` is software/browser/backend/offline verified and ready for the final merge audit.

Fresh GitHub search still returns **zero open Issues labelled `status:ready`**. This does not block the already-selected active Issue #513, which is `status:in-progress`. It means the post-merge next Work Package must be selected again unless a new repository-backed Ready task appears.

Do not automatically promote or bundle into PR #514:

- remaining Epic #450 selector consumer integrations for reports, alarms or equipment maps;
- #245 while it remains `status:needs-validation` and requires real standalone Raspberry Pi acceptance;
- #444 while controlled Raspberry Pi runtime acceptance remains blocked;
- #189 while hardware/recovery evidence remains blocked.

## Issue #513 — no open implementation blocker

PR #514 exact product head `b884bf2e531e1eb6f3dbd99fbeef0ec9de77f21a` has GREEN:

- CI #3290 / run `32033655886` — format, lint, typecheck, 442 tests and production build;
- Test Sessions Browser Acceptance #878 / run `32033655829` — canonical selector subset plus existing production session flow;
- Telemetry service #1593 / run `32033655867` — backend/runtime contract, migrations, recovery and container build;
- Offline Bundle #1265 / run `32033655901` — disconnected runtime with blocked egress/pull disabled and persistent-data-preserving update/rollback.

No unresolved PR reviews or review threads were present at the product-head audit. No Raspberry Pi deployment or hardware action is required by Issue #513.

## Epic #450 — remaining product sequencing decision after Sessions

Completed Epic #450 work now includes the previously merged children #451, #453, #457, #461, #465 and #507, with #513 pending merge as the Sessions consumer integration.

Epic #450 Work Package 5 requires each remaining consumer integration to be a separate focused Issue/PR. Reports, alarms and equipment maps are therefore post-merge candidates only; their order is not automatically inferred.

## Issue #507 — completed; Raspberry Pi evidence remains separate

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** is completed through PR #510 / product merge `ba988930ba78bc44c6ec6b003a13af79d552f9fa`.

Classification remains:

`software/browser/offline verified; Raspberry Pi operator acceptance pending`

No Raspberry Pi operator/browser acceptance is claimed without real evidence.

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
