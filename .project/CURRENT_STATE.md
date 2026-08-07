# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `1c10f86a57dbeea9b2d410888d57d8b19a2288ab`
Active Work Package: Issue #378 / PR #380 — recover RS-485 after USB re-enumeration without recreating Device Agent
Blocked Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #374 regression status

Issue #374 / PR #375 merged the first serial-session invalidation slice as `442cd6bc37aefc11977f82f31423d052fe70ced1`. Its `except OSError:` recovery works for ordinary `OSError` transport failures, but real Raspberry Pi hotplug evidence has now shown a second boundary: pyserial `reset_input_buffer()` propagates `termios.error`, which is not an `OSError` subclass and therefore bypassed the merged invalidation branch.

Issue #374 remains reopened as the regression parent. Do not create another implementation PR under #374; focused child Issue #378 is the active implementation package.

## Active Issue #378 / PR #380

Branch:

```text
fix/378-rs485-usb-hotplug-recovery
```

The first #378 implementation added a hotplug-visible container path:

- remove static `${RS485_HOST_DEVICE}:/dev/rs485` device injection;
- mount host `/dev` read-only at `/host/dev`;
- set `SERIAL_DEVICE=/host${RS485_HOST_DEVICE}`;
- allow only Linux `ttyUSB` character major `188` through `device_cgroup_rules`;
- keep the exact `/dev/serial/by-id/...` identity authoritative;
- no privileged container and no polling/scheduler change.

Software CI on `aec3cb10ea33395e8ac7472dfac433976f18cc96` was GREEN, including Quality and Offline Bundle.

### First physical hotplug acceptance — failed usefully

Exact candidate `aec3cb10ea33395e8ac7472dfac433976f18cc96` was installed as `nexolab-device-agent:issue-378`. Candidate container:

```text
b26acda00ae8
```

The container remained the same throughout the test:

```text
restart_count: 0 -> 0
started_at: unchanged
container id: unchanged
```

The host stable path disappeared and reappeared successfully across a real CP2104 unplug/replug:

```text
device_before: /dev/ttyUSB0
stable path absent observed: yes
device_after: /dev/ttyUSB1
stable path reappeared observed: yes
```

This proves the Compose hotplug-visible path layer works. However telemetry did not resume. PostgreSQL remained at:

```text
recovery_base_max_id: 2331346
final max_id: 2331346
newest_age after test: ~7m10s
```

Device Agent repeatedly logged:

```text
termios.error: (5, 'Input/output error')
```

Repository diagnosis found that `ModbusRTUClient.read_holding_registers()` only caught `OSError`, while Python `termios.error` is a distinct `Exception` type rather than an `OSError` subclass. Therefore `_invalidate_serial()` was never called for the real `tcflush()` failure, so the cached dead handle remained in use even though the new `/host/dev/serial/by-id/...` path was visible.

### Current implementation

PR #380 now contains the second recovery layer:

- import `termios` in the Linux Device Agent Modbus client;
- catch `(OSError, termios.error)` as bounded serial transport failures;
- preserve the original exception;
- invalidate/close the cached handle exactly as #374 intended;
- let the next normal scheduler attempt reopen the same stable by-id path;
- add a deterministic regression test using a real `termios.error(5, "Input/output error")` exception class;
- retain the Compose hotplug-visible `/host/dev` contract.

Implementation head after the code/test fix:

```text
b71040bda3b56f835af883bbe33a682060344518
```

Fresh CI is running on that head. A final project-state checkpoint will produce the final hardware candidate SHA; only that final exact head may be used for the second Raspberry Pi unplug/replug acceptance.

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
#378 termios-aware exact-head GREEN
  -> install final candidate once
  -> controlled same-container CP2104 ttyUSB minor-change unplug/replug acceptance
  -> close #378 and resolve #374 regression parent
  -> resume #368 migration-v2/latest-query physical acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing toolchain compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure is included in #378. The physical acceptance requires only a user-performed unplug/replug of the same CP2104 adapter.

## Next action

Complete fresh CI on the termios-aware implementation, checkpoint the final exact head, rerun exact-head CI if the checkpoint changes the SHA, then install that candidate once on the Raspberry Pi and repeat the same-container unplug/replug acceptance. Do not resume #368 before #378 passes.
