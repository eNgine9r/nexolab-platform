# Adaptive Acquisition Scheduler

## Purpose

The adaptive scheduler executes only read-only Acquisition Registry targets and protects each physical RS-485 bus with one serialized worker.

After Issue #589, recurring cadence is no longer owned by priority classes. The durable Acquisition Registry is the cadence authority. Scheduler priority remains only an ordering and bounded-fairness mechanism among jobs that are already due.

This runtime performs no Modbus writes, browser-driven polling or mandatory cloud synchronization.

## Eligibility boundary

Only targets for which both the registry device and registry target have lifecycle `active` enter normal scheduling. Normal acquisition remains FC03 read-only.

Inventory targets in `disabled`, `reserve`, `retired`, `uninstalled`, `discovery_only` or `invalid` remain visible but create no recurring scheduler job.

A successful registry mutation reconciles scheduler state only after the atomic SQLite transaction commits. Deactivation always remains possible even when the existing capacity baseline is unsafe.

## Cadence authority

Cadence is persisted in Acquisition Registry schema v2.

Effective cadence precedence is:

1. device override;
2. bus + device-family default.

Supported operator presets are `10`, `30` and `60` seconds. Custom values are accepted from `10` through `3600` seconds.

The scheduler exposes `cadence_policy_revision` so diagnostics identify the registry revision that supplied the current intervals.

Priority mapping remains:

- `high`: XJP60D temperature/status targets;
- `medium`: operational LE-01MP metrics;
- `low`: slower LE-01MP diagnostics;
- `on_demand`: explicit discovery/configuration operations.

Priority does **not** change the configured polling interval.

Legacy `ACQUISITION_HIGH_INTERVAL_SECONDS`, `ACQUISITION_MEDIUM_INTERVAL_SECONDS` and `ACQUISITION_LOW_INTERVAL_SECONDS` remain relevant only to backward-compatible v1→v2 bootstrap semantics and the internal priority policy object. They are not an operator cadence control after migration.

See `docs/architecture/persisted-acquisition-cadence.md` for persistence, API, migration and capacity-validation rules.

## Deadline and fairness model

Each registry-eligible target receives an explicit persisted interval and monotonic next deadline.

Selection rules on each bus are:

1. choose the highest-priority due target;
2. within a class, choose the oldest effective deadline;
3. after the configured high-priority burst, force a due non-high target;
4. after the configured non-low burst, force the oldest due low target.

A deadline advances from its prior monotonic value rather than completion time. When a read finishes after one or more future intervals, expired occurrences are counted as skipped and the job advances to the next future deadline. The scheduler never performs catch-up bursts.

When a persisted cadence changes, reconcile installs the new interval and computes a new bounded next deadline instead of replaying historical missed periods.

## Bus serialization and multi-bus isolation

Every normal worker and explicit service operation uses the operation lock for its physical `bus_id`.

In legacy mode there is one `rs485-main` bus. In explicit #607 topology mode KK1 and KK2 own distinct transports, readers and locks, so requests remain serialized within one bus while different buses may execute concurrently.

Opening Overview, Live Data, REST or WebSocket consumers does not create scheduler jobs or alter physical polling cadence.

## Capacity validation

Cadence changes and newly poll-eligible activations are validated **before** SQLite commit.

The capacity model is per bus and conservatively accounts for:

- production physical request count per target pass;
- serial timeout or sufficiently sampled measured p95 latency;
- configured retry allowance and reserve;
- Modbus RTU inter-frame silence;
- bounded scheduler overhead;
- heterogeneous per-device cadence.

The accepted estimated utilization ceiling is 75%, retaining a 25% safety margin. Cooldown is never counted as spare capacity.

Measured p95 may replace the timeout fallback only after at least 20 physical request samples exist for that bus.

Unsafe changes fail with structured `acquisition_capacity_exceeded` evidence and leave registry revision, audit and scheduler state unchanged.

## Cooldown and circuit breaker

Communication failure state is tracked by `(bus_id, unit_id)`.

When consecutive communication failures reach the configured threshold:

- the endpoint enters cooldown;
- all normal jobs for that Unit ID are deferred;
- other Unit IDs remain eligible;
- cooldown grows exponentially to its configured maximum;
- a successful post-cooldown read resets failure state.

A sensor-quality value such as `sensor_error` is a successful communication attempt and does not trip the communication circuit breaker.

## Latest-value cache

The local SQLite `acquisition_latest_values` read model preserves the last successful value while separately recording current communication quality and attempt metadata.

On communication failure the prior successful value and `captured_at` remain available while `quality`, `last_attempt_at` and `last_error` reflect the current failure.

Read-only local endpoint:

```text
GET /api/v1/acquisition-latest
```

Reading diagnostics or latest values never causes a Modbus request.

## Restart behavior

At startup jobs are deterministically spread across the bounded startup window. A recent persisted last-attempt timestamp delays the first deadline by the remaining effective device interval.

Restart does not trigger:

- a full discovery scan;
- one immediate request per inventory target;
- a catch-up burst for downtime.

Persisted cadence itself is loaded from Acquisition Registry schema v2 and survives restart independently of browser state.

## Metrics and health evidence

`/metrics`, `/health` and `/ready` include acquisition scheduler evidence for:

- current registry cadence revision;
- effective target intervals;
- target priorities;
- worker state per bus;
- queue depth and executions;
- communication failures and callback errors;
- missed/skipped deadlines and overruns;
- cooldown and fairness counters;
- scheduler lag and rolling bus-load evidence.

Explicit dual-bus diagnostics additionally expose bounded physical request count/rate, retries/timeouts/errors and recent latency average/p95/max for each logical bus.

No secret labels or remote telemetry dependency are introduced.

## Local control plane

Cadence inspection and mutation are local Device Agent operations:

```text
GET /api/v1/acquisition-cadence
PUT /api/v1/acquisition-cadence
```

Mutation uses the existing registry revision/audit boundary and is capacity-validated before commit.

## Verification

Targeted software checks include the Device Agent unit suite and deterministic acquisition scale matrix. Exact-head completion also requires every path-triggered Edge, authenticated acquisition-invariant, offline, security and Core workflow plus `NEXOLAB Merge Gate`.

Software checks prove deterministic scheduling behavior, persistence and conservative capacity rejection. They do not prove the actual site bus can sustain a selected cadence.

## Hardware acceptance boundary

Physical acceptance remains pending until real read-only evidence is collected from the intended Raspberry Pi, adapters and RS-485 topology.

Required evidence includes:

- per-bus request latency and retries;
- bus utilization and scheduler lag;
- simultaneous KK1/KK2 polling;
- behavior with an absent/slow endpoint;
- one-bus disconnect isolation;
- confirmation that UI activity does not change physical request rate.

No Modbus/controller write or production/site cutover is part of this Work Package.
