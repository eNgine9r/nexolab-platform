# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #378 — hardware verified; merge gate only

Issue #378 / PR #380 passed controlled Raspberry Pi hotplug acceptance on exact pre-state candidate `c2cf1ce4939c77f138daac2841f39651afd4bcba`.

Physical PASS evidence:

```text
candidate container: 9f03df0e798e
container id before/after: unchanged
restart_count: 0 -> 0
started_at: unchanged
device_before: /dev/ttyUSB1
stable by-id path disappeared: yes
device_after: /dev/ttyUSB0
stable by-id path reappeared: yes
PostgreSQL max(id) at reappearance: 2332589
first recovery max(id): 2332595
final observed max(id): 2332624
newest_age after recovery: ~18-21 s
```

Transient `termios.error` / ENOENT warnings occurred during the deliberate physical disconnect while the path was absent. The same running Device Agent recovered automatically after re-enumeration without restart/recreate.

PR #380 therefore satisfies the hardware behavior boundary. Remaining gate: commit this project-state checkpoint, rerun exact-head CI on the resulting head, complete final diff/review/base audit, then merge only if GREEN.

## Issue #374 — regression parent awaiting #378 merge

Issue #374 / PR #375 remains the merged partial serial-session invalidation fix. The previously exposed long-duration USB re-enumeration regression is now physically resolved by #378.

Keep #374 reopened only until #378 is merged and post-merge reconciliation confirms the corrected behavior in canonical `main`; then close #374 as completed regression parent. Do not create another implementation PR under #374.

## Issue #368 — blocked only by #378 merge/reconciliation

Issue #368 / PR #373 remains software-GREEN on reconciled head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed checks
0 failures
0 in-progress
0 queued
```

Its Raspberry Pi database remains safe:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

Do not run #368 migration-v2 until #378 is merged into `main` and the post-merge project state confirms acquisition recovery as canonical.

## Sequencing blockers

- #378: hardware PASS; final exact-head CI and merge pending.
- #374: waits for #378 merge and post-merge reconciliation, then close.
- #368: waits for #378 merge/reconciliation only.
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
