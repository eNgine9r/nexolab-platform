# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `b00c996a1990dde4f5427e0caa44cc34f1e4f6a6`, the squash merge of PR #538 — **selectable period consumption for Energy Monitoring**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. Repository changes after that accepted runtime, including Energy Monitoring period consumption, have not been deployed to the Raspberry Pi.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`, with central PostgreSQL/MQTT/Telemetry healthy, edge MQTT/Device Agent healthy, and one serialized RS-485 worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #537 — completed and merged

Issue #537 **Add selectable period consumption to Energy Monitoring cards** is closed `status:done` through PR #538 / merge `b00c996a1990dde4f5427e0caa44cc34f1e4f6a6`.

Product outcome:

- W1–W4 primary cards no longer present the cumulative-energy counter as the operator-facing value;
- each card presents `СПОЖИВАННЯ` for an independently selected period;
- presets cover Today, Yesterday, last 24 hours, 7 days, 30 days and current month, plus a validated custom local date/time range;
- interval consumption is derived only from verified `electrical.energy.active` cumulative boundary readings;
- raw cumulative telemetry remains unchanged as internal source truth;
- missing/stale boundary evidence produces an explicit unavailable state;
- negative deltas are classified as reset/rollover/discontinuity and are not fabricated into consumption;
- equivalent W1–W4 historical boundary reads are auth-scoped and coalesced so the existing bounded navigation/read-model invariant is preserved;
- active power, U/I/PF, timestamps, comparison selection and live/stale/error semantics remain intact;
- selector interaction changes no physical polling, acquisition registry, Modbus traffic or hardware state.

Final implementation head `3df744d36000d719cff02fd756e0610354b1eebc` had GREEN:

- CI #3397 — format, lint, typecheck, tests, production build and repository contracts;
- Authenticated Dashboard Acceptance #1949 — 16/16 Playwright flows, including Energy period consumption, authenticated history, live updates, route time-to-usable and bounded acquisition/read-model invariants;
- Refrigeration Browser Acceptance #1830;
- Offline Bundle #1342 — clean transferred host, pull-disabled disconnected start, update/rollback persistent-data preservation and final disconnected evidence.

Evidence artifacts:

- `authenticated-dashboard-acceptance-32053053523-1`, SHA-256 `8ec1b7fefc8abcbf7aaa5f2ecbdbf181b903fb5a6ef4ccecc3c3cc82874ea2d2`;
- `nexolab-offline-amd64-3df744d36000d719cff02fd756e0610354b1eebc`, SHA-256 `40d9cb52628c48467923fea1989a38854d7f5cc9baf775eb32673e3f37a37d95`.

No Raspberry Pi deployment, Modbus write, hardware mutation, DB schema change, dependency upgrade, site cutover or mandatory public/cloud runtime dependency occurred in #537.

## Issue #201 — normal-operation hardware verified; full power-cycle boundary pending

Issue #201 remains open `status:needs-validation`.

Verified normal-operation semantics remain:

- read-only FC03 start register `7`, count `2` atomically;
- R7 high word + R8 low word, unsigned uint32, scale `0.01 kWh`;
- Units `200–203` correlated with physical W1–W4 displays;
- loaded meters increased cumulatively while zero-load meters remained unchanged;
- no Modbus write, reset, configuration mutation or electrical installation change occurred.

Full #201 hardware acceptance still requires explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification. Issue #537 deliberately fails closed on a decreasing counter rather than inventing rollover behavior.

## Active product lane — Issue #536 / PR #539

A repository audit during #537 completion found that Issue #536 **Integrate TelemetryPointSelector into Alarms feed scope** is already `status:in-progress` with draft PR #539 on `feat/536-alarms-telemetry-selector`.

This state reconciliation does not modify, reprioritize or take over #536. It records the existing repository fact so the Sprint does not falsely report a no-work hard blocker while an implementation lane is already active.

The current audit finds **zero open Issues carrying `status:ready`**. That does not create a hard blocker while #536 is already in progress; the next selection decision belongs after the active #536 package is resolved.

## Existing operational blockers

- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity and signing-key authorization boundaries.
- #189 recovery acceptance remains hardware/evidence blocked; no destructive restore, named-volume deletion, product-data deletion or hardware write is authorized.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- The next controlled Raspberry Pi redeploy remains stopped by capacity preflight: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`. Do not bypass the guard or delete product data/history/volumes/evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
