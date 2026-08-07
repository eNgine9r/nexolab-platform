# NEXOLAB Blockers

Updated: 2026-08-07

## Active critical runtime blocker — Issue #374

Controlled Raspberry Pi acceptance for Issue #368 cannot continue until Device Agent acquisition freshness is restored.

Actual evidence:

```text
Device Agent container/process: healthy
Device Agent status: degraded
MQTT connected: true
PostgreSQL/Telemetry Service: healthy
telemetry last sample/publish: 2026-08-07T09:53:34Z
PostgreSQL max telemetry id at diagnosis: 2327052
serial exception: termios.error: (5, 'Input/output error')
location: reset_input_buffer() before the Modbus request is transmitted
```

Repository inspection proved `ModbusRTUClient` retained the failed cached serial descriptor after `OSError`. Because the client is shared by the serialized bus worker, subsequent endpoints reused the same unusable descriptor and entered scheduler cooldown one after another.

Issue #374 / PR #375 is the focused correction. The failed handle is invalidated and closed best-effort; the next normal scheduler attempt may reopen the existing configured stable path. There is no immediate EIO retry loop, no polling amplification and no Modbus write.

Classification:

```text
software fix under final exact-head verification;
Raspberry Pi serial-session recovery unverified
```

If a fresh handle still receives EIO after #374 is deployed, the remaining blocker becomes physical/host USB/TTY evidence. Do not claim the adapter/cabling/power path is repaired without kernel and real hardware evidence.

## Issue #368 — physical acceptance temporarily blocked by #374

PR #373 latest-projection software remains verified on `cb082621f8b5e4cedf44534f3b5256fb2817d55a` with its previous 26-check GREEN exact-head run.

The latest migration-v2 attempt was rejected by its precondition monitor because telemetry was already stale (`newest_age ~612 s`). No migration-v2 performance conclusion can be drawn from that run.

Automatic rollback left:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
```

Resume #368 only after #374 proves telemetry freshness on the controlled Raspberry Pi.

## Sequencing blockers

- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence so read-model work is not validated against a known-broken acquisition/runtime state.
- #289 remains the downstream final acquisition/route-latency/hardware matrix after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, or unsupported physical acceptance claims.
