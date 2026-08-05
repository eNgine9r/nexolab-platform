# Persisted Live Dashboard domain

Issue: #287  
Profile: `LOCAL_LAN`  
Runtime rule: local persistence, no acquisition side effects

## Decision

Live Dashboards are organization-scoped operator configuration stored in PostgreSQL.
They select canonical measurement channels but do not define, enable, prioritize or
schedule physical acquisition.

```text
canonical measurement catalog
          ↓ validation only
live_dashboards + ordered live_dashboard_items
          ↓ read/write local API
future Live Dashboard editor
          ↓ latest/history delivery queries
PersistedTelemetryReadModel
```

The physical path remains independent:

```text
active acquisition registry
          ↓
Device Agent adaptive scheduler
          ↓
read-only FC03 acquisition
```

No dashboard field is an input to registry eligibility, scheduler priority, physical
deadlines or Modbus bus work.

## Domain contract

A dashboard stores:

- stable ID and organization ID;
- name and optional description;
- owner subject and audit identities;
- active or archived lifecycle state;
- ordered canonical channel selections;
- visualization type: `line`, `area`, `gauge` or `value`;
- display refresh preference: `1`, `2`, `5`, `10`, `15`, `30` or `60` seconds;
- time window: `5m`, `15m`, `30m`, `1h`, `6h`, `12h`, `24h` or `7d`;
- optional six-digit hexadecimal color;
- display unit only when it equals the canonical native unit;
- optimistic concurrency version.

A dashboard contains at most 64 ordered items. The API accepts pages of at most 100
dashboards and an offset no greater than 10,000.

## Canonical channel validation

Each item resolves `channel_id` against the organization-scoped measurement catalog.
The channel, device, bus, climate chamber and central node must remain eligible:

- channel, device, bus and chamber status are `active`;
- the central node is not revoked;
- requested metric equals the channel's canonical `metric_type`;
- requested display unit is either absent or equal to the native unit.

Unknown, cross-organization or inactive identities are returned as
`live_dashboard_channel_not_found`. Metric mismatches and unsupported unit
conversions have separate explicit errors.

Validation reads catalog state only. It does not reconcile the acquisition registry.

## API

```text
GET    /api/v1/live-dashboards
POST   /api/v1/live-dashboards
GET    /api/v1/live-dashboards/{dashboard_id}
PUT    /api/v1/live-dashboards/{dashboard_id}
DELETE /api/v1/live-dashboards/{dashboard_id}
```

`DELETE` archives the dashboard. It never deletes telemetry, equipment, channel
inventory or historical samples.

Create returns `Location` and `ETag`. Read and update return `ETag`. Update and
archive require:

```text
If-Match: W/"live-dashboard-vN"
```

A stale writer receives HTTP 409 with expected and actual versions. A missing or
malformed precondition receives HTTP 428.

## Authorization and audit

All endpoints require `dashboard.read`. Mutations require the explicit
`live_dashboards.manage` permission. Administrators, laboratory managers, engineers
and operators receive that permission. Viewers and auditors remain read-only.

Mutations append atomic security audit events:

- `live_dashboard.created`;
- `live_dashboard.updated`;
- `live_dashboard.archived`.

Snapshots include dashboard identity, ordered items and display preferences, but no
credentials or telemetry payloads.

## Offline and hardware boundary

The domain uses the local telemetry-service database and existing local
authentication. It adds no CDN, remote font, telemetry SDK, cloud realtime service
or paid runtime dependency.

Software verification can prove that dashboard CRUD does not import or invoke
scheduler, registry, Modbus or hardware-driver code. Physical request-counter
comparison remains part of Issue #289 and cannot be claimed from software tests.
