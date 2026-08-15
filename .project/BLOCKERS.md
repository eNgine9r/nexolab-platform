# NEXOLAB Blockers

Updated: 2026-08-15

## Hard blocker — physical Raspberry Pi validation

Issue #469 is software-complete but remains open as `status:needs-validation`. PR #476 merged at `b79bcee3670693c46219e8bc58ec3fc8ffe5095a` with GREEN targeted verification, exact-head CI and Telemetry integration.

Final acceptance requires a controlled physical Raspberry Pi deployment proving:

- capacity diagnostics on the real filesystem;
- preserved PostgreSQL, edge SQLite, MQTT, MinIO and Docker named-volume identities/data;
- safe behavior when bounded old deployment-evidence retention applies;
- successful deployment to exact current `main`;
- preserved rollback/evidence behavior.

The deployment may irreversibly prune **only** old strict timestamp children of `runtime/deployments/`, while protecting the current deployment, newest evidence and `.nexolab-preserve` evidence. Product persistent data and named volumes are excluded. Because physical cleanup is irreversible, Product Owner confirmation is required before that controlled execution.

## No independent Ready software package

The repository query for open `status:ready` Issues returns none. Autonomous software work cannot continue around the physical blocker without inventing scope.

## Issue #289

Issue #289 remains open and `status:in-progress` as the broader Raspberry Pi/RS-485 performance/recovery acceptance lane. Software workflow evidence does not satisfy hardware acceptance.

## Other pending physical evidence

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
