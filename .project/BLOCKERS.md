# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #378 — active critical blocker for physical acceptance

Issue #378 / PR #380 remains the single active Work Package. The first controlled Raspberry Pi hotplug acceptance proved the new Compose path is visible across CP2104 re-enumeration, but telemetry still failed to resume.

Physical evidence:

```text
candidate container: b26acda00ae8
container id before/after: unchanged
restart_count: 0 -> 0
started_at: unchanged
device_before: /dev/ttyUSB0
stable by-id path disappeared: yes
device_after: /dev/ttyUSB1
stable by-id path reappeared: yes
recovery_base PostgreSQL max(id): 2331346
final PostgreSQL max(id): 2331346
final newest_age: 00:07:10.22367
```

The Device Agent continued logging:

```text
termios.error: (5, 'Input/output error')
```

The Compose-only layer is therefore validated: the running container can see the updated stable by-id path after `ttyUSB0 -> ttyUSB1` without restart/recreate.

The remaining root cause is in the Modbus client exception boundary. `ModbusRTUClient.read_holding_registers()` caught only `OSError`, but Python `termios.error` is a distinct `Exception` type and bypassed `_invalidate_serial()`. The cached dead handle therefore remained in use even though the new stable path was available.

PR #380 now also:

- catches `(OSError, termios.error)` only for bounded serial transport failures;
- invalidates/closes the cached handle while preserving the original exception;
- allows the next normal scheduler attempt to reopen the exact stable by-id path;
- adds a deterministic regression test using a real `termios.error(5, "Input/output error")`;
- preserves FC03 read-only behavior, scheduler cadence and one-worker-per-bus;
- retains the read-only `/host/dev` mount and bounded `c 188:* rwm` rule;
- does not use privileged mode.

Implementation head before final project-state checkpoint:

```text
b71040bda3b56f835af883bbe33a682060344518
```

Fresh CI is running. After the final state checkpoint, exact-head CI must be GREEN again before repeating physical hotplug acceptance.

## Issue #374 — reopened regression parent

Issue #374 / PR #375 remains a valid merged partial fix for ordinary `OSError` serial invalidation. Its previous completion claim is not sufficient for real USB re-enumeration because real `tcflush()` failures propagate `termios.error`.

Issue #374 remains reopened and blocked by child #378. Do not create a second implementation PR under #374.

## Issue #368 — blocked by acquisition stability

Issue #368 / PR #373 remains software-GREEN on reconciled head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed checks
0 failures
0 in-progress
0 queued
```

Physical migration-v2/latest-query acceptance is blocked until #378 proves that telemetry resumes automatically after real CP2104 disconnect/re-enumeration.

The Raspberry Pi database remains safe:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

Do not run #368 migration-v2 while telemetry freshness is not proven stable.

## Sequencing blockers

- #374 regression record waits for #378 physical hotplug PASS.
- #368 waits for #378 physical hotplug PASS.
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
