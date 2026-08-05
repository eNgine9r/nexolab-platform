# NEXOLAB Blockers

Updated: 2026-08-05

## Completed acquisition instrumentation

Issue #283 / PR #294 was squash-merged as `b207a15fe88621f0ad43fe6555af2b29ad1796e7` from verified head `ad5705282ef38528f1ae645458231bcef471273a`.

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

Deterministic browser evidence held the normal acquisition envelope at 19.57–20.32 physical requests/second across no browser, Overview open/refresh, Live Data, three concurrent authenticated browser contexts and WebSocket reconnect. Discovery and mutation deltas were zero, and observed Device Agent control requests were GET-only.

## Acquisition optimization sequencing

Epic #282 remains active. Issue #284 is the single Ready Work Package.

```text
#284 active acquisition registry
→ #285 priority-aware scheduler
→ #286 subscription isolation
→ #287 Live Dashboard API
→ #288 Live Dashboard UI
→ #289 scale and hardware acceptance
```

Issue #284 may change only local acquisition eligibility and registry persistence. It must not change Modbus function codes, scheduler priority/cadence or physical controller configuration.

## Supply-chain security risk

Issue #295 / PR #296 upgraded `cryptography` to the fixed 50.x line and restored the GREEN container gate.

One exact exception remains for `telemetry-service/libcjson1/CVE-2026-67216` because Debian Trixie currently reports no fixed package. It:

- is owned by `platform-security`;
- expires on 2026-08-15;
- is limited to the authenticated local `mosquitto_ctrl` dynamic-security adapter path;
- does not weaken global HIGH/CRITICAL enforcement.

This is a tracked security risk and review obligation, not a blocker for Issue #284. Remove the exception immediately when a fixed Debian package becomes available.

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
- Issue #284 hardware acceptance must compare request counters before and after disabling approved test targets without performing any physical write.

## Residual risks, not blockers for Issue #284

- Registry migration must preserve existing XJP60D active points and LE-01MP configuration without deleting data.
- Inventory visibility must remain independent from polling eligibility.
- Invalid, duplicate, write-capable or ambiguous bus/Unit/channel identities must be rejected.
- Disabled, reserve, retired, uninstalled and discovery-only targets must generate zero normal-cycle requests.
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

Validate and squash-merge control Issue #297 after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #284 on a focused feature branch. Preserve the read-only Modbus invariant and existing scheduler cadence.
