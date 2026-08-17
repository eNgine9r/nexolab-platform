# NEXOLAB Current State

Updated: 2026-08-17

## Repository and runtime baseline

Current `main` is `426d834390cde83cdec99defa40cf7e165ee711b`, the post-Reports state reconciliation commit. The latest merged product feature remains PR #529 / `1c17719c4dccbef735d58fdea9be87d44f8b8a46`.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. Repository software after that baseline is not treated as Raspberry Pi runtime-accepted until a controlled deployment produces evidence.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`. The next controlled Raspberry Pi redeploy remains blocked by the existing capacity preflight and must not be bypassed by deleting product data, history, volumes or evidence.

## Issue #537 — selectable period consumption implemented and GREEN

Product Owner selected Issue #537 to replace the cumulative-energy presentation in the W1–W4 Energy Monitoring cards with operator-facing `СПОЖИВАННЯ` for a selectable period.

Implementation is on PR #538, branch `feat/537-energy-period-consumption`. Exact implementation head before this state checkpoint was `3df744d36000d719cff02fd756e0610354b1eebc`.

Implemented product behavior:

- W1–W4 primary cards no longer expose the cumulative `kWh` total as the operator KPI;
- each meter has an independent period selector with Today, Yesterday, last 24 hours, 7 days, 30 days, This month and a custom local date/time range;
- interval consumption is derived only from persisted/current `electrical.energy.active` cumulative boundary readings;
- raw cumulative telemetry remains unchanged as the source measurement;
- missing/stale boundary evidence produces an explicit unavailable state;
- negative cumulative delta is classified as a discontinuity/reset/rollover boundary and is not shown as valid consumption;
- active power, U/I/PF, live/stale/error state, timestamp, chart and comparison behavior remain available;
- selector interaction creates no acquisition-registry mutation, physical polling change or Modbus request.

Exact-head verification on `3df744d...` is GREEN:

- CI #3397;
- Authenticated Dashboard Acceptance #1949;
- Refrigeration Browser Acceptance #1830;
- Offline Bundle #1342.

No hardware action, Modbus write, site cutover, persistent-data deletion or new mandatory cloud/runtime dependency was introduced. Raspberry Pi deployment/hardware acceptance is not required for the software completion of #537 and is not claimed.

## Concurrent repository work

PR #539 / Issue #536 (Alarms telemetry selector scope) is open independently from #537. It is not part of the Energy Monitoring Work Package and must not be mixed into PR #538.

## Existing operational blockers

- #201 cumulative-energy normal operation is hardware verified, while approved restart/power-cycle and rollover/reset/discontinuity evidence remains pending.
- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity/signing-key boundaries.
- #189 recovery acceptance remains hardware/evidence blocked.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- next Raspberry Pi redeploy remains capacity-blocked: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
