# NEXOLAB Blockers

Updated: 2026-08-05

## Completed active acquisition registry

Issue #284 / PR #299 was squash-merged as `6aaa3e700365aa7edcf8ce7de1818e5e2d1b67c8` from verified head `c83f42aee7fc1251a683fb5c55cbe2779217673f`.

Final exact-head verification:

- CI `30990278424` GREEN;
- Edge image `30990278312` GREEN;
- Container Supply Chain `30990278313` GREEN;
- Telemetry service `30990278544` GREEN;
- Device Agent Fleet Acceptance `30990278529` GREEN;
- MQTT TLS Fleet Acceptance `30990278311` GREEN;
- Disaster Recovery TLS Fleet `30990278521` GREEN;
- Authenticated Dashboard Acceptance `30990278466` GREEN on attempt 2;
- Offline Bundle `30990278317` GREEN;
- focused diff: 8 files;
- inline review threads: zero;
- submitted reviews: zero.

The registry now preserves inventory while allowing only targets with active device and target lifecycle to enter normal FC03 polling. Disabled, reserve, retired, uninstalled, discovery-only and invalid targets remain visible but are excluded by deterministic eligibility tests. Registry state and audit are persisted atomically with optimistic revision control.

Physical Raspberry Pi/RS-485 proof is still required before claiming that a real disabled target emits zero bus requests.

## Acquisition optimization sequencing

Epic #282 remains active. Issue #285 is the single Ready Work Package.

```text
#285 priority-aware adaptive scheduler and edge latest cache
→ #286 REST/WebSocket subscription isolation
→ #287 Live Dashboard persistence and API
→ #288 Live Dashboard operator workspace
→ #289 scale, stability and hardware acceptance
```

Issue #285 may change scheduling of registry-eligible read-only targets only. It must preserve:

- FC03-only behavior;
- one serialized worker per physical bus;
- inventory/eligibility separation;
- explicit discovery as a separate service operation;
- the rule that UI routes and display refresh cannot add physical work.

## Supply-chain security risk

Issue #295 / PR #296 upgraded `cryptography` to the fixed 50.x line and restored the GREEN container gate.

One exact exception remains for `telemetry-service/libcjson1/CVE-2026-67216` because Debian Trixie currently reports no fixed package. It:

- is owned by `platform-security`;
- expires on 2026-08-15;
- is limited to the authenticated local `mosquitto_ctrl` dynamic-security adapter path;
- does not weaken global HIGH/CRITICAL enforcement.

This is a tracked security risk and review obligation, not a blocker for Issue #285. Remove the exception immediately when a fixed Debian package becomes available.

## Smart Lockers blocker

`/lockers` remains blocked. Repository and GitHub evidence do not provide:

- a concrete locker inventory;
- a read-only protocol or API contract;
- a defined operator workflow;
- verified physical locker evidence.

Do not create demo locker controls, guessed states, door/lock writes or fabricated production behavior. Resume only after the Product Owner supplies the missing inventory and protocol scope.

## Hardware-dependent blockers

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending.
- **#200:** physical RS-485 topology and polling envelope require hardware evidence.
- **#201:** LE-01MP cumulative energy remains excluded pending read-only hardware validation.
- **#202:** extended XJP60D semantics and portability require read-only hardware evidence.
- Physical cameras, ONVIF, RTSP media and NVR remain unverified.
- Issue #283 is software/browser/offline verified only; real Raspberry Pi/RS-485 request-rate evidence remains required before hardware verification.
- Issue #284 is software/browser/offline verified only; hardware acceptance must compare request counters before and after disabling an approved real target without any physical write.

## Residual risks, not blockers for Issue #285

- Priority intervals must be bounded and validated against actual bus capacity rather than assuming one-second polling is safe.
- One slow or absent endpoint must not starve other eligible targets.
- Cooldown/circuit-breaker behavior must not silently convert stale values into live values.
- Latest-value caching must remain local and durable enough for normal UI reads without becoming a second uncontrolled acquisition path.
- Scheduler metrics must expose missed deadlines, overruns, cooldown and fairness without secret or high-cardinality labels.
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

Validate and squash-merge control Issue #301 after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #285 on a focused feature branch from updated `main`.
