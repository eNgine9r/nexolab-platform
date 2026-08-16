# NEXOLAB Blockers

Updated: 2026-08-16

## Issue #469 deployment-capacity blocker — resolved

Issue #469 is closed `completed`. The real Raspberry Pi LOCAL_LAN acceptance passed after Product Owner-approved bounded cleanup limited to old strict timestamped `runtime/deployments/<timestamp>` evidence.

Verified physical result:

- low-space guard failed safely before runtime mutation;
- bounded evidence retention was applied without deleting product data or Docker named volumes;
- final capacity preflight passed with `free_bytes=16164007936` and `required_bytes=16137036936` using a complete live PostgreSQL estimate;
- controlled deployment passed at exact `main` `6dde6989f1822b04c48e8dbdb89f6059b63d6be6`;
- protected named-volume identity comparison completed without failure;
- central services, dashboard, edge MQTT and Device Agent container recovered successfully.

The obsolete #469 physical-validation hard blocker is removed.

## Active physical validation — Issue #289

Issue #289 remains open `status:in-progress` and is now the active Raspberry Pi/RS-485 scale, stability and truthful-state validation lane.

Fresh 2026-08-16 evidence shows:

- one serialized worker on `rs485-main`;
- scheduler worker state remains running/healthy;
- LE01MP unit 201 is timing out and enters cooldown;
- unrelated LE01MP units 200, 202 and 203 continue successful reads;
- XJP60D active targets continue successful reads;
- central ingestion remains ready.

This is not a #469 deployment failure. It must be evaluated under #289 against the explicit acceptance criterion that one unavailable endpoint does not make unrelated channels appear offline.

Remaining #289 work includes the controlled no-browser / Overview / one Live Dashboard / repeated navigation / multi-browser physical-request-rate matrix, truthful reconnect/stale/offline behavior and recovery gates.

## Ready queue

The fresh GitHub query for open `status:ready` Issues returned none. There is no independent Ready software package to run instead of the already-active #289 lane.

## Other pending physical evidence

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
