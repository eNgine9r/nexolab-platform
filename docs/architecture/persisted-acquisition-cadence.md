# Persisted Acquisition Cadence and RS-485 Capacity Contract

## Purpose

Issue #589 makes recurring acquisition cadence an explicit, durable part of the local Acquisition Registry instead of an implicit side effect of scheduler priority classes.

The product outcome is operator-controlled cadence that survives restart, is auditable through the existing registry revision stream, and cannot be committed when the requested rate would exceed the conservative capacity envelope of the affected physical RS-485 bus.

This contract is local-first and read-only. It introduces no Modbus write path, cloud runtime dependency, mandatory public service, hardware cutover, or browser-driven polling path.

## Source of truth

Cadence is stored in Acquisition Registry schema v2 in the edge SQLite database.

The same durable document owns:

- logical buses;
- devices and lifecycle;
- read-only targets;
- cadence family defaults;
- device-specific cadence overrides;
- revision and update timestamp.

Cadence updates use the same optimistic revision and audit stream as topology/lifecycle mutations. There is no second cadence database or hidden scheduler-owned configuration source.

## Precedence and limits

Effective cadence is resolved in this order:

1. device-specific override;
2. bus + device-family default.

Supported operator presets are `10`, `30`, and `60` seconds. Custom cadence is allowed from `10` through `3600` seconds.

Values below `10` seconds are rejected. The product floor is intentionally stricter than historical internal scheduler intervals because the operator-facing contract must remain portable across the validated LOCAL_LAN topology and conservative until real hardware evidence proves a tighter envelope.

Priority remains part of scheduling only for ordering and bounded fairness among due jobs. Priority no longer determines recurring cadence.

## Backward-compatible migration

Persisted Acquisition Registry schema v1 migrates to schema v2 on startup.

Migration rules must never increase physical request rate relative to the previous policy:

- XJP60D inherits at least the former high-priority interval and never less than 10 seconds;
- LE-01MP inherits the former slowest applicable normal class so a device-scoped cadence does not silently accelerate low-priority metrics;
- the migration increments the registry revision and records a `system:migration` audit entry;
- subsequent restart does not repeat the migration or duplicate the audit event.

Discovery-only enrollment does not create polling load. A newly discovered device receives the applicable family default but remains non-polling until lifecycle activation.

## Local API

Read-only inspection:

```text
GET /api/v1/acquisition-cadence
```

The response includes:

- current registry revision;
- persisted family defaults and device overrides;
- effective per-device cadence and source;
- current capacity summary.

Mutation:

```text
PUT /api/v1/acquisition-cadence
```

A mutation requires:

- `expected_revision`;
- non-empty `reason`;
- one or more bounded family-default or device-override changes;
- audit actor from the existing authorized local control-plane header.

A device override can be removed by sending a null interval, returning the device to its inherited bus/family default.

The API performs no physical Modbus request merely because cadence is read or changed.

## Atomic pre-commit capacity validation

Every cadence mutation is evaluated against an immutable candidate registry before the SQLite transaction is committed.

A topology/lifecycle mutation is also capacity-validated when it adds new poll-eligible targets. Deactivation is never blocked by an already overloaded baseline because reducing load must always remain possible.

If capacity validation fails:

- the SQLite document is unchanged;
- registry revision is unchanged;
- no audit event is written;
- scheduler state is not reconciled to the rejected candidate;
- the API returns HTTP `422` with code `acquisition_capacity_exceeded` and a structured per-bus capacity summary.

Optimistic revision conflicts continue to return conflict semantics through the existing registry control plane.

## Capacity model

Capacity is calculated separately for every logical `bus_id`.

For each active device:

```text
estimated utilization = estimated work per acquisition pass / effective device interval
```

Bus utilization is the sum of its active device contributions.

The default maximum accepted estimated utilization is 75%, leaving a 25% safety margin for jitter, service operations and modeling uncertainty.

### Physical request accounting

The model follows production reader behavior:

- one XJP60D channel pass performs two FC03 requests: value + status;
- one LE-01MP metric pass performs one FC03 request, including the two-register cumulative-energy value because it is one contiguous FC03 transaction.

Disabled, reserve, retired, uninstalled, discovery-only and invalid targets add no recurring capacity demand.

### Request budget

Per-request budget includes:

- request latency evidence;
- configured retry allowance;
- retry reserve;
- Modbus RTU 3.5-character inter-frame silence;
- bounded scheduler overhead.

Cooldown is never treated as capacity credit. The model must remain safe even when all configured endpoints are healthy and polling at their requested cadence.

### Timing evidence authority

In legacy single-bus mode the profile is derived from local serial settings.

In explicit #607 multi-bus mode each configured binding contributes its own baud/parity/stopbits/timeout/retry values and bounded per-bus request metrics.

Measured p95 latency may reduce the conservative timeout fallback only after at least 20 physical request samples exist for that bus. Before that threshold, the configured serial timeout remains authoritative. This prevents one or a few unusually fast samples from approving an unsafe cadence.

## Scheduler reconciliation

After a successful registry commit, the adaptive scheduler reconciles from the new registry revision.

The scheduler:

- derives interval from persisted device cadence;
- keeps priority only for ordering/fairness;
- preserves one serialized worker per physical bus;
- resets the next deadline when a target cadence changes;
- preserves cooldown and no-catch-up behavior;
- never launches a burst for periods missed during restart or a cadence change.

Scheduler diagnostics expose the effective interval and the registry revision that supplied the cadence policy.

## Dual-bus behavior

The #607 topology binding remains authoritative for physical bus identity.

Cadence policy is rebound deterministically when a legacy `rs485-main` registry is composed into explicit KK1/KK2 logical buses. Device-specific overrides follow the device identity. A family default is copied to a new bus only when its source interval is unambiguous; conflicting values fail closed instead of being guessed.

Newly discovered XJP60D controllers retain the bus on which they were observed and receive a matching family default while remaining `discovery_only`.

## Offline and security boundaries

All cadence persistence, validation, audit and scheduling run locally with SQLite and existing Device Agent code.

No mandatory CDN, remote font, telemetry service, cloud API or paid runtime dependency is added.

Cadence control does not add:

- Modbus FC05/FC06/FC15/FC16 or any controller write;
- serial-port write/configuration workflow beyond normal read-only Modbus request framing;
- production/site cutover;
- automatic reassignment of unknown LE-01MP physical bus ownership.

## Verification

Targeted software evidence must cover at least:

- schema v1 to v2 migration and one-time audit;
- restart persistence;
- family-default and device-override precedence;
- custom interval floor/ceiling validation;
- optimistic revision conflict;
- audit actor/reason;
- XJP60D and LE-01MP physical request accounting;
- p95 evidence threshold and timeout fallback;
- safe and unsafe capacity outcomes;
- atomic rejection without revision/audit mutation;
- activation pre-check and unrestricted deactivation;
- scheduler reconcile after cadence change;
- cooldown/fairness/no-catch-up regressions;
- explicit dual-bus policy preservation and per-bus capacity profiles.

Required exact-head CI remains change-impact driven and includes every path-triggered Device Agent, Acquisition Scale, Edge, offline, security and Core workflow plus `NEXOLAB Merge Gate`.

## Hardware acceptance boundary

Software verification does not prove the actual safe site cadence.

Real hardware acceptance still requires read-only evidence from the intended Raspberry Pi, adapters and physical buses, including request latency/retries, scheduler lag, bus utilization, simultaneous KK1/KK2 operation and disconnect isolation. Until that evidence exists, the software capacity model remains conservative and hardware acceptance is reported as unverified.
