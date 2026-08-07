# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `1c10f86a57dbeea9b2d410888d57d8b19a2288ab`
Active Work Package: Issue #378 / PR #380 — recover RS-485 after USB re-enumeration without recreating Device Agent
Blocked Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #374 regression status

Issue #374 / PR #375 merged the valid serial-session invalidation fix as `442cd6bc37aefc11977f82f31423d052fe70ced1`. The fix closes and clears a cached pyserial handle after transport `OSError`/EIO so a later scheduler attempt opens a new handle. Its software verification remains valid.

The original short Raspberry Pi acceptance is no longer sufficient as a completion criterion. Long-duration evidence from the same `nexolab-device-agent:issue-374` candidate reproduced acquisition loss after a real CP2104 USB disconnect/re-enumeration:

```text
Device Agent container: running / healthy
mqtt_connected: true
last_sample_at: 2026-08-07T10:55:00.478390+00:00
last_publish_at: 2026-08-07T10:55:00.728022+00:00
last_error: adaptive acquisition degraded: 8 endpoint(s) failing or in cooldown
PostgreSQL max(id): 2329963
newest telemetry age at diagnosis: ~1h10m
```

Kernel evidence aligns with the stop point:

```text
13:55:00+03 CP2104 disconnects from ttyUSB1
13:55:01+03 same serial 0133F090 re-enumerates on ttyUSB0
13:57:09+03 another disconnect/reconnect
15:04:48/49+03 another disconnect/reconnect
```

The host stable path correctly followed the device to `ttyUSB0`, but the already-created container continued using the stale `/dev/rs485` device mapping and repeated `termios.error: (5, 'Input/output error')`.

Issue #374 is therefore reopened as a regression record and blocked by focused child Issue #378.

## Active Issue #378 / PR #380

Issue #378 is the single active implementation Work Package. Branch:

```text
fix/378-rs485-usb-hotplug-recovery
```

Draft PR #380 changes the hardware Compose boundary so the running Device Agent can resolve the live host stable by-id path after `ttyUSB` minor changes:

- remove static `${RS485_HOST_DEVICE}:/dev/rs485` device injection;
- mount host `/dev` read-only at `/host/dev`;
- set `SERIAL_DEVICE=/host${RS485_HOST_DEVICE}`;
- allow only the current CP210x `ttyUSB` character-device class (`c 188:* rwm`) so the minor may change on hotplug;
- keep exact `RS485_HOST_DEVICE=/dev/serial/by-id/...` identity authoritative;
- no `privileged: true`, no scheduler change and no Device Agent Python change.

Deterministic Docker Compose contract validation is GREEN on implementation head `1fe7d2b1051293ce55062159b03d3828684cd6bc` for the hotplug-visible path, absence of static device mapping, bounded cgroup rule and read-only host `/dev` bind. Full exact-head CI will be rerun after the project-state checkpoint commit.

Physical completion still requires a controlled Raspberry Pi acceptance where the exact candidate is installed once, the container ID is recorded, the same CP2104 is physically unplugged/replugged, and telemetry resumes with the same container ID and no manual restart/recreate.

## Issue #368 blocked

Issue #368 remains software-GREEN but physical migration-v2 acceptance is blocked until #378 proves stable acquisition across USB re-enumeration.

PR #373 reconciled software head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed GitHub checks
0 failures
0 in-progress
0 queued
```

The Raspberry Pi database remains safe after the rejected precondition runs:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

Do not run #368 migration-v2 while telemetry is stale.

## Execution sequence

```text
#378 exact-head GREEN
  -> controlled Raspberry Pi CP2104 unplug/replug acceptance with same container ID
  -> close #378 and resolve #374 regression record
  -> resume #368 migration-v2/latest-query physical acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing toolchain compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure is included in #378. The later physical acceptance requires only a user-performed unplug/replug of the same CP2104 adapter.

## Next action

Complete exact-head CI/review for PR #380. If GREEN, build the exact candidate on the Raspberry Pi, recreate only Device Agent once to install it, then perform controlled unplug/replug acceptance without any further container restart or recreate.
