# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `b207a15fe88621f0ad43fe6555af2b29ad1796e7`
Active control Work Package: Issue #297 — post-acquisition project-state reconciliation
Branch: `chore/297-post-acquisition-state`
Next Ready Work Package: Issue #284 — universal active acquisition registry
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, deterministic serial tests, authenticated browser invariants and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Acquisition instrumentation completed

Issue #283 / PR #294 was squash-merged as `b207a15fe88621f0ad43fe6555af2b29ad1796e7` from verified head `ad5705282ef38528f1ae645458231bcef471273a`.

The merged Device Agent now:

- records each physical read-only FC03 attempt exactly once by bounded outcome;
- exposes retry attempts, latency, last-success, cycle duration, overrun, busy-time and utilization evidence;
- separates normal acquisition from explicit discovery and configuration service operations;
- exposes sanitized acquisition evidence through `/metrics`, `/health` and `/ready`;
- preserves the existing polling interval, configured targets and retry policy;
- performs no Modbus write and introduces no cloud runtime dependency.

Authenticated browser evidence proved that physical request rates remained inside the same scheduler envelope for no browser, Overview open/refresh, Live Data, three concurrent authenticated browser contexts and WebSocket reconnect. Observed rates were 19.57–20.32 requests/second, `discoveryDelta=0`, `mutationDelta=0`, and every observed Device Agent control request was `GET`.

Final exact-head verification:

- CI `30985996238` GREEN;
- Authenticated Dashboard Acceptance `30985996315` GREEN;
- Device Agent Fleet Acceptance `30985996219` GREEN;
- Offline Bundle `30985996222` GREEN;
- Container Supply Chain `30985996275` GREEN;
- Edge image `30985996225` GREEN;
- Telemetry service `30985996265` GREEN;
- Refrigeration Browser Acceptance `30985996253` GREEN;
- MQTT TLS Fleet Acceptance `30985996287` GREEN;
- Disaster Recovery TLS Fleet `30985996234` GREEN;
- focused diff: 11 acquisition files;
- inline review threads: zero;
- submitted reviews: zero.

## Supply-chain security state

Issue #295 / PR #296 was squash-merged as `3b26fb444cdfc3f11659bce149037a87c6e3fc36`.

- `cryptography` uses the fixed 50.x line;
- one exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains because Debian Trixie currently provides no fixed package;
- the exception is owned by `platform-security`, expires on 2026-08-15 and does not weaken global HIGH/CRITICAL enforcement.

## Active architecture sequence

Epic #282 continues in dependency order:

1. #284 — universal active acquisition registry;
2. #285 — priority-aware adaptive scheduler and edge latest-value cache;
3. #286 — isolate REST/WebSocket subscriptions from physical acquisition;
4. #287 — persisted Live Dashboard domain and local API;
5. #288 — Live Dashboard editor and channel-scoped operator workspace;
6. #289 — scale, stability and truthful live-state acceptance.

Issue #284 is Ready because #283 established the objective request counters needed to prove that disabled, reserve, retired, uninstalled and discovery-only targets generate zero normal-cycle Modbus requests.

## Approved blocked route

`/lockers` remains blocked pending concrete locker inventory, a read-only protocol/API contract and a defined operator workflow. No demo controls, guessed device states or door/lock writes may be introduced.

## Runtime and hardware evidence

```text
software verified; deterministic serial verified; authenticated browser invariant verified; disconnected update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Next action

Validate and squash-merge the control-only Issue #297 PR after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #284 on a dedicated feature branch. Preserve read-only Modbus behavior and do not change scheduler priority or cadence in #284.
