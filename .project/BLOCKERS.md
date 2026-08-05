# NEXOLAB Blockers

Updated: 2026-08-05

## Completed Live Dashboard product boundary

Issue #288 / PR #320 is merged. Current product baseline is `d7affee11a39d5a007c461b9a4dea17f14b5bfb3`.

The completed `/live` product surface guarantees:

- persisted organization-scoped dashboard definitions through `/api/v1/live-dashboards`;
- library, create, edit, duplicate, archive and open flows;
- ETag/If-Match optimistic concurrency and preservation of unsaved local changes on stale-writer conflict;
- editor-only canonical inventory with bounded search/filter selection;
- duplicate prevention, deterministic ordering and a 64-item maximum;
- selected-only `latest`, `history` and logical WebSocket subscriptions after a saved dashboard is opened;
- one physical WebSocket maximum through the shared application-shell runtime;
- bounded history of 8,000 total samples and 500 per series;
- truthful loading, empty, reconnecting, stale, offline, forbidden, configuration and error states;
- viewer read-only behavior and `live_dashboards.manage` mutation gating;
- refresh, time window, colors and visualizations remain display/query preferences only;
- no Device Agent discovery/configuration mutation, registry mutation, scheduler mutation, Modbus write or hardware action.

Authenticated evidence recorded exactly one selected `latest` and one selected `history` request for `106-03 + temperature.probe`, maximum concurrent WebSockets of one, persistence after Telemetry Service restart and zero acquisition mutations. Offline Bundle update/rollback and volume preservation remained GREEN.

## Acquisition optimization sequencing

Epic #282 remains active.

```text
#321 state-only reconciliation
→ #289 acquisition scale, stability and truthful live-state acceptance
```

All software dependencies for Issue #289 are merged. The deterministic software matrix is Ready; the real Raspberry Pi/RS-485 gate is hardware-dependent.

## Issue #289 hardware boundary

Software verification must document targets and prove the reproducible matrix for:

- baseline and increased deterministic inventories;
- unavailable and timeout-heavy endpoints;
- one and multiple authenticated browser contexts;
- Overview, Live Dashboard, Refrigeration, Energy and session-scoped telemetry concurrently;
- route transitions, WebSocket interruption/reconnect and Telemetry Service restart;
- MQTT interruption and outbox drain;
- disconnected LOCAL_LAN runtime;
- deterministic reconnecting, stale, offline, auth, permission and configuration states.

Real Raspberry Pi/RS-485 evidence remains required for:

- physical requests per bus and time window;
- installed-adapter response latency and retry rate;
- actual bus utilization;
- high-priority deadline and fairness performance with slow or absent endpoints;
- final high/medium/low interval acceptance;
- confirmation that no other Modbus master is active;
- physical request-counter comparison with no browser, Overview, one Live Dashboard, route transitions and multiple browsers;
- physical CPU, memory, disk, queue depth and ingestion-to-WebSocket latency.

Until measured, use this classification:

```text
software verified; hardware performance acceptance pending
```

## Supply-chain security risk

One exact exception remains for `telemetry-service/libcjson1/CVE-2026-67216` because Debian Trixie currently reports no fixed package. It:

- is owned by `platform-security`;
- expires on 2026-08-15;
- is limited to the authenticated local `mosquitto_ctrl` dynamic-security adapter path;
- does not weaken global HIGH/CRITICAL enforcement.

Remove the exception immediately when a fixed Debian package becomes available.

## Smart Lockers blocker

`/lockers` remains blocked pending:

- concrete locker inventory;
- a read-only protocol or API contract;
- a defined operator workflow;
- verified physical locker evidence.

Do not create demo controls, guessed states, door/lock writes or fabricated production behavior.

## Hardware-dependent blockers

- **#245:** actual standalone Raspberry Pi acceptance pending.
- **#189:** physical reboot, power-loss and media restore pending.
- **#200:** physical RS-485 topology and polling envelope pending.
- **#201:** LE-01MP cumulative energy remains excluded pending read-only hardware validation.
- **#202:** extended XJP60D semantics and portability require read-only hardware evidence.
- Physical cameras, ONVIF, RTSP media and NVR remain unverified.
- Issue #284 still requires physical request-counter proof for disabled real targets.
- Issue #285 still requires physical interval, utilization and deadline proof.
- Issue #289 owns final physical comparison for the merged acquisition, delivery and Live Dashboard stack.

## Residual risks, not blockers for deterministic Issue #289 work

- Performance targets must be documented before execution rather than inferred after results.
- Fake/recorded serial inventories must remain deterministic and must not be reported as hardware evidence.
- A slow or missing endpoint must degrade only its own quality and must not make unrelated channels appear offline.
- Latest REST and selected WebSocket values must remain consistent by event identity and freshness.
- Backend restart and MQTT backlog recovery must not create duplicate committed telemetry or false freshness.
- Browser counts and route transitions must not recreate broad inventory bootstrap or duplicate active subscriptions.
- Deferred toolchain Issues #252–#257 remain outside active validation scope unless they become a concrete security or delivery blocker.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- materially different product or architecture choices;
- any operation that cannot preserve local laboratory data;
- claiming physical performance acceptance without controlled Raspberry Pi/RS-485 evidence.

## Next Ready action

Complete Issue #321 as a four-file state-only PR, then start Issue #289 by documenting the performance targets and deterministic software matrix. Treat unavailable controlled Raspberry Pi/RS-485 access as a hardware acceptance blocker, not as a reason to fabricate completion.
