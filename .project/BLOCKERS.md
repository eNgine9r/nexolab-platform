# NEXOLAB Blockers

Updated: 2026-08-05

## Completed adaptive acquisition scheduler

Issue #285 / PR #305 was squash-merged as `4d9300a87e497b13d1d9fcabc479df781bcc8505` from verified head `54d49f422723b52a41feff307023a299f27e3a92`.

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
- focused diff: 10 files;
- inline review threads: zero;
- submitted reviews: zero.

The scheduler now derives normal jobs only from registry-eligible FC03 targets, uses one serialized worker per bus, applies monotonic deadlines, bounded fairness and endpoint cooldown, and stores a durable latest-value read model. UI activity remains outside physical target selection and cadence.

## Acquisition optimization sequencing

Epic #282 remains active. Issue #286 is the single Ready Work Package.

```text
#286 REST/WebSocket subscription isolation
→ #287 Live Dashboard persistence and API
→ #288 Live Dashboard operator workspace
→ #289 scale, stability and hardware acceptance
```

Issue #286 must preserve these completed boundaries:

- REST reads and WebSocket subscriptions consume persisted/latest telemetry state;
- consumer count, refresh rate and reconnect activity cannot enqueue, accelerate or reprioritize physical reads;
- the Device Agent remains the owner of physical acquisition cadence;
- registry eligibility remains the only normal target source;
- MQTT and SQLite delivery semantics remain compatible;
- no Modbus or hardware writes.

## Physical scheduler acceptance remains blocked

Software verification proves deterministic priority ordering, monotonic deadlines, fairness, cooldown, restart staggering, latest-value persistence and offline operation. It does not prove final physical intervals.

Real Raspberry Pi/RS-485 evidence is still required for:

- request latency and retries on the installed adapter and wiring;
- bus utilization under the actual active registry;
- high-priority deadline performance with slow or absent endpoints;
- final high/medium/low interval selection;
- confirmation that no other Modbus master is active;
- request-counter comparison under UI load.

Until measured, report physical scheduler intervals as unverified. Do not lower intervals or perform a site cutover based only on software tests.

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

## Residual risks, not blockers for Issue #286

- Consumers must not read directly from hardware drivers or invoke acquisition callbacks.
- Latest-value age and quality must remain explicit; retained values cannot be represented as fresh live samples.
- WebSocket reconnects must not cause replay storms or duplicate physical work.
- Subscription fan-out must be bounded and isolated from the Device Agent bus lock.
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

Start Issue #286 on a focused feature branch from current `main`. Preserve complete separation between physical acquisition and REST/WebSocket consumer activity.
