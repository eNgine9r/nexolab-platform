# NEXOLAB active acquisition registry

## Purpose

The edge acquisition registry is the single source of truth for normal read-only Modbus polling eligibility. It separates **inventory visibility** from **physical bus work**.

A device, channel or metric may remain visible for commissioning, history, replacement or audit while consuming zero RS-485 time.

## Safety boundary

The registry can represent only:

- Modbus RTU buses marked `read_only=true`;
- function code `3` (`FC03` read holding registers);
- bounded register addresses from versioned NEXOLAB profiles;
- local acquisition lifecycle changes.

It cannot represent:

- FC05, FC06, FC15 or FC16;
- controller setpoint changes;
- Unit ID, baud, parity or other physical configuration changes;
- relay, output or lock commands;
- discovery as a normal polling target.

Updating registry eligibility changes only the local target set used by Device Agent.

## Schema and stable identity

Current schema version: `1`.

The registry contains:

- buses;
- devices;
- channel or metric targets;
- profile versions;
- lifecycle values;
- read-only function and register addresses;
- optimistic revision;
- local audit entries.

Stable IDs preserve current telemetry contracts:

```text
xjp60d-106                 device
xjp60d:106-03              registry target
106-03                     telemetry channel_id

le01mp-200                 device
le01mp:200-active-power    registry target
200-active-power           telemetry channel_id
```

Changing lifecycle does not rename historical telemetry, MQTT topics, equipment IDs or channel IDs.

## Lifecycle values

| Lifecycle        | Inventory visible |           Normal polling eligible           |
| ---------------- | :---------------: | :-----------------------------------------: |
| `active`         |        yes        | yes, when both device and target are active |
| `disabled`       |        yes        |                     no                      |
| `reserve`        |        yes        |                     no                      |
| `retired`        |        yes        |                     no                      |
| `uninstalled`    |        yes        |                     no                      |
| `discovery_only` |        yes        |                     no                      |
| `invalid`        |        yes        |                     no                      |

Effective eligibility is deliberately strict:

```text
device.lifecycle == active
AND target.lifecycle == active
AND function == FC03
```

Any other state emits zero normal-cycle requests.

## Migration

On first registry-managed startup, Device Agent creates the registry in the existing edge SQLite database.

Migration rules:

- current XJP60D `active_points` remain active;
- other catalogued XJP60D channels become `discovery_only`;
- configured LE-01MP Unit IDs and their current supported metrics become active;
- irrelevant device families are not added in single-family modes;
- duplicate `(bus, Unit ID)` identities across families are rejected;
- no existing SQLite table, telemetry record or outbox row is deleted;
- a `system:migration` audit entry records revision 1.

Subsequent restarts load the persisted registry and do not repeat migration.

## Local persistence

The existing edge SQLite database contains:

```text
acquisition_registry_state
acquisition_registry_audit
```

`acquisition_registry_state` stores one versioned document and revision.

Mutations use:

- `BEGIN IMMEDIATE`;
- `expected_revision` optimistic concurrency;
- one transaction for state and audit;
- rollback on any error.

A stale revision returns conflict and does not create an audit entry.

## Local endpoints

### Read registry

```http
GET /api/v1/acquisition-registry
```

Returns sanitized inventory, lifecycle, eligibility, summary and recent audit data. It contains no secrets, raw Modbus frames or production measurements.

### Update eligibility

```http
PUT /api/v1/acquisition-registry
Content-Type: application/json
X-NEXOLAB-Actor: organization:<id>:equipment.manage
```

Example:

```json
{
  "expected_revision": 4,
  "reason": "Move unused meter metric to reserve",
  "devices": [],
  "targets": [
    {
      "target_id": "le01mp:200-active-power",
      "lifecycle": "reserve"
    }
  ]
}
```

The local endpoint accepts only known devices and targets, supported lifecycle values and a bounded mutation set.

The Next.js loopback proxy is:

```text
GET /api/device-agent/acquisition-registry
PUT /api/device-agent/acquisition-registry
```

Permissions:

- GET: `dashboard.read`;
- PUT: `equipment.manage`.

The proxy permits only loopback HTTP Device Agent endpoints and passes a bounded non-secret audit actor.

## XJP60D compatibility

The existing `/api/v1/xjp60d/configuration` contract remains available.

Its `active_points` list is projected from registry eligibility. A legacy active-point update is translated into registry lifecycle changes and is audited. The compatibility layer does not overwrite explicit `reserve`, `retired`, `uninstalled` or `invalid` states unless the operator intentionally reactivates that target.

Discovery remains a separate service operation and is not inserted into the normal polling loop.

## Health and metrics

`/health` and `/ready` include an `acquisition_registry` summary:

- schema version;
- revision;
- inventory devices;
- inventory targets;
- poll-eligible targets;
- lifecycle counts.

`/metrics` continues to report actual physical request counters. These counters are the acceptance source for proving that a non-active target produces zero normal-cycle Modbus requests.

## Software verification

Required checks:

- migration preserves existing XJP60D active points;
- LE-01MP metrics can be excluded individually;
- all non-active lifecycle values yield zero eligible targets;
- device-level non-active lifecycle suppresses all child targets;
- write-capable functions are rejected;
- duplicate bus/Unit identities are rejected;
- revision conflict does not mutate state or audit;
- restart preserves revision and target set;
- normal sampling calls only registry-eligible readers;
- permission-gated proxy denies unauthorized mutation;
- CI, Device Agent fleet, image, supply-chain and disconnected bundle gates pass.

## Physical hardware acceptance

Physical acceptance remains separate and read-only:

1. capture `/metrics` over several completed cycles;
2. choose an approved non-critical test target;
3. change only its registry lifecycle from `active` to `disabled` or `reserve`;
4. capture the same number of completed cycles;
5. confirm its normal request counter delta becomes zero;
6. confirm unrelated active targets keep their expected scheduler envelope;
7. reactivate the test target through the registry;
8. confirm polling resumes;
9. verify no Modbus write frame occurred.

Do not perform this procedure on production/site hardware without the separately approved hardware acceptance scope.
