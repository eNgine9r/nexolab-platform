# NEXOLAB Current State

Updated: 2026-08-05
Verified product baseline: `d7affee11a39d5a007c461b9a4dea17f14b5bfb3`
Active control Work Package: Issue #321 — reconcile project state after Live Dashboard workspace merge
Branch: `chore/321-reconcile-live-dashboard-state`
Next Ready Work Package: Issue #289 — acquisition scale, stability and truthful live-state acceptance
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, persisted Live Dashboard CRUD, selected-series delivery, route-persistent telemetry, authenticated browser evidence and disconnected runtime; physical Raspberry Pi/RS-485 performance acceptance remains explicitly pending.

## Live Dashboard workspace completed

Issue #288 / PR #320 was squash-merged as `d7affee11a39d5a007c461b9a4dea17f14b5bfb3` from verified head `091b1698ff4005164e7409fb38af475128160f73`.

The merged `/live` product surface now provides:

- an organization-scoped persisted Live Dashboard library;
- search, archived visibility, create, edit, duplicate, archive and open workflows;
- authenticated `/api/v1/live-dashboards` contracts with ETag/If-Match concurrency;
- stale-writer recovery that preserves the local draft and offers server-version or save-as-copy paths;
- an editor-only canonical latest inventory with node, equipment, channel, metric, quality and alarm filters;
- duplicate prevention, deterministic ordering and a 64-item maximum;
- line, area, value and range-less gauge presentations;
- bounded refresh and time-window preferences that do not mutate acquisition;
- native-unit validation without fabricated unit conversion;
- read-only viewer behavior and `live_dashboards.manage` mutation gating;
- explicit library, loading, empty, forbidden, conflict, reconnecting, stale, offline, configuration and error states;
- organization/dashboard scope isolation so data from a previous tenant or definition cannot flash during changes.

The live view:

- loads only the saved `channel_id + metric` pairs;
- performs bounded selected `latest` and `history` REST reads;
- creates logical selected-series subscriptions over the shared application-shell WebSocket runtime;
- keeps one physical WebSocket maximum per authenticated telemetry scope;
- bounds history to 8,000 total samples and 500 samples per series;
- preserves retained values without relabelling stale or offline data as live;
- never calls Device Agent discovery/configuration or changes acquisition registry/scheduler state.

## Exact-head evidence for PR #320

- CI formatting, lint, typecheck, full tests and production build — GREEN;
- Authenticated Dashboard Acceptance — GREEN;
- Refrigeration Browser Acceptance — GREEN;
- Offline Bundle build, clean-host transfer simulation, blocked egress, `--pull never` startup, smoke, update/rollback and persistent-volume preservation — GREEN;
- focused diff: 16 frontend/test/acceptance files;
- backend, database migration, Device Agent, registry and scheduler files changed: zero;
- unresolved review threads: zero;
- branch behind `main` before merge: zero commits.

Authenticated persisted-dashboard evidence:

- a saved viewer dashboard remained available after Telemetry Service restart;
- viewer create/edit/archive controls were absent;
- opening the dashboard performed exactly one selected `latest` request for `106-03 + temperature.probe`;
- opening the dashboard performed exactly one selected `history` request for `106-03 + temperature.probe`;
- no broad inventory telemetry bootstrap occurred after opening the saved definition;
- maximum concurrent WebSockets: 1;
- Device Agent discovery/configuration mutations: 0.

Deterministic acquisition-invariant evidence remained stable at approximately 19.58–20.49 FC03 requests/second through no-browser, Overview, refresh, Live Dashboard, multiple browser contexts and WebSocket reconnect scenarios. This is software acceptance evidence, not final physical Raspberry Pi/RS-485 acceptance.

## Completed acquisition optimization sequence

- Issue #283 / PR #294 — physical FC03 request/retry/latency/outcome/utilization instrumentation.
- Issue #284 / PR #299 — canonical versioned active acquisition registry.
- Issue #285 / PR #305 — priority-aware adaptive scheduler and local acquisition latest-value cache.
- Issue #286 / PR #308 — persisted REST/WebSocket delivery isolated from physical acquisition.
- Issue #287 / PR #311 — persisted organization-scoped Live Dashboard definitions, ordered items, ETag concurrency, RBAC and audit API.
- Issue #314 / PR #315 — application-shell route-persistent telemetry snapshots and shared WebSocket lifecycle.
- Issue #316 / PR #317 — shared in-flight REST ownership, bounded transport/cache lifecycle and route-cycle request-count evidence.
- Issue #288 / PR #320 — persisted Live Dashboard library, editor and selected-series operator workspace.

## Next Ready validation Work Package

Issue #289 — Prove acquisition scale, stability and truthful live-state behavior.

The software validation scope is Ready because all product dependencies are merged. It must now document performance targets and run the reproducible scale matrix for:

- baseline and increased deterministic inventories;
- slow, unavailable and timeout-heavy endpoints;
- one and multiple authenticated browser contexts;
- Overview, Live Dashboard, Refrigeration, Energy and session-scoped telemetry concurrently;
- route transitions, WebSocket reconnect, Telemetry Service restart, MQTT interruption/outbox drain and disconnected LOCAL_LAN operation;
- truthful reconnecting, stale, offline, auth, permission and configuration states.

The real hardware gate remains pending and requires the controlled Raspberry Pi/RS-485 installation. Until that evidence exists, completion classification must remain:

```text
software verified; hardware performance acceptance pending
```

## Runtime and hardware evidence

```text
software verified; persisted Live Dashboard API and UI verified; selected-series REST/WebSocket delivery verified; route-persistent telemetry verified; disconnected update/rollback verified; physical Raspberry Pi/RS-485 performance, cameras and locker hardware unverified
```

## Approved blockers

- Physical RS-485 topology, final scheduler intervals, bus utilization, high-priority deadline acceptance, LE-01MP cumulative energy and extended XJP60D semantics remain hardware-dependent.
- `/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract and a defined operator workflow.
- Physical cameras, ONVIF/RTSP media and NVR remain unverified.
- The exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security` and expires on 2026-08-15 unless a fixed package becomes available first.

## Next action

Complete Issue #321 as a state-only four-file reconciliation. Then start Issue #289 with a documented performance target matrix and deterministic software acceptance. Execute the physical Raspberry Pi/RS-485 matrix only when the controlled hardware environment is available; do not perform Modbus writes or production/site cutover.
