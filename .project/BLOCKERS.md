# NEXOLAB Blockers

Updated: 2026-08-05

## Completed route-persistent telemetry delivery

Issue #314 / PR #315 and corrective Issue #316 / PR #317 are merged. Current product baseline is `b4660b15b49ff6e2776ea6adb4f0cea1e3f9ece0`.

The completed delivery layer guarantees:

- application-shell-scoped canonical latest snapshots across route transitions;
- one organization-scoped physical WebSocket shared by logical route consumers;
- simultaneous identical `latest` and `history` requests share one physical REST request;
- independent consumer abort semantics;
- 5-second zero-consumer route-transition grace before transport close;
- 15-minute bounded idle scope TTL;
- limits of 20,000 canonical samples and 128 exact latest-query snapshots;
- narrower latest views are derived only from complete broad snapshots;
- retained data keeps truthful quality, age, stale, reconnecting and offline states;
- UI navigation, display preferences and subscriptions do not mutate acquisition registry eligibility, scheduler priority or physical polling cadence;
- no Device Agent discovery/configuration mutations, Modbus writes or hardware actions were added.

Authenticated route-cycle evidence recorded one `latest` request, three `history` requests and one active WebSocket across Overview → Refrigeration → Energy → Overview, with Overview usable again in 226 ms. Offline Bundle update/rollback and volume-preservation acceptance remained GREEN.

## Acquisition optimization sequencing

Epic #282 remains active. After state-only Issue #318, Issue #288 is the single Ready product Work Package.

```text
#318 state-only reconciliation
→ #288 Live Dashboard editor and channel-scoped operator workspace
→ #289 scale, stability and truthful live-state acceptance
```

Issue #288 must preserve these completed boundaries:

- use the persisted `/api/v1/live-dashboards` API rather than browser-only storage;
- use the #314/#316 shared telemetry runtime rather than introducing page-local cache or a second WebSocket lifecycle;
- bootstrap and subscribe only to selected canonical channel/metric pairs;
- preserve ETag stale-writer conflicts and unsaved operator changes truthfully;
- display refresh, time window, filters and reconnect behavior cannot mutate acquisition;
- normal UI actions cannot call Device Agent discovery/configuration endpoints;
- local/offline operation remains complete;
- no required cloud, CDN, remote fonts, telemetry or paid runtime service;
- no Modbus or hardware writes.

## Physical scheduler acceptance remains blocked

Software verification proves deterministic priority ordering, monotonic deadlines, fairness, cooldown, delivery isolation, persisted dashboard configuration, route-persistent telemetry and offline operation. It does not prove final physical intervals or real-bus request counts.

Real Raspberry Pi/RS-485 evidence remains required for Issue #289:

- request latency and retries on the installed adapter and wiring;
- bus utilization under the actual active registry;
- high-priority deadline performance with slow or absent endpoints;
- final high/medium/low interval selection;
- confirmation that no other Modbus master is active;
- physical request-counter comparison under real operator UI load and multiple saved-dashboard subscriptions.

Until measured, report physical scheduler intervals, physical request-rate acceptance and hardware latency as unverified.

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
- Issue #286/#314/#316 software isolation and continuity are verified; final physical comparison remains part of #289.

## Residual risks, not blockers for Issue #288

- The editor must preserve unsaved local changes when the API returns a stale-writer conflict.
- Channel search/filter UX must use canonical identities and reject unavailable selections clearly.
- Dashboard live views must bound selected series, history windows and render cost.
- Loading, empty, stale, reconnecting, offline, forbidden and configuration-error states must remain distinct.
- Archived dashboards must not silently reopen as active or fall back to demo data.
- Color choices and charts must remain keyboard accessible and cannot communicate state by color alone.
- The UI must not use broad inventory bootstrap after a dashboard definition is already known.
- Deferred toolchain Issues #252–#257 remain outside active product scope unless they become a concrete security or delivery blocker.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- materially different product or architecture choices;
- any operation that cannot preserve local laboratory data.

## Next Ready action

Complete Issue #318 as a four-file state-only PR, then start Issue #288 on a dedicated feature branch from current `main`.
