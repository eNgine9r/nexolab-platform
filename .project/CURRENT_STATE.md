# NEXOLAB Current State

Updated: 2026-08-05
Verified product baseline: `4d9300a87e497b13d1d9fcabc479df781bcc8505`
Active control Work Package: none
Branch: `main`
Next Ready Work Package: Issue #286 — isolate REST and WebSocket subscriptions from physical acquisition
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, deterministic scheduler/registry tests, authenticated browser invariants, secure fleet operation and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Priority-aware adaptive acquisition scheduler completed

Issue #285 / PR #305 was squash-merged as `4d9300a87e497b13d1d9fcabc479df781bcc8505` from verified head `54d49f422723b52a41feff307023a299f27e3a92`.

The merged hardware Device Agent now:

- derives recurring normal jobs only from registry-eligible read-only FC03 targets;
- runs one serialized worker per registry bus and reuses the same bus lock for explicit service operations;
- assigns explicit `high`, `medium` and `low` priorities while discovery/configuration remain on demand;
- uses monotonic target deadlines, deterministic startup staggering and no catch-up bursts;
- forces bounded non-high and low-priority fairness;
- applies bounded endpoint cooldown after repeated communication failures without blocking other Unit IDs;
- persists a local SQLite latest-value read model that preserves the last successful value and timestamp during communication failure;
- exposes queue depth, scheduler lag, missed/skipped deadlines, overruns, deferrals, cooldown, fairness and rolling bus-load evidence;
- exposes read-only local latest values without initiating physical acquisition;
- preserves MQTT event identity, SQLite outbox ordering, offline operation and the no-Modbus-write invariant.

Default software policy does not accelerate high-priority targets below the existing `SAMPLE_INTERVAL_SECONDS` baseline. Current defaults are high `max(5 s, baseline)`, medium `max(10 s, high)` and low `max(30 s, medium)`. Final physical intervals remain unverified pending real Raspberry Pi/RS-485 measurements.

Final exact-head verification:

- CI `30996678326` GREEN;
- Edge image `30996678375` GREEN;
- Container Supply Chain `30996678388` GREEN;
- Telemetry service `30996678331` GREEN;
- Device Agent Fleet Acceptance `30996678275` GREEN;
- MQTT TLS Fleet Acceptance `30996678364` GREEN;
- Disaster Recovery TLS Fleet `30996678450` GREEN;
- Authenticated Dashboard Acceptance `30996678338` GREEN;
- Offline Bundle `30996678393` GREEN;
- focused diff: 10 device-agent/test/docs files;
- inline review threads: zero;
- submitted reviews: zero.

Authenticated browser evidence remained UI-independent across no browser, Overview, refresh, Live Data, three browser contexts and WebSocket reconnect: 19.58–20.52 fixture requests/second, zero discovery delta, zero mutation delta and GET-only Device Agent control requests.

## Previous acquisition foundations

- Issue #283 / PR #294 provides objective physical FC03 request, retry, latency, outcome and utilization instrumentation.
- Issue #284 / PR #299 provides the canonical versioned active acquisition registry and atomic local eligibility/audit persistence.
- Issue #295 / PR #296 upgraded `cryptography` to the fixed 50.x line. One exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security` and expires on 2026-08-15.

## Active architecture sequence

Epic #282 continues in dependency order:

1. #286 — isolate REST/WebSocket subscriptions from physical acquisition;
2. #287 — persisted Live Dashboard domain and local API;
3. #288 — Live Dashboard editor and channel-scoped operator workspace;
4. #289 — scale, stability and truthful live-state acceptance.

Issue #286 is Ready because the edge now has a canonical registry, a deterministic physical scheduler and a durable latest-value read model. Subscription and API consumers can therefore be isolated from bus work without changing acquisition cadence.

## Runtime and hardware evidence

```text
software verified; deterministic scheduler/registry tests verified; authenticated browser invariant verified; secure fleet verified; disconnected update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Approved blockers

- `/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract and a defined operator workflow.
- Physical RS-485 topology, final scheduler intervals, bus utilization, high-priority deadline acceptance, LE-01MP cumulative energy and extended XJP60D semantics remain hardware-dependent.
- Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Next action

Start Issue #286 on a dedicated feature branch. REST reads and WebSocket subscriptions must consume persisted/latest telemetry state and must never enqueue, accelerate or reprioritize physical Modbus acquisition.
