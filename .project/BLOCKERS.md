# NEXOLAB Blockers

Updated: 2026-08-05

## Completed telemetry delivery isolation

Issue #286 / PR #308 was squash-merged as `894884fb9a0fc6ad807206ed2fc087d68226346f` from verified head `8f8842bfac37e696989ad00a3074844b41de2736`.

Final exact-head verification was GREEN across CI, telemetry service, Device Agent fleet, authenticated dashboard/acquisition invariant, offline authentication, MQTT TLS fleet, broker control, security browser, capacity release, edge image, container supply chain, disaster recovery TLS/browser and offline bundle workflows.

The merged boundary guarantees:

- REST latest/history read committed telemetry state;
- WebSocket replay reads committed telemetry state;
- live fan-out is downstream of successful persistence and exposed as `publish_committed`;
- client count, filters, refresh and reconnect do not enqueue or persist telemetry;
- delivery code has no scheduler, registry, Modbus or driver dependencies;
- scheduler and registry code has no client-subscription inputs;
- Device Agent remains the only owner of physical cadence;
- no Modbus or hardware writes were added.

## Acquisition optimization sequencing

Epic #282 remains active. Issue #287 is the single Ready product Work Package after the state-only control reconciliation.

```text
#287 persisted Live Dashboard domain and local API
→ #288 Live Dashboard editor and channel-scoped workspace
→ #289 scale, stability and truthful live-state acceptance
```

Issue #287 must preserve these completed boundaries:

- dashboard definitions are configuration/read models, not acquisition targets;
- selected channels must reference canonical registry/inventory identities;
- dashboard CRUD cannot mutate registry eligibility, priority or cadence;
- latest telemetry remains sourced from persisted delivery state;
- local/offline operation remains complete;
- no required cloud, CDN, remote fonts, telemetry or paid runtime service;
- no Modbus or hardware writes.

## Physical scheduler acceptance remains blocked

Software verification proves deterministic priority ordering, monotonic deadlines, fairness, cooldown, restart staggering, latest-value persistence, delivery isolation and offline operation. It does not prove final physical intervals.

Real Raspberry Pi/RS-485 evidence is still required for:

- request latency and retries on the installed adapter and wiring;
- bus utilization under the actual active registry;
- high-priority deadline performance with slow or absent endpoints;
- final high/medium/low interval selection;
- confirmation that no other Modbus master is active;
- request-counter comparison under real operator UI load.

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
- Issue #286 software isolation is verified; physical request-counter comparison under actual client churn remains part of #289 hardware acceptance.

## Residual risks, not blockers for Issue #287

- Dashboard ownership, organization scoping, ordering and optimistic concurrency need explicit contracts.
- Canonical channel selection must reject unknown or ineligible identities without mutating acquisition.
- Dashboard limits must prevent unbounded definitions and channel lists.
- Deleting a dashboard must not delete telemetry or channel inventory.
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

Finish Issue #309 as a focused four-file state reconciliation. Then start Issue #287 on a dedicated feature branch from current `main`.
