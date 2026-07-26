# Production alerts rule engine

Sprint 13 introduces organization-scoped, deterministic alert evaluation for NEXOLAB telemetry.

## Core invariants

- alert rules and alert instances belong to exactly one organization;
- evaluation is idempotent for duplicate telemetry event IDs;
- out-of-order samples cannot move a rule evaluation backwards;
- a single rule/resource identity has at most one non-closed alert instance;
- acknowledgement records operator awareness but does not resolve the physical condition;
- resolution requires the clear condition to remain satisfied for the configured duration;
- hysteresis separates trigger and clear thresholds;
- all lifecycle transitions are append-only and attributed to a verified principal;
- browser actor fields are never authoritative;
- session, stage and binding context are copied from the triggering telemetry record.

## Initial delivery slices

1. PostgreSQL rule, version, alert, transition and evaluation-state models.
2. Deterministic threshold evaluator with duration, hysteresis, debounce and cooldown.
3. Organization-scoped REST API and RBAC.
4. Authenticated frontend alerts list and detail workspace.
5. Controlled browser acceptance using Next.js, FastAPI, PostgreSQL and MQTT.

## Boundary

This Gate does not require Raspberry Pi, Modbus, RS-485, Tailscale or access to the physical laboratory network.
