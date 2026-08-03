# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #261 — Energy Monitoring

No product, software, runtime, offline or hardware blocker prevents protected merge of PR #262.

Exact implementation head `c8dc696f2b344a6c412e4cbc2a4fddd24a6fccd7` is GREEN across CI, Telemetry Service, authenticated/security/refrigeration/test-session/report browser gates, Offline Auth, disconnected Offline Bundle, capacity, fleet, MQTT TLS, broker control, supply-chain and disaster-recovery workflows.

The production fixes include:

- authenticated WebSocket coverage before latest and history snapshots;
- bounded startup event reconciliation;
- commit-stable history watermark with the barrier applied to `SessionAwareDatabase`;
- complete pagination and bounded renderable-only downsampling;
- source-derived outage segmentation and cross-callback ordering protection;
- ordering cursor seeded when changing metrics;
- explicit history error for terminal WebSocket startup states;
- permission gating, stale-value retention, metric/unit validation and production node scope;
- restoration of the stage telemetry filter in session attribution.

Remaining administrative actions are limited to the exact-head state-only gate, review hygiene and expected-head merge.

Cumulative active energy remains blocked under Issue #201 until the physical register, scale, unit, word order and rollover behavior are confirmed. Do not display guessed `kWh`.

## Product-page priority

After PR #262, Issue #263 is Ready and replaces `/live` with the universal authenticated telemetry explorer.

Deferred toolchain Issues #252–#257 may resume only for a relevant security fix, end-of-support condition or concrete blocker for an active product Work Package.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production device behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Hardware and operational risks

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending controlled access.
- **N-037:** Sharp compatibility override remains monitored.
- **N-023:** node health durability is not claimed equal to telemetry process-restart durability.
- **N-024:** rollback must preserve named volumes and spool compatibility.
- **N-025:** actual-host spool capacity evidence remains required.
- **N-032:** actual Raspberry Pi ARM64 archive/load/start/update/rollback remains unverified.
- **#200:** physical RS-485 topology hardware-blocked.
- **#201:** cumulative LE-01MP energy hardware-blocked.
- **#202:** extended XJP60D semantics hardware-blocked.

## Next Ready action

Complete the state-only gate and merge PR #262. Then create `feat/263-live-telemetry-explorer` from updated `main` and implement Issue #263 without dependency migrations.
