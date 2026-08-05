# NEXOLAB Blockers

Updated: 2026-08-05

## Completed software scope

Issue #280 / PR #290 was squash-merged as `4af4c04167d82bdbf2d0cec71b1d10e843c30fb2`.

Final exact-head verification on `66e6133ab1129c5397f32d3e3e62946cff4a92f7`:

- CI `30980784355` GREEN;
- Authenticated Dashboard Acceptance `30980784398` GREEN;
- Offline Bundle `30980784393` GREEN;
- focused diff: three dashboard files;
- inline review threads: zero;
- submitted reviews: zero.

The live Overview no longer presents a fabricated laboratory layout or camera demo label as production evidence. Repository-backed sessions, equipment layouts and camera states remain read-only.

## Acquisition optimization sequencing

Epic #282 is active. Issue #283 is Ready and must precede scheduler or polling-policy changes.

Issues #284–#289 are dependency-blocked in this order:

```text
#283 instrumentation
→ #284 active acquisition registry
→ #285 priority-aware scheduler
→ #286 subscription isolation
→ #287 Live Dashboard API
→ #288 Live Dashboard UI
→ #289 scale and hardware acceptance
```

This dependency ordering is intentional, not a hard blocker. The project must measure physical request rates, latency, retries, cycle duration and estimated bus utilization before changing acquisition cadence.

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
- Final #283 and #289 hardware classifications require real Raspberry Pi/RS-485 request-rate evidence; deterministic fake/recorded serial evidence can verify software only.

## Residual risks, not blockers for Issue #283

- Existing Device Agent metrics are insufficient to prove whether UI activity affects physical request counts.
- The current base loop uses one global sample interval and sequentially reads configured targets; Issue #283 measures this behavior but does not redesign it.
- High-cardinality metric labels, raw payloads, credentials and production telemetry must not enter observability evidence.
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

Validate and squash-merge control Issue #292 after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #283 on a focused feature branch. Do not change polling policy in #283.
