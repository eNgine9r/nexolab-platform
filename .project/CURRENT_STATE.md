# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `1c10f86a57dbeea9b2d410888d57d8b19a2288ab`
Active Work Package: Issue #378 / PR #380 — recover RS-485 after USB re-enumeration without recreating Device Agent
Blocked Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #374 regression status

Issue #374 / PR #375 merged the first serial-session invalidation slice as `442cd6bc37aefc11977f82f31423d052fe70ced1`. Its `except OSError:` recovery works for ordinary `OSError` transport failures, but real Raspberry Pi hotplug evidence showed a second boundary: pyserial `reset_input_buffer()` propagates `termios.error`, which is not an `OSError` subclass and therefore bypassed the merged invalidation branch.

Issue #374 remains reopened as the regression parent. Focused child Issue #378 is the only active implementation package.

## Active Issue #378 / PR #380

The first #378 layer fixed the container-visible device path:

- remove static `${RS485_HOST_DEVICE}:/dev/rs485` injection;
- mount host `/dev` read-only at `/host/dev`;
- set `SERIAL_DEVICE=/host${RS485_HOST_DEVICE}`;
- allow only Linux `ttyUSB` character major `188` through `device_cgroup_rules`;
- retain exact `/dev/serial/by-id/...` identity;
- no privileged container and no scheduler/polling change.

Software CI on `aec3cb10ea33395e8ac7472dfac433976f18cc96` was GREEN.

### First physical hotplug acceptance — failed usefully

Exact candidate `aec3cb10ea33395e8ac7472dfac433976f18cc96` ran as container `b26acda00ae8`. The container ID, start time and restart count remained unchanged. The host stable path disappeared and reappeared successfully across a real CP2104 unplug/replug:

```text
device_before: /dev/ttyUSB0
device_after: /dev/ttyUSB1
stable path absent observed: yes
stable path reappeared observed: yes
```

This proves the Compose hotplug-visible path works. Telemetry did not resume:

```text
recovery_base max(id): 2331346
final max(id): 2331346
newest_age after test: 00:07:10.22367
```

Device Agent repeatedly logged `termios.error: (5, 'Input/output error')`.

Repository diagnosis established that `ModbusRTUClient.read_holding_registers()` caught only `OSError`; Python `termios.error` is a distinct exception type, so `_invalidate_serial()` was skipped and the cached dead handle remained active even though the new `/host/dev/serial/by-id/...` path was visible.

### Current implementation

PR #380 now includes both recovery layers:

- live read-only `/host/dev` path with dynamic ttyUSB minor visibility;
- bounded `c 188:* rwm` cgroup permission and no privileged mode;
- catch `(OSError, termios.error)` at the serial transport boundary;
- invalidate/best-effort close the cached handle while preserving the original exception;
- no immediate retry storm; next normal scheduler attempt reopens the stable path;
- deterministic regression test using real `termios.error(5, "Input/output error")`;
- FC03 read-only and scheduler cadence preserved.

Exact branch candidate after the final checkpoint is:

```text
1b9feb55c8512ce250beb9b83b2ee8f72498bdda
```

Any new branch-content commit invalidates that candidate. Exact-head CI must be GREEN on that SHA before the second Raspberry Pi hotplug acceptance.

## Issue #368 blocked

Issue #368 remains software-GREEN on reconciled head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed GitHub checks
0 failures
0 in-progress
0 queued
```

The Raspberry Pi database remains safe:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

Do not run #368 migration-v2 until #378 proves acquisition resumes automatically after real CP2104 re-enumeration.

## Execution sequence

```text
#378 exact-head GREEN on 1b9feb55...
  -> install exact candidate once
  -> prove fresh telemetry before hotplug
  -> controlled same-container CP2104 unplug/replug acceptance
  -> close #378 and resolve #374 regression parent
  -> resume #368 migration-v2/latest-query physical acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure is included in #378. Physical acceptance requires only user-performed unplug/replug of the same CP2104 adapter.

## Next action

Do not change PR #380 branch content. Require exact-head CI GREEN on `1b9feb55c8512ce250beb9b83b2ee8f72498bdda`; then build/install that candidate once on the Raspberry Pi, prove fresh telemetry, and repeat same-container unplug/replug acceptance. Do not resume #368 before #378 passes.
