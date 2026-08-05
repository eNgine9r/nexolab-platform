# NEXOLAB Blockers

Updated: 2026-08-05

## Completed software scope

Issue #277 / PR #278 was squash-merged as `1f4c2999a7bf1f1b14fe32f4995313c884be81b3`. Final exact-head verification was GREEN across CI, authenticated dashboard, Nodes, Alerts, Reports, Refrigeration and Offline Bundle. Parent Issue #260 is closed as completed.

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

## Residual risks, not blockers for Issue #280

- Overview currently contains demo sessions/layout/camera summaries; Issue #280 can replace these with existing read-only contracts or explicit unavailable states without hardware access.
- Deferred toolchain Issues #252–#257 remain outside active product scope unless they become a concrete security or delivery blocker.
- Real camera `online` state requires a concrete read-only observation source and must not be inferred from configuration.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- materially different product or architecture choices;
- any operation that cannot preserve local laboratory data.

## Next Ready action

Merge the control-only Issue #279 PR after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #280 on a focused branch and draft PR. Keep `/lockers` blocked.
