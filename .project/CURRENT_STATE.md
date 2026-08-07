# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `1c10f86a57dbeea9b2d410888d57d8b19a2288ab`
Active Work Package: Issue #378 / PR #380 — recover RS-485 after USB re-enumeration without recreating Device Agent
Next blocked Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #378 / PR #380 — hardware verified, final CI pending

PR #380 contains both required recovery layers:

- remove static `${RS485_HOST_DEVICE}:/dev/rs485` injection;
- mount host `/dev` read-only at `/host/dev`;
- set `SERIAL_DEVICE=/host${RS485_HOST_DEVICE}`;
- allow only Linux `ttyUSB` character major `188` through `device_cgroup_rules`;
- retain exact `/dev/serial/by-id/...` identity;
- catch `(OSError, termios.error)` at the serial transport boundary;
- invalidate/best-effort close the cached handle while preserving the original exception;
- reopen only on the next normal scheduler attempt;
- preserve FC03 read-only behavior, scheduler cadence and one-worker-per-bus;
- no privileged container.

Software CI on exact pre-hardware candidate `c2cf1ce4939c77f138daac2841f39651afd4bcba` completed GREEN with 14 checks, 0 failures and 0 in-progress, including Quality/build and Offline Bundle.

### Raspberry Pi physical acceptance — PASS

Phase 1 proved fresh real acquisition before hotplug:

```text
candidate: c2cf1ce4939c77f138daac2841f39651afd4bcba
container: 9f03df0e798e
restart_count: 0
PostgreSQL max(id): 2331346 -> 2331419
newest_age: ~18 s
Device Agent status: ok
mqtt_connected: true
last_error: none
degraded_endpoints: 0
cooldown_endpoints: 0
```

Phase 2 performed a controlled unplug/replug of the same CP2104 `0133F090` without restarting or recreating Device Agent:

```text
container_before: 9f03df0e798e
container_after: 9f03df0e798e
started_at before/after: unchanged
restart_count: 0 -> 0
stable by-id path disappeared: yes
device_before: /dev/ttyUSB1
stable by-id path reappeared: yes
device_after: /dev/ttyUSB0
PostgreSQL max(id) at reappearance: 2332589
first recovery max(id): 2332595
final observed max(id): 2332624
newest_age after recovery: ~18-21 s
```

Transient `termios.error` and ENOENT warnings occurred only while the physical adapter/path was absent. Acquisition recovered automatically after re-enumeration on the same running container. This satisfies the hardware acceptance boundary for #378.

## Issue #374 regression status

Issue #374 / PR #375 remains the merged first serial-session invalidation slice. Its long-duration USB re-enumeration regression is now physically resolved by child Issue #378. Keep #374 open only until PR #380 merges and post-merge state reconciliation confirms the fix in `main`; then close #374 as completed regression parent.

## Issue #368 status

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

#368 is now blocked only by final #378 merge/post-merge reconciliation. Do not run migration-v2 until #378 is merged into `main` and the canonical Device Agent recovery state is reconciled.

## Execution sequence

```text
#378 hardware PASS
  -> final hardware-result state checkpoint
  -> exact-head CI GREEN
  -> final focused review/base audit
  -> mark PR #380 Ready and squash merge
  -> post-merge state reconciliation
  -> close #378 and resolve #374 regression parent
  -> resume #368 migration-v2/latest-query physical acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure was performed during #378 acceptance.

## Next action

Freeze PR #380 branch after this hardware-result state checkpoint. Require exact-head CI GREEN on the resulting branch head, then perform final focused diff/review/base audit and merge only if GREEN. After merge, reconcile project state and resume #368.
