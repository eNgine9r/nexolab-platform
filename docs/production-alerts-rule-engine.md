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
- closing a resolved alert releases the evaluation identity while preserving its cooldown watermark, so the same rule/resource may trigger a new immutable instance only after cooldown;
- all lifecycle transitions, rule versions and evidence samples are append-only and attributed to a verified principal or system actor;
- browser actor fields are never authoritative;
- session, stage and binding context are copied from the triggering telemetry record.

## Initial delivery slices

1. PostgreSQL rule, version, alert, transition, evidence and evaluation-state models.
2. Deterministic threshold evaluator with duration, hysteresis, debounce and cooldown.
3. Durable post-persist processing for committed MQTT telemetry.
4. Organization-scoped REST API, immutable rule revisions and RBAC.
5. Authenticated frontend alerts list, dashboard summary and lifecycle workspace.
6. Controlled browser acceptance using production Next.js, FastAPI, PostgreSQL and MQTT.

## Acceptance contract

The controlled Gate proves anonymous denial, Viewer read-only access, organization non-disclosure, versioned rule replacement, short-spike rejection, sustained trigger, duplicate and out-of-order isolation, verified acknowledgement and close actors, hysteresis-based resolution, idempotent close replay, append-only database enforcement and absence of JWT material in browser evidence.

## Boundary

This Gate does not require Raspberry Pi, Modbus, RS-485, Tailscale or access to the physical laboratory network.
