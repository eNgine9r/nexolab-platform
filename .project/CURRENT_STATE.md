# NEXOLAB Current State

Updated: 2026-08-06
Verified software baseline: `959bd8f54cf044280d385917578f836a5c8ec7c8`
Control checkpoint: Issue #324 — completed in the state-only branch
Branch: `docs/324-acquisition-software-checkpoint`
Next independent Ready Work Package: none
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software and disconnected runtime; physical Raspberry Pi/RS-485 performance acceptance remains explicitly pending.

## Acquisition software acceptance merged

Issue #289 software validation was implemented in PR #323 and squash-merged as `959bd8f54cf044280d385917578f836a5c8ec7c8` from exact verified head `a15f4b084137bb53a11eff7c7ba5f2f3d78436f5`.

Issue #289 remains open. Its completion classification is:

```text
software verified; hardware performance acceptance pending
```

The merged acceptance layer adds no product or acquisition runtime behavior. It provides:

- predeclared scale, latency, truthful-state and safety thresholds;
- deterministic pilot, expanded and stress acquisition profiles;
- read-only scheduler scale, fairness, cooldown and overrun evidence;
- zero-execution proof for disabled and other ineligible targets;
- MQTT outbox replay-order verification;
- truthful connecting, live, reconnecting, stale, offline, authorization and configuration state verification;
- an authenticated multi-browser acquisition-invariant matrix;
- a sanitized read-only Raspberry Pi evidence collector for aggregate local metrics;
- a documented controlled hardware procedure.

## Exact software evidence

Deterministic scheduler profiles:

| Profile | Active targets | Executions | Maximum concurrent reads | Planning load | Maximum scheduler lag |
| --- | ---: | ---: | ---: | ---: | ---: |
| pilot | 34 | 336 | 1 | 0.56% | 0.002 s |
| expanded | 136 | 2,304 | 1 | 3.84% | 0.000329 s |
| stress | 240 | 4,320 | 1 | 7.20% | 0.001435 s |

Additional deterministic evidence:

- healthy-profile communication failures: 0;
- callback errors: 0;
- healthy-profile overruns: 0;
- disabled/ineligible executions: 0;
- one unavailable Unit ID entered cooldown after the configured threshold;
- unrelated `xjp60d:106-03` continued to execute;
- retained value and original capture timestamp survived the communication failure;
- quality changed truthfully to `communication_error`;
- maximum concurrent fake serial reads remained one;
- serial port opened by the deterministic runner: false;
- Modbus write attempts: 0.

Authenticated acquisition-invariant evidence:

- authenticated contexts: 7;
- open pages: 8;
- request-rate range across all phases: 19.7697–20.1266 requests/second;
- no-browser rate: 19.9594 requests/second;
- persisted Live Dashboard rate: 19.8890 requests/second;
- concurrent operator surfaces rate: 20.0860 requests/second;
- WebSocket reconnect rate: 20.1180 requests/second;
- Telemetry Service restart rate: 19.9899 requests/second;
- Device Agent control requests were GET-only;
- discovery delta: 0;
- configuration mutation delta: 0;
- maximum physical WebSocket count per page: 1.

Selected-series and route-return evidence:

- saved series: `106-03 + temperature.probe`;
- selected latest requests: 1;
- selected history requests: 1;
- selected-series maximum concurrent WebSockets: 1;
- persisted definition remained available after Telemetry Service restart;
- Refrigeration usable: 175 ms;
- Energy usable: 210 ms;
- Overview usable after return: 170 ms;
- route-persistent active/max concurrent WebSockets: 1/1;
- acquisition mutations: 0.

## Exact-head gates

All checks on `a15f4b084137bb53a11eff7c7ba5f2f3d78436f5` were GREEN:

- formatting, lint, typecheck, full tests and production build;
- Acquisition Scale Acceptance;
- Authenticated Dashboard Acceptance;
- Refrigeration Browser Acceptance;
- Telemetry Service;
- Device Agent Fleet Acceptance;
- MQTT TLS Fleet Acceptance;
- Edge image;
- Container Supply Chain;
- Disaster Recovery TLS Fleet;
- Offline Bundle.

Offline Bundle proved clean-host transfer, runtime-image removal, blocked egress, archive loading, disconnected startup with pulls disabled, update/rollback and persistent-volume preservation.

## Completed acquisition optimization software sequence

- Issue #283 / PR #294 — acquisition request instrumentation and UI-independent request-rate evidence.
- Issue #284 / PR #299 — canonical active acquisition registry.
- Issue #285 / PR #305 — priority-aware adaptive scheduler and durable latest-value cache.
- Issue #286 / PR #308 — REST/WebSocket delivery isolated from physical acquisition.
- Issue #287 / PR #311 — persisted Live Dashboard domain and API.
- Issue #314 / PR #315 — route-persistent application-shell telemetry runtime.
- Issue #316 / PR #317 — request ownership, bounded lifecycle and route-cycle evidence.
- Issue #288 / PR #320 — persisted Live Dashboard library/editor/workspace.
- Issue #289 / PR #323 — software scale, stability and truthful-state acceptance.

Issue #321 / PR #322 state reconciliation is completed and merged as `261beced14a2e4604fc1ae2d2bb56c054acf0d78`.

## Physical acceptance boundary

Controlled Raspberry Pi/RS-485 evidence is still required for:

1. no browser;
2. Overview;
3. one persisted Live Dashboard;
4. repeated route transitions;
5. multiple browser workstations;
6. WebSocket reconnect;
7. one known unavailable endpoint;
8. MQTT interruption and outbox drain.

The physical matrix must capture real request counters, retries, serial latency, bus utilization, scheduler lag, CPU, RAM, disk, queue depth and delivery latency. It must remain read-only and must not perform controller configuration, Modbus writes, persistent-data deletion or production cutover.

## Open blockers

- No controlled SSH/RS-485 access is available from the current execution environment.
- Issue #289 cannot be closed without physical Raspberry Pi/RS-485 evidence.
- Issue #245 software is merged, but actual loopback-only Raspberry Pi acceptance is pending.
- Issues #189, #200, #201 and #202 remain hardware-dependent.
- `/lockers` remains blocked by missing concrete inventory, read-only protocol scope and operator workflow.
- Cameras, ONVIF/RTSP media and NVR remain physically unverified.
- The `telemetry-service/libcjson1/CVE-2026-67216` exception remains owned by `platform-security` and must be reviewed by 2026-08-15.

## Next action

No independent Ready software Work Package remains. Resume Issue #289 hardware acceptance only when controlled Raspberry Pi/RS-485 access is available, or create a new independent Ready Work Package through the normal product process. Do not fabricate physical evidence or perform Modbus/hardware writes.
