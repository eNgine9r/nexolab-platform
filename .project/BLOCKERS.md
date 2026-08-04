# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #263 — Live Data telemetry explorer

No product, software, browser-runtime or offline blocker prevents PR #264 from leaving draft after the state-only exact-head gate.

Verified executable head `de80cf689fc8829fdf325f8991de9e7d3533ee3e` is GREEN across:

- CI `30880961470`;
- Authenticated Dashboard Acceptance `30880961490`;
- Refrigeration Browser Acceptance `30880961482`;
- Offline Bundle `30880961442`.

The final browser acceptance proves:

- deterministic PostgreSQL latest/history fixtures;
- stale, filter and selection behavior;
- separate charts for incompatible units;
- outage boundaries and stable watermark history;
- retry after an injected history failure;
- MQTT QoS 1 publication with a known `event_id`;
- commit of that exact event in PostgreSQL;
- authenticated WebSocket propagation into the `/live` latest table.

The MQTT acceptance payload now conforms to the canonical telemetry contract: XJP60D `raw_value` is integer evidence and `raw_status` is explicit. The persistence barrier is retained so future schema, authorization or ingestion regressions fail at their real boundary instead of timing out only at the UI.

Review audit is clean: no inline review threads and no submitted reviews.

Remaining administrative action: pass the final state-only repository gate, update the PR description and mark PR #264 ready for review.

## Product-page priority

The next queued operator page is `/equipment-layouts`. It requires a focused GitHub Issue before implementation.

Deferred toolchain Issues #252–#257 remain out of the page-completion sequence unless a security, support or concrete product blocker appears.

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

Complete the state-only exact-head gate and mark PR #264 ready. After merge, create the focused Work Package for `/equipment-layouts`.
