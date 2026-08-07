# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #378 — active critical blocker for physical acceptance

Issue #378 / PR #380 is the active Work Package after long-duration Raspberry Pi evidence proved that the merged #374 serial-handle invalidation is not sufficient across real CP2104 USB disconnect/re-enumeration.

Observed runtime sequence:

```text
Device Agent image: nexolab-device-agent:issue-374
container: running / healthy
mqtt_connected: true
last_sample_at: 2026-08-07T10:55:00.478390+00:00
PostgreSQL max(id): 2329963
newest telemetry age at diagnosis: ~1h10m

13:55:00+03 CP2104 disconnects from ttyUSB1
13:55:01+03 same serial re-enumerates on ttyUSB0
```

The host stable path correctly moved to the new `ttyUSB0` target, but the already-created container remained bound to the stale `/dev/rs485` device mapping and subsequent reads repeatedly failed with `termios.error: (5, 'Input/output error')`.

Repository diagnosis:

- #374 correctly invalidates the cached pyserial handle;
- `compose.hardware.yaml` previously injected `${RS485_HOST_DEVICE}:/dev/rs485` through Docker `devices:`;
- that mapping is fixed when the container is created and does not follow a later by-id symlink target/minor change;
- therefore reopening `/dev/rs485` after #374 still reopens the stale container device node.

PR #380 replaces that runtime boundary with a read-only host `/dev` view at `/host/dev`, exact `SERIAL_DEVICE=/host${RS485_HOST_DEVICE}`, and a bounded `c 188:* rwm` cgroup rule for the current CP210x `ttyUSB` class. No `privileged: true`, scheduler change or Device Agent Python change is included.

Deterministic Docker Compose contract validation passed on implementation head `1fe7d2b1051293ce55062159b03d3828684cd6bc`. Final exact-head CI is required after the project-state checkpoint.

Completion requires controlled Raspberry Pi evidence where the exact candidate is installed once, the Device Agent container ID is recorded, the same CP2104 adapter is unplugged/replugged, and telemetry resumes without restarting/recreating the container.

## Issue #374 — reopened regression parent

Issue #374 / PR #375 remains a valid merged software slice for cached serial-handle invalidation, but the previous short hardware acceptance is invalidated as a completion criterion by the later re-enumeration failure.

Issue #374 is reopened and `status:blocked` on focused child #378. Do not create a second implementation PR under #374.

## Issue #368 — blocked by acquisition stability

Issue #368 / PR #373 is software-GREEN on reconciled head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed checks
0 failures
0 in-progress
0 queued
```

Physical migration-v2/latest-query acceptance is blocked until #378 restores reliable telemetry across USB re-enumeration. The Raspberry Pi database remains safe:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

Do not run #368 migration-v2 while telemetry freshness is stale.

## Sequencing blockers

- #374 regression record waits for #378 physical hotplug PASS.
- #368 waits for #378 physical hotplug PASS.
- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence.
- #289 remains the downstream final acquisition/route-latency/hardware matrix after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, privileged hardware containers, or unsupported physical acceptance claims.
