# NEXOLAB Blockers

Updated: 2026-08-17

## Autonomous Sprint selection — hard blocker after Issue #201 software merge

PR #519 merged the verified LE-01MP cumulative active-energy software to product `main` as `21cddfbb041d4b5c1dc8271c1ee4604460c50170`.

Fresh post-merge GitHub audit returns **zero open Issues labelled `status:ready`**.

Issue #201 remains open as `status:needs-validation`. Its software implementation and normal-operation hardware semantics are verified, but full hardware acceptance requires an explicitly approved restart/power-cycle observation and consequent rollover/reset/discontinuity classification. No such physical action is authorized by the software merge.

Per NEXOLAB Autonomous Sprint policy, autonomous product implementation has no independent Ready Work Package after state reconciliation. Continue only after Product Owner selects another independent package or explicitly approves the physical validation required by a `needs-validation` lane.

## Issue #201 — normal-operation hardware verified; power-cycle boundary pending

Verified normal-operation evidence on installed LE-01MP Units `200–203`:

- read-only FC03 start `7`, count `2`;
- R7 high word + R8 low word, unsigned uint32;
- scale `0.01 kWh`;
- decoded values correlated with W1–W4 displays;
- loaded meters increased cumulatively while zero-load meters remained unchanged;
- Device Agent returned healthy after controlled probes;
- no Modbus write, meter reset, configuration change or electrical installation change occurred.

PR #519 exact head `48bcad8f3fbb9b71cda3a438863078013fd2d9fb` had GREEN CI, Edge image/Device Agent tests, Acquisition Scale, Device Agent Fleet, Telemetry Service, Authenticated Dashboard, Offline Bundle, Container Supply Chain, Disaster Recovery TLS and MQTT TLS gates.

Remaining boundary:

- controlled restart/power-cycle observation requires explicit Product Owner approval;
- rollover/reset/discontinuity behavior must not be invented before that evidence;
- negative cumulative deltas are treated as discontinuity/reset/rollover candidates, not silently converted to consumption;
- the new software has not yet been deployed to the accepted Raspberry Pi runtime.

## Issue #444 — software complete, controlled Raspberry Pi runtime acceptance blocked

PR #501 is merged at `efd190a70309039d498e2a9bab2cf47c3598e8b7` with software/offline/browser verification GREEN.

Issue #444 remains open because its own acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. Two boundaries apply:

- the next controlled redeploy is stopped by the existing deployment-capacity preflight constraint;
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
