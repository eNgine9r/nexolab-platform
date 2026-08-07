# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #378 — resolved and merged

Issue #378 / PR #380 is completed. Final exact head `5635df201a6cbd59227a8ebe181c44fa5167f67c` completed 14 checks with 0 failures and 0 in-progress, and PR #380 squash-merged into `main` as `6645af46a198ff454142df3b0a713984f4d71196`.

Controlled Raspberry Pi hotplug acceptance passed on the same running Device Agent:

```text
container: 9f03df0e798e
restart_count: 0 -> 0
device_before: /dev/ttyUSB1
stable by-id path disappeared: yes
device_after: /dev/ttyUSB0
stable by-id path reappeared: yes
PostgreSQL max(id): 2332589 -> 2332595 -> 2332624
newest_age after recovery: ~18-21 s
```

The RS-485 USB re-enumeration blocker is no longer active.

## Issue #374 — regression parent resolved

Issue #374 / PR #375 remains a valid merged partial fix. Its reopened long-duration USB re-enumeration regression is resolved by merged Issue #378 and physical same-container recovery evidence.

After this state-only reconciliation merges, close #374 as completed regression parent and remove any stale blocked/in-progress label.

## Issue #368 — active validation track

Issue #368 / PR #373 remains software-GREEN on the previously reconciled head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed checks
0 failures
0 in-progress
0 queued
```

It is no longer blocked by acquisition recovery. Before Raspberry Pi migration-v2, PR #373 must be reconciled with current `main` so it inherits merged #378 and canonical project state, then must receive fresh exact-head GREEN CI.

The Raspberry Pi database remains safe:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

## Sequencing blockers

- #381: state-only post-#378 reconciliation; merge on proportional GREEN CI.
- #368: active immediately after #381; reconcile branch and rerun exact-head CI before physical migration-v2.
- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence.
- #289 remains downstream after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, privileged hardware containers, or unsupported physical acceptance claims.
