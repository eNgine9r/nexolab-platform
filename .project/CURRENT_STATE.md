# NEXOLAB Current State

Updated: 2026-08-05
Verified product baseline: `b4660b15b49ff6e2776ea6adb4f0cea1e3f9ece0`
Active control Work Package: Issue #318 — reconcile project state after telemetry route-persistence merges
Branch: `chore/318-reconcile-telemetry-state`
Next Ready Work Package: Issue #288 — Live Dashboard editor and channel-scoped operator workspace
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, persisted Live Dashboard API, route-persistent telemetry delivery, REST deduplication, bounded WebSocket/cache lifecycle, authenticated request-count evidence and disconnected runtime; physical Raspberry Pi/RS-485 acceptance remains explicitly unverified.

## Route-persistent telemetry delivery completed

Issue #314 / PR #315 was squash-merged as `0b55fef9c2f41670339248d132b51dd4d67d44d5`.

The merged frontend delivery layer:

- keeps canonical latest telemetry snapshots in the application-shell scope across route transitions;
- shares one organization-scoped physical WebSocket across Overview, Live Data and Energy consumers;
- replays retained samples to newly mounted routes without blanking previously usable values;
- preserves age, quality, stale, reconnecting and offline semantics instead of relabelling retained data as live;
- keeps physical acquisition, registry eligibility and scheduler cadence independent of UI subscriptions.

A post-merge audit identified unproven acceptance details. Corrective Issue #316 / PR #317 was therefore completed and squash-merged as `b4660b15b49ff6e2776ea6adb4f0cea1e3f9ece0` from verified head `c8ae44983c97fe108710d2d294c390b4dabfb2c2`.

The corrective slice additionally:

- deduplicates simultaneous identical `latest` and `history` REST requests per authenticated telemetry scope;
- preserves independent consumer abort semantics and aborts the physical request only after the final consumer releases it;
- removes settled and failed in-flight entries deterministically;
- applies a 5-second zero-consumer route-transition grace interval to the physical WebSocket;
- retains canonical latest snapshots for a separate bounded 15-minute idle TTL;
- limits persistent in-memory state to 20,000 canonical samples and 128 exact latest-query snapshots;
- derives narrower latest views only from complete broad snapshots where `next_offset` is `null`;
- closes/evicts idle organization-scoped clients and timers deterministically.

## Exact-head evidence for PR #317

- CI formatting, lint, typecheck, full tests and production build — GREEN;
- Authenticated Dashboard Acceptance — GREEN;
- Refrigeration Browser Acceptance — GREEN;
- Offline Bundle clean transfer, blocked egress, `--pull never` startup, smoke, update/rollback and persistent-volume preservation — GREEN;
- focused diff: 11 product/test/acceptance files;
- inline review threads: zero;
- branch behind `main` before merge: zero commits.

Authenticated route-cycle evidence for Overview → Refrigeration → Energy → Overview:

- Refrigeration usable: 354 ms;
- Energy usable: 203 ms;
- Overview usable after return: 226 ms;
- telemetry `latest` REST requests: 1;
- telemetry `history` REST requests: 3;
- WebSockets opened: 1;
- maximum concurrent WebSockets: 1;
- WebSockets closed during the route cycle: 0;
- Device Agent discovery/configuration mutations: 0.

The authenticated acquisition invariant remained stable at approximately 19.49–20.28 physical FC03 requests/second through browser-open, refresh, Live Data, multiple browser contexts and WebSocket reconnect scenarios. This is deterministic acceptance evidence, not final physical Raspberry Pi/RS-485 acceptance.

## Completed acquisition and Live Dashboard foundations

- Issue #283 / PR #294 — physical FC03 request/retry/latency/outcome/utilization instrumentation.
- Issue #284 / PR #299 — canonical versioned active acquisition registry.
- Issue #285 / PR #305 — priority-aware adaptive scheduler and local acquisition latest-value cache.
- Issue #286 / PR #308 — persisted REST/WebSocket delivery isolated from physical acquisition.
- Issue #287 / PR #311 — persisted organization-scoped Live Dashboard definitions, ordered items, ETag concurrency, RBAC and audit API.
- Issue #314 / PR #315 — application-shell route-persistent telemetry snapshots and shared WebSocket lifecycle.
- Issue #316 / PR #317 — shared in-flight REST ownership, bounded transport/cache lifecycle and route-cycle request-count evidence.

## Active architecture sequence

Epic #282 continues in dependency order:

1. #288 — Live Dashboard editor and channel-scoped operator workspace;
2. #289 — scale, stability and truthful live-state acceptance, including real Raspberry Pi/RS-485 request-count and latency evidence.

Issue #288 is Ready because the local API persists dashboard definitions and #314/#316 now provide a bounded application-shell telemetry runtime that can request and subscribe only to selected canonical channels.

## Runtime and hardware evidence

```text
software verified; Live Dashboard PostgreSQL/API/RBAC/audit verified; route-persistent telemetry delivery verified; REST deduplication and bounded lifecycle verified; authenticated browser/request-count evidence verified; disconnected update/rollback verified; physical Raspberry Pi/RS-485, cameras and locker hardware unverified
```

## Approved blockers

- `/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract and a defined operator workflow.
- Physical RS-485 topology, final scheduler intervals, bus utilization, high-priority deadline acceptance, LE-01MP cumulative energy and extended XJP60D semantics remain hardware-dependent.
- Physical cameras, ONVIF/RTSP media and NVR remain unverified.
- The exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security` and expires on 2026-08-15 unless a fixed package becomes available first.

## Next action

Complete Issue #318 as a state-only four-file reconciliation, then start Issue #288 on a dedicated feature branch. The Live Dashboard library/editor/workspace must use `/api/v1/live-dashboards` and the shared telemetry runtime, request only selected canonical series, preserve optimistic-concurrency conflicts and unsaved local changes, and never mutate physical acquisition.
