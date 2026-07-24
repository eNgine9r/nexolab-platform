# ADR 0005: Laboratory test session domain

- Status: Accepted
- Date: 2026-07-24
- Issues: #74, #75

## Context

M3 established a production telemetry path from `edge-01` through MQTT, the Telemetry Service, PostgreSQL, REST/WebSocket and the NEXOLAB dashboard. M4 must add a laboratory workflow without weakening the proven acquisition path or rewriting historical telemetry.

A test session must describe the test object, standard, personnel, assigned channels, limits, sampling policy and ordered workflow stages. Lifecycle commands can be retried after browser, network or service failures, so transitions must be deterministic and idempotent.

The production input remains:

- node `edge-01`;
- XJP60D channels `106-03`, `106-04`;
- LE-01MP units `200`, `201`, `202`, `203`;
- 34 telemetry series per complete polling cycle.

## Decision

### Domain ownership

The Telemetry Service owns the canonical session domain because it already owns durable telemetry persistence, REST/WebSocket contracts and PostgreSQL migrations.

The Device Agent remains responsible only for Modbus polling, local buffering and MQTT publication. Session state must not change its mode, serial path, register profiles or polling cadence.

The session state machine is implemented as a pure Python domain module without FastAPI, SQLAlchemy or MQTT dependencies. Persistence and API adapters invoke the domain module rather than duplicating transition rules.

### Session lifecycle

Canonical states:

```text
draft → ready → running ⇄ paused → completed → archived
   ↘       ↘                 ↘              
cancelled ←──────────────────┘
   ↓
archived
```

Allowed transition commands:

| Current state | Command    | Next state  | Event               |
| ------------- | ---------- | ----------- | ------------------- |
| `draft`       | `prepare`  | `ready`     | `session_prepared`  |
| `draft`       | `cancel`   | `cancelled` | `session_cancelled` |
| `ready`       | `start`    | `running`   | `session_started`   |
| `ready`       | `cancel`   | `cancelled` | `session_cancelled` |
| `running`     | `pause`    | `paused`    | `session_paused`    |
| `running`     | `complete` | `completed` | `session_completed` |
| `paused`      | `resume`   | `running`   | `session_resumed`   |
| `paused`      | `cancel`   | `cancelled` | `session_cancelled` |
| `completed`   | `archive`  | `archived`  | `session_archived`  |
| `cancelled`   | `archive`  | `archived`  | `session_archived`  |

A running session cannot be cancelled directly. The operator must pause it first, making the workflow interruption explicit before cancellation.

Cancellation requires a non-empty reason. Other transition reasons are optional at the domain layer and may be required by later policy or authorization layers.

Invalid transitions return stable domain error codes instead of relying on database or HTTP errors.

### Immutability

Scientific/configuration content is immutable after `completed`, `cancelled` or `archived`.

Archiving a completed or cancelled session changes only the lifecycle state. It must not change:

- test metadata;
- channel bindings;
- configuration snapshots;
- limit versions;
- stages or timestamps;
- telemetry records;
- audit events.

Before start, configuration is mutable only in `draft` and `ready`. Changes during `running` or `paused` require dedicated audited commands and new versions; they are not generic edits.

### Telemetry semantics

Telemetry attribution is active in both:

```text
running
paused
```

`paused` means that the laboratory workflow clock and stage progression are paused. It does not stop Modbus polling, MQTT publication, persistence or session attribution.

Telemetry captured in `draft`, `ready`, `completed`, `cancelled` or `archived` is not attributed to that session.

Later persistence work must bind each attributed record to immutable identifiers for:

- session;
- stage occurrence;
- channel binding;
- configuration snapshot;
- limit version.

Raw value, normalized value, quality, alarm and capture timestamp remain unchanged.

### Stage model

Canonical stage names are:

```text
Preparation
Preconditioning
Stabilization
Main Test
Defrost
Recovery
Completion
Report
```

A session stores an ordered stage plan. Stage occurrences are addressed by plan index rather than only by stage name, allowing a method to repeat stage names such as Defrost and Recovery.

Stage progression rules:

- the first entered index is `0`;
- each transition advances exactly to the next configured index;
- stages cannot be skipped or moved backwards;
- stage progression is allowed only while the session is `running`;
- pausing freezes the current stage but telemetry attribution continues.

A later API may provide an explicit audited override for exceptional methods, but the default domain transition remains sequential.

### Transition command contract

Every lifecycle command contains:

- `idempotency_key` — non-empty, maximum 128 characters;
- `actor_id` — non-empty, maximum 128 characters;
- timezone-aware `occurred_at`;
- optional `reason` — maximum 2000 characters.

The database layer introduced in #76 must enforce uniqueness of the idempotency key within a session. Repeating the same command returns the original event/result rather than applying another transition.

### Error contract

The initial stable domain error codes are:

| Code                          | Meaning                                              |
| ----------------------------- | ---------------------------------------------------- |
| `invalid_transition_command`  | malformed actor, key, timestamp or reason            |
| `transition_reason_required`  | cancellation was requested without a reason          |
| `invalid_session_transition`  | command is not allowed from the current active state |
| `session_immutable`           | mutation was attempted on a terminal session         |
| `invalid_stage_plan`          | configured stage plan is empty or invalid            |
| `invalid_stage_transition`    | stage entry is out of order or workflow is not live  |

API adapters will map these codes to typed HTTP error responses without changing their meaning.

## Consequences

Positive:

- one lifecycle contract for database, API and frontend;
- deterministic transition validation before persistence;
- retries can be made safe through idempotency;
- pause semantics preserve telemetry continuity;
- stage occurrences support repeated method stages;
- session workflow remains isolated from Modbus acquisition.

Trade-offs:

- running sessions require pause before cancellation;
- generic configuration editing ends at start;
- stage progression is sequential unless a future audited override is added;
- persistence, REST endpoints, authorization and frontend workflow remain separate issues #76–#82.

## Validation

Issue #75 is accepted when:

- every allowed transition has a unit test;
- every other state/action pair is rejected;
- terminal-state immutability is tested;
- pause telemetry semantics are tested;
- stage ordering and pause restrictions are tested;
- transition command validation is tested;
- telemetry-service CI passes.
