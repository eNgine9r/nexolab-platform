# NEXOLAB Blockers

Updated: 2026-08-17

## Autonomous Sprint selection — resolved for Reports Issue #521

The previous `hard_blocked_no_ready_work_package` selection blocker is resolved by the explicit Product Owner decision to continue Epic #450 with **Reports**.

Issue #521 **Integrate TelemetryPointSelector into report evidence selection** is open, assigned, `priority:critical` and `status:ready`. It is the single next software Work Package after state reconciliation.

Do not bundle or auto-promote:

- Epic #450 Alarms selector integration;
- Epic #450 Equipment Maps selector integration;
- Issue #201 physical restart/power-cycle/rollover validation;
- Issue #245 standalone Raspberry Pi acceptance;
- Issue #444 LOCAL_LAN user-administration runtime retest;
- Issue #189 recovery/power-loss evidence.

## Issue #201 — software merged; physical restart/rollover boundary pending

PR #519 merged product commit `21cddfbb041d4b5c1dc8271c1ee4604460c50170`. Exact final head `48bcad8f3fbb9b71cda3a438863078013fd2d9fb` had GREEN CI, Edge image/Device Agent tests, Acquisition Scale, Device Agent Fleet, Telemetry Service, Authenticated Dashboard, Offline Bundle, Container Supply Chain, Disaster Recovery TLS and MQTT TLS gates.

Normal-operation hardware evidence is verified on installed Units `200–203`:

- read-only FC03 start `7`, count `2`;
- R7 high word + R8 low word, unsigned uint32;
- scale `0.01 kWh`;
- decoded values correlated with physical W1–W4 displays;
- loaded meters increased cumulatively while zero-load meters remained unchanged;
- Device Agent returned healthy after controlled probes;
- no Modbus write, meter reset, configuration change or electrical installation change occurred.

Issue #201 remains `status:needs-validation`. Full hardware acceptance still requires an explicitly approved restart/power-cycle observation and consequent rollover/reset/discontinuity classification. That physical lane is independent and does not block Reports #521.

## Reports #521 — no implementation blocker identified

Repository audit confirmed a focused software path exists without hardware or migration prerequisites:

- terminal Test Sessions already expose persisted `SessionChannelBinding` configuration;
- canonical `TelemetryPointSelector` already exists and is used by prior consumers;
- existing local organization-scoped inventory can enrich taxonomy without becoming the authority for report eligibility;
- report sources and artifacts are already immutable and content-hashed;
- the selected binding subset can be validated server-side and embedded in the immutable source contract without changing physical acquisition.

Implementation must preserve these boundaries:

- selector eligibility comes from the persisted session binding set, not arbitrary live inventory;
- omitted explicit selection remains backward compatible with the current all-session-binding report behavior;
- explicit selection must fail closed for unknown/foreign/duplicate binding IDs;
- excluded bindings must not silently remain in `telemetry.csv` or binding-scoped evidence;
- existing report versions remain immutable;
- selector interaction creates zero new Modbus/polling/discovery/WebSocket/acquisition work;
- LOCAL_LAN/offline runtime remains mandatory.

## Repository repair #524 — completed

The accidental empty root `.tmp` file created during connector preparation was removed through normal PR #525 after exact-head standard CI. The accidental add remains transparently in Git history; no force push/history rewrite was used. No product/runtime/state/data/hardware behavior changed.

## Issue #444 — software complete, controlled Raspberry Pi runtime acceptance blocked

PR #501 is merged with software/offline/browser verification GREEN. Issue #444 still requires a controlled Raspberry Pi `LOCAL_LAN` retest.

Two boundaries apply:

- the next controlled redeploy is stopped by deployment-capacity preflight;
- local signing-key generation/activation/rotation or secret exposure is not authorized.

Do not claim #444 Raspberry Pi runtime acceptance until real deployment evidence exists.

## Deployment capacity — operational constraint before next redeploy

The currently running Raspberry Pi `LOCAL_LAN` runtime is healthy on accepted/deployed product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0`.

The next controlled redeploy remains stopped safely at deployment capacity preflight before runtime mutation:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational blocker for the next controlled redeploy only. Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or runtime acceptance evidence.

## Issue #189 — complete recovery acceptance requires controlled hardware evidence

Issue #189 remains open `status:blocked`.

Its final acceptance requires controlled central-host and Raspberry Pi evidence for isolated restore, restart/reboot, edge outbox preservation, rollback and approved power-loss behavior. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Independent pending physical/evidence items

These remain separate unless explicitly promoted into a focused Work Package:

- #201 LE-01MP restart/power-cycle and rollover/reset/discontinuity validation;
- #507 Raspberry Pi operator/browser acceptance;
- #444 LOCAL_LAN user-administration runtime retest;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- Raspberry Pi version-management acceptance;
- #245 standalone loopback-only Raspberry Pi acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
