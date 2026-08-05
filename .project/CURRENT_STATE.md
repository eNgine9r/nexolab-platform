# NEXOLAB Current State

Updated: 2026-08-05
Verified product baseline: `894884fb9a0fc6ad807206ed2fc087d68226346f`
Active control Work Package: Issue #309 — reconcile project state after telemetry delivery isolation
Branch: `docs/309-reconcile-telemetry-delivery-state`
Next Ready Work Package: Issue #287 — persisted Live Dashboard domain and local API
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, persisted telemetry delivery, deterministic scheduler/registry tests, authenticated acquisition invariants, secure fleet operation and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Telemetry delivery isolation completed

Issue #286 / PR #308 was squash-merged as `894884fb9a0fc6ad807206ed2fc087d68226346f` from verified head `8f8842bfac37e696989ad00a3074844b41de2736`.

The merged delivery plane now:

- serves REST latest/history through a dedicated persisted telemetry read model;
- replays WebSocket history from committed database rows;
- fans out only events that completed successful idempotent persistence;
- exposes the live publication boundary explicitly as `publish_committed`;
- exposes `received_at`, `age_seconds`, source quality and `state_source: persisted`;
- preserves a source-owned `stale_after_seconds` threshold when present;
- reports staleness as `unknown` when no source threshold exists instead of inventing freshness;
- proves repeated REST refreshes and WebSocket reconnect/client churn create no ingestion or persistence activity;
- statically forbids delivery modules from depending on the scheduler, acquisition registry, Modbus transport or hardware drivers;
- statically forbids scheduler and registry code from accepting client-subscription inputs.

The Device Agent remains the sole owner of registry eligibility, priority, deadlines, serialized physical bus work and FC03 hardware cadence.

## Exact-head verification

- CI `31000543504` GREEN;
- Telemetry service `31000543552` GREEN;
- Device Agent Fleet Acceptance `31000543513` GREEN;
- Authenticated Dashboard Acceptance `31000543599` GREEN;
- Offline Auth Acceptance `31000543518` GREEN;
- MQTT TLS Fleet Acceptance `31000543557` GREEN;
- Broker Control Acceptance `31000543548` GREEN;
- Security Browser Acceptance `31000543616` GREEN;
- Capacity Release Gate `31000543535` GREEN;
- Edge image `31000543536` GREEN;
- Container Supply Chain `31000543545` GREEN;
- Disaster Recovery TLS Fleet `31000543529` GREEN;
- Disaster Recovery Browser `31000543530` GREEN;
- Offline Bundle `31000543512` GREEN;
- focused diff: 9 telemetry-service/device-agent-test/docs files;
- inline review threads: zero;
- submitted reviews: zero;
- branch behind main before merge: zero commits.

Initial Offline Auth run `31000100012` failed immediately after the base PostgreSQL image pull. The exact-head rerun completed migration upgrade/downgrade and disconnected authentication successfully in `31000543518`, classifying the first result as transient runner/image-pull failure rather than a product regression.

## Completed acquisition foundations

- Issue #283 / PR #294 provides objective physical FC03 request, retry, latency, outcome and utilization instrumentation.
- Issue #284 / PR #299 provides the canonical versioned active acquisition registry and atomic local eligibility/audit persistence.
- Issue #285 / PR #305 provides the priority-aware adaptive scheduler, one serialized worker per bus, monotonic deadlines, fairness, cooldown and local acquisition latest-value cache.
- Issue #286 / PR #308 now isolates persisted REST/WebSocket delivery from physical acquisition.
- Issue #295 / PR #296 upgraded `cryptography` to the fixed 50.x line. One exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security` and expires on 2026-08-15.

## Active architecture sequence

Epic #282 continues in dependency order:

1. #287 — persisted Live Dashboard domain and local API;
2. #288 — Live Dashboard editor and channel-scoped operator workspace;
3. #289 — scale, stability and truthful live-state acceptance.

Issue #287 is Ready because REST and WebSocket consumers now read persisted telemetry state without changing registry eligibility, scheduler priority or physical cadence.

## Runtime and hardware evidence

```text
software verified; persisted delivery isolation verified; deterministic scheduler/registry tests verified; authenticated acquisition invariant verified; secure fleet verified; disconnected update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Approved blockers

- `/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract and a defined operator workflow.
- Physical RS-485 topology, final scheduler intervals, bus utilization, high-priority deadline acceptance, LE-01MP cumulative energy and extended XJP60D semantics remain hardware-dependent.
- Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Next action

Complete Issue #309 as a four-file state-only reconciliation, then start Issue #287 on a dedicated feature branch. Dashboard persistence may store organization-scoped definitions and canonical channel selections, but must not influence acquisition registry eligibility or scheduler priority.
