# NEXOLAB Current State

Updated: 2026-08-05
Verified product baseline: `e92c36fe1b863f25132ecb39fe7f46928742c470`
Active control Work Package: none
Branch: `main`
Next Ready Work Package: Issue #288 — Live Dashboard editor and channel-scoped operator workspace
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, persisted telemetry delivery, Live Dashboard persistence/API, deterministic scheduler/registry tests, authenticated acquisition invariants, secure fleet operation and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Persisted Live Dashboard domain completed

Issue #287 / PR #311 was squash-merged as `e92c36fe1b863f25132ecb39fe7f46928742c470` from verified head `58f03b107cb900c7436b6784d27a305a1bccc4a4`.

The merged local domain now:

- stores organization-scoped Live Dashboard definitions in PostgreSQL migration `20260805_0022`;
- stores ordered canonical channel selections with a maximum of 64 items per dashboard;
- validates channel identity, metric and native unit against active organization-scoped catalog records;
- persists bounded visualization, refresh and time-window preferences without changing acquisition cadence;
- exposes authenticated list/create/read/update/archive endpoints under `/api/v1/live-dashboards`;
- uses weak ETags in the form `W/"live-dashboard-vN"` and requires `If-Match` for update/archive;
- rejects stale writers with explicit expected and actual versions;
- grants `live_dashboards.manage` to administrator, laboratory manager, engineer and operator roles while viewer/auditor remain read-only;
- records atomic `created`, `updated` and `archived` security audit events;
- archives instead of hard-deleting dashboards, preserving telemetry, channel inventory and equipment configuration;
- provides deterministic page-size, offset, name, payload and item-count limits;
- contains static tests proving dashboard code has no scheduler, acquisition-registry, Modbus or hardware-driver dependency.

`refresh_seconds` and `time_window` are display/query preferences only. The Device Agent remains the sole owner of registry eligibility, priority, deadlines, serialized bus work and physical FC03 cadence.

## Exact-head verification

- CI `31006749777` GREEN;
- Telemetry service `31006750030` GREEN;
- Authenticated Dashboard Acceptance `31006749792` GREEN;
- Offline Auth Acceptance `31006749749` GREEN after isolated rerun of a transient migration-harness startup failure;
- Offline Bundle `31006750129` GREEN;
- Device Agent Fleet Acceptance `31006749753` GREEN;
- MQTT TLS Fleet Acceptance `31006750185` GREEN;
- Broker Control Acceptance `31006750302` GREEN;
- Capacity Release Gate `31006749756` GREEN;
- Container Supply Chain `31006749998` GREEN;
- Security Browser Acceptance `31006749943` GREEN;
- Nodes Browser Acceptance `31006749809` GREEN;
- Alerts Browser Acceptance `31006750146` GREEN;
- Refrigeration Browser Acceptance `31006750013` GREEN;
- Test Sessions Browser Acceptance `31006750194` GREEN;
- Reports Browser Acceptance `31006750027` GREEN;
- Rendered Reports Browser Acceptance `31006750023` GREEN;
- Disaster Recovery Browser `31006749921` GREEN;
- Disaster Recovery TLS Fleet `31006750063` GREEN;
- focused diff: 18 product/test/acceptance/docs files;
- inline review threads: zero;
- submitted reviews: zero;
- branch behind `main` before merge: zero commits.

Compatibility verification additionally proved:

- the local-auth migration harness resolves the current single Alembic head rather than hardcoding the previous head;
- rendered-report acceptance remains retry-safe while preserving consecutive version semantics;
- the frontend authenticated-session parser accepts `live_dashboards.manage` as an effective backend permission without expanding the Settings UI.

## Completed acquisition and delivery foundations

- Issue #283 / PR #294 provides objective physical FC03 request, retry, latency, outcome and utilization instrumentation.
- Issue #284 / PR #299 provides the canonical versioned active acquisition registry and atomic local eligibility/audit persistence.
- Issue #285 / PR #305 provides the priority-aware adaptive scheduler, one serialized worker per bus, monotonic deadlines, fairness, cooldown and local acquisition latest-value cache.
- Issue #286 / PR #308 isolates persisted REST/WebSocket delivery from physical acquisition.
- Issue #287 / PR #311 provides persisted Live Dashboard definitions and a local permission-aware API without acquisition side effects.
- Issue #295 / PR #296 upgraded `cryptography` to the fixed 50.x line. One exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security` and expires on 2026-08-15.

## Active architecture sequence

Epic #282 continues in dependency order:

1. #288 — Live Dashboard editor and channel-scoped operator workspace;
2. #289 — scale, stability and truthful live-state acceptance.

Issue #288 is Ready because persisted organization-scoped dashboard CRUD, ordered canonical items, ETag concurrency, role permissions and audit history are now available through the local API.

## Runtime and hardware evidence

```text
software verified; Live Dashboard PostgreSQL/API/RBAC/audit verified; persisted delivery isolation verified; authenticated acquisition invariant verified; secure fleet verified; disconnected update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Approved blockers

- `/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract and a defined operator workflow.
- Physical RS-485 topology, final scheduler intervals, bus utilization, high-priority deadline acceptance, LE-01MP cumulative energy and extended XJP60D semantics remain hardware-dependent.
- Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Next action

Start Issue #288 on a dedicated feature branch. The editor and live workspace must use the persisted API and request only selected telemetry channels; display preferences, filters and reconnects must never mutate registry eligibility, scheduler priority or physical polling cadence.
