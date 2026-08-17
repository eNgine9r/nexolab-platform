# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

Current `main` is `b00c996a1990dde4f5427e0caa44cc34f1e4f6a6`, the squash merge of PR #538 — **selectable period consumption in Energy Monitoring**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. The Energy Monitoring period-consumption work from PR #538 has not been deployed to the Raspberry Pi and is not claimed as Raspberry Pi runtime acceptance.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`. The next controlled Raspberry Pi redeploy remains blocked by the capacity preflight and must not be bypassed by deleting product data, history, named volumes or evidence.

## Issue #537 — completed and merged

Issue #537 **Add selectable period consumption to Energy Monitoring cards** is completed through PR #538 / merge `b00c996a1990dde4f5427e0caa44cc34f1e4f6a6`.

Product outcome:

- W1–W4 primary cards show `СПОЖИВАННЯ` rather than exposing the cumulative totalizer as the operator KPI;
- each meter owns an independent selector for Today, Yesterday, last 24 hours, 7 days, 30 days, This month and a custom local date/time range;
- consumption is derived only from verified `electrical.energy.active` cumulative readings near the selected boundaries;
- raw cumulative telemetry remains unchanged as the source measurement;
- missing/stale boundary evidence fails closed as unavailable;
- negative delta fails closed as a reset/rollover/discontinuity boundary instead of producing fabricated consumption;
- active power, U/I/PF, timestamps, comparison selection, chart behavior and live/stale/error semantics remain available;
- selector interaction causes zero acquisition-registry mutation, physical polling change or Modbus request.

Final implementation head `3df744d36000d719cff02fd756e0610354b1eebc` was GREEN:

- CI #3397;
- Authenticated Dashboard Acceptance #1949;
- Refrigeration Browser Acceptance #1830;
- Offline Bundle #1342.

No Raspberry Pi deployment or new hardware acceptance was required or claimed for #537.

## Concurrent / next repository work

Issue #536 / PR #539 — Alarms telemetry-selector scope — remains an independent open Work Package and must not be mixed with the completed Energy Monitoring change. Its own exact-head/CI state governs whether it is the next mergeable package.

## Existing operational blockers

- #201 cumulative-energy normal operation is hardware verified; approved restart/power-cycle and rollover/reset/discontinuity evidence remains pending.
- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity/signing-key boundaries.
- #189 recovery acceptance remains hardware/evidence blocked.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- next Raspberry Pi redeploy remains capacity-blocked: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
