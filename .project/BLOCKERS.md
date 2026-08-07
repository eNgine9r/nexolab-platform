# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #374 — runtime blocker resolved, merge pending

The controlled Raspberry Pi serial-session recovery acceptance has passed on exact candidate `8543bebad6149ac9c23be75b60d85830e980509e`.

Original blocker:

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

Repository inspection proved `ModbusRTUClient` retained the failed cached serial descriptor after `OSError`. PR #375 fixes that boundary by invalidating/closing the failed handle and allowing the next normal scheduler attempt to reopen the existing configured stable serial path. No scheduler production-code change, polling amplification or Modbus write was introduced.

Controlled Raspberry Pi acceptance after candidate recreate:

```text
stable path: /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0 -> ttyUSB1
PostgreSQL max(id): 2327052 -> 2327095 in first 10 seconds
newest telemetry age: 00:00:19.499133
Device Agent status: ok
mqtt_connected: true
last_error: null
degraded_endpoints: 0
cooldown_endpoints: 0
active_bus_workers: 1
communication_failures_total: 0
cooldown_entered_total: 0
recent EIO/ERROR/WARNING/Traceback matches: 0
```

Classification:

```text
software verified;
Raspberry Pi serial recovery hardware verified;
final evidence-head CI and merge pending
```

The runtime blocker is therefore resolved. #374 remains open only until PR #375 receives final exact-head GREEN after the evidence/state checkpoint and is merged.

This acceptance proves recovery from the observed poisoned serial-session failure mode. It does not claim that every future physical USB/TTY EIO root cause is eliminated.

## Issue #368 — ready to resume after #374 merge

PR #373 latest-projection software remains verified on `cb082621f8b5e4cedf44534f3b5256fb2817d55a` with 26 completed checks, zero failures and zero in-progress checks.

The prior migration-v2 retry did not fail migration-v2; its precondition monitor rejected stale ingestion caused by the #374 serial EIO defect. Automatic rollback left:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
```

Because acquisition freshness is now physically verified, #368 can resume immediately after #374 is merged/closed. Its remaining acceptance must prove migration-v2/latest-query behavior on the existing long-running Raspberry Pi PostgreSQL database.

## Sequencing blockers

- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence so read-model work is not validated against an incomplete runtime path.
- #289 remains the downstream final acquisition/route-latency/hardware matrix after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, or unsupported physical acceptance claims.
