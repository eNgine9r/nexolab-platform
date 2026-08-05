# NEXOLAB Blockers

Updated: 2026-08-05

## Completed persisted Live Dashboard domain

Issue #287 / PR #311 was squash-merged as `e92c36fe1b863f25132ecb39fe7f46928742c470` from verified head `58f03b107cb900c7436b6784d27a305a1bccc4a4`.

Final exact-head verification was GREEN across CI, telemetry service, authenticated acquisition invariant, offline authentication, Offline Bundle, Device Agent fleet, MQTT TLS fleet, broker control, capacity release, container supply chain, security, nodes, alerts, refrigeration, test sessions, reports, rendered reports and disaster-recovery browser/TLS workflows.

The merged domain guarantees:

- Live Dashboard definitions and ordered items are persisted locally in PostgreSQL;
- every selected channel is validated against the active organization-scoped measurement catalog;
- maximum item count, page size, offset, names and display preferences are bounded deterministically;
- update/archive use ETag/version optimistic concurrency;
- mutation permissions are explicit and viewer/auditor remain read-only;
- create/update/archive audit events are atomic with the domain mutation;
- archive preserves telemetry, histories, channel inventory and equipment configuration;
- refresh/time-window preferences do not influence acquisition registry eligibility, scheduler priority or physical cadence;
- no Modbus or hardware writes were added.

## Acquisition optimization sequencing

Epic #282 remains active. Issue #288 is the single Ready product Work Package.

```text
#288 Live Dashboard editor and channel-scoped operator workspace
→ #289 scale, stability and truthful live-state acceptance
```

Issue #288 must preserve these completed boundaries:

- use the persisted `/api/v1/live-dashboards` API rather than browser-only storage;
- bootstrap latest values and subscribe only to selected canonical channels/metrics;
- keep WebSocket delivery downstream of persisted telemetry;
- preserve ETag stale-writer conflicts and unsaved operator changes truthfully;
- display refresh, time window, filters and reconnect behavior cannot mutate acquisition;
- normal UI actions cannot call Device Agent discovery/configuration endpoints;
- local/offline operation remains complete;
- no required cloud, CDN, remote fonts, telemetry or paid runtime service;
- no Modbus or hardware writes.

## Physical scheduler acceptance remains blocked

Software verification proves deterministic priority ordering, monotonic deadlines, fairness, cooldown, restart staggering, latest-value persistence, delivery isolation, persisted dashboard configuration and offline operation. It does not prove final physical intervals or real-bus request counts.

Real Raspberry Pi/RS-485 evidence is still required for:

- request latency and retries on the installed adapter and wiring;
- bus utilization under the actual active registry;
- high-priority deadline performance with slow or absent endpoints;
- final high/medium/low interval selection;
- confirmation that no other Modbus master is active;
- request-counter comparison under real operator UI load and multiple dashboard subscriptions.

Until measured, report physical scheduler intervals and physical request-rate acceptance as unverified.

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
- Issue #286 software isolation is verified; physical request-counter comparison remains part of #289.
- Issue #287 software persistence/API is verified; no physical hardware behavior was changed or accepted.

## Residual risks, not blockers for Issue #288

- The editor must preserve unsaved local changes when the API returns a stale-writer conflict.
- Channel search/filter UX must use canonical identities and reject unavailable selections clearly.
- Dashboard live views must bound selected series, history windows and render cost.
- Loading, empty, stale, reconnecting, offline, forbidden and configuration-error states must remain distinct.
- Archived dashboards must not silently reopen as active or fall back to demo data.
- Color choices and charts must remain keyboard accessible and cannot communicate state by color alone.
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

Start Issue #288 on a dedicated feature branch from current `main`. Build the dashboard library, editor and selected-series live workspace while preserving complete separation from physical acquisition.
