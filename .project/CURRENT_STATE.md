# NEXOLAB Current State

Updated: 2026-08-16

## Canonical deployed baseline

The controlled Raspberry Pi LOCAL_LAN host is deployed at exact `main` `6dde6989f1822b04c48e8dbdb89f6059b63d6be6`, the state-only merge of PR #478 on top of the Issue #469 product/runtime merge `b79bcee3670693c46219e8bc58ec3fc8ffe5095a`.

## Issue #469 — completed, software and physical acceptance verified

Issue #469 — **Prevent Raspberry Pi deployment evidence capture from exhausting disk** — is closed `completed`.

Software verification remained GREEN from PR #476:

- targeted capacity verification `31908201491` — PASS;
- targeted audit-hardening verification `31908426084` — PASS;
- exact-head CI `31908564398` — PASS;
- exact-head Telemetry service integration `31908564403` — PASS.

Physical Raspberry Pi acceptance completed on 2026-08-16 after Product Owner approval of bounded cleanup limited to old strict timestamped deployment evidence. The initial low-space guard failed safely before runtime mutation; the approved retention then reduced deployment evidence and the controlled deployment passed.

Physical evidence:

- cleanup audit: `/home/nexolab/nexolab-platform/runtime/deployments/20260816T084819Z`;
- deployment evidence: `/home/nexolab/nexolab-platform/runtime/deployments/20260816T084824Z`;
- capacity: `status=PASS`, `free_bytes=16164007936`, `required_bytes=16137036936`, complete live PostgreSQL size estimate;
- deployment: `DEPLOYMENT PASSED`, `runtime_mode=lan`;
- exact deployed commit: `6dde6989f1822b04c48e8dbdb89f6059b63d6be6`;
- central PostgreSQL, MQTT, MinIO, Telemetry Service, Prometheus, Alertmanager and Grafana were healthy after deployment;
- edge MQTT and the Device Agent container were healthy after recreation;
- the protected named-volume identity comparison gate completed without failure;
- no product-data deletion, Docker named-volume deletion, Modbus write, hardware write or site cutover occurred.

## Active Work Package — Issue #289

Issue #289 — **Prove acquisition scale, stability and truthful live-state behavior** — is the active `status:in-progress` physical Raspberry Pi/RS-485 validation lane.

The #469 deployment produced fresh useful #289 evidence: the acquisition scheduler reports one serialized worker for `rs485-main`, `workers_healthy=true`, while LE01MP unit 201 times out and enters cooldown. LE01MP units 200, 202 and 203 and the XJP60D targets continue successful reads. This supports the required isolation behavior but does not yet complete the full no-browser / Overview / Live Dashboard / navigation / multi-browser request-rate matrix.

## Ready audit

The fresh GitHub query for open `status:ready` Issues returned **none**. No independent Ready software Work Package is selected. Continue the already-active Issue #289 rather than inventing new scope.

## Remaining validation boundary

Issue #289 still requires the full controlled real-hardware matrix proving that browser/page count does not change the physical Modbus polling envelope, plus the remaining truthful-state, reconnect and recovery evidence defined by that Issue.

LOCAL_LAN, offline-first runtime and read-only Modbus boundaries remain unchanged. No Modbus/hardware write, product persistent-data deletion, named-volume deletion or site cutover is authorized.
