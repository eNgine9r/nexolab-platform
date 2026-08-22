# Dual RS-485 bus isolation

Issue: #607  
Profile: `LOCAL_LAN`  
Status: software candidate; hardware unverified

## Product boundary

NEXOLAB supports explicit logical Modbus RTU buses so independent physical RS-485 adapters can execute concurrently while every request on one physical bus remains serialized and read-only.

Planned topology:

```text
Raspberry Pi 5
├─ rs485-kk1 -> dedicated KK1 adapter / field bus
└─ rs485-kk2 -> dedicated KK2 adapter / field bus
```

The repository-backed XJP60D address catalog identifies:

- KK2: Unit IDs `101..115`;
- KK1: Unit IDs `126..138`.

Current repository evidence does **not** establish whether LE-01MP Unit IDs `200..203` belong to KK1 or KK2. They must therefore be assigned explicitly before combined `DEVICE_MODE=modbus` dual-bus operation. The runtime never guesses that ownership.

## Why the scheduler was not rewritten

`AdaptiveAcquisitionScheduler` already models jobs, workers, endpoint cooldown and scheduler metrics by `bus_id`. It already creates one worker and one lock per logical bus and can execute workers for different buses concurrently.

The previous single-bus limitation was composition above the scheduler:

- one `SERIAL_DEVICE` setting;
- one `ModbusRTUClient`;
- one XJP60D / LE-01MP reader set;
- one legacy `_bus_operation_lock` passed to every registry bus;
- initial registry identity `rs485-main`.

Issue #607 therefore changes the hardware composition boundary, not scheduler fairness/deadline behavior.

## Configuration contract

`compose.hardware.yaml` starts the bus-aware entrypoint. When `RS485_BUS_CONFIG_JSON` is empty, it delegates to the existing legacy `SERIAL_DEVICE` / `rs485-main` behavior.

When present, `RS485_BUS_CONFIG_JSON` is authoritative for physical bus bindings. It is a JSON array whose entries contain:

```json
{
  "bus_id": "rs485-kk1",
  "serial_device": "/host/dev/serial/by-id/REPLACE_WITH_STABLE_ADAPTER",
  "unit_ids": [126, 127],
  "baudrate": 9600,
  "parity": "N",
  "stopbits": 1,
  "timeout_seconds": 0.3,
  "retries": 1
}
```

Rules:

- `bus_id` is stable logical identity, not `/dev/ttyUSB*` numbering;
- production bindings must use `/dev/serial/by-id/...` or the container-visible `/host/dev/serial/by-id/...` equivalent;
- duplicate logical bus IDs fail closed;
- duplicate physical serial paths fail closed;
- every registry device must have one explicit Unit-ID ownership in explicit mode;
- a Unit ID cannot be assigned ambiguously to two configured physical buses in the current registry identity model;
- invalid serial settings or malformed JSON fail before acquisition starts;
- configured buses may contain no active targets, which supports software-defined future hardware without claiming acceptance.

See `infrastructure/compose/.env.dual-rs485.example` for a non-production example. It is not a cutover procedure.

## Runtime isolation

Explicit mode creates for every configured bus:

- one `ModbusRTUClient`;
- one physical operation lock;
- one XJP60D reader when that family is enabled;
- one LE-01MP reader when that family is enabled;
- one scheduler worker when the registry has eligible targets on that bus.

The scheduler receives the individual bus locks directly. A normal read on KK1 therefore cannot serialize an unrelated normal read on KK2.

Registry and legacy active-point mutations are different: they can alter the active acquisition topology. Those operations use a composite guard that acquires **all** configured bus locks in deterministic `bus_id` order before mutating/reconciling the registry. This prevents a lifecycle/topology mutation from racing an in-flight physical read on either bus.

## Discovery and adoption

XJP60D discovery remains explicit and read-only.

In explicit topology mode:

1. configured discovery Unit IDs are partitioned by bus ownership;
2. each bus is scanned only through its own client and lock;
3. discovery evidence carries `bus_id`;
4. a newly responsive controller is enrolled as `discovery_only` on the bus on which it was actually scanned;
5. the enrollment is persisted to the local acquisition registry with revision/audit evidence;
6. enrollment alone creates no recurring scheduler job;
7. later authorized lifecycle activation reconciles the scheduler using the persisted bus identity.

This preserves the discovery/adoption semantics that existed before Issue #607 instead of silently dropping new controllers in dual-bus mode.

## Diagnostics

Local acquisition diagnostics expose one item per configured bus with:

- logical `bus_id`;
- stable serial-device path;
- device-path presence;
- `hardware_state` and `acceptance_state`;
- configured / registry / active device counts;
- active target count;
- serial settings;
- scheduler worker/queue/fairness/cooldown/lag/load metrics;
- bounded physical request totals;
- request rate over the recent 60-second window;
- retry, timeout, protocol-error, I/O-error and exception-response counters;
- recent request-latency average, p95 and maximum.

Observability never initiates acquisition.

If a configured bus has active recurring targets but its stable serial path is absent, top-level health fails closed. A configured bus with **no active targets** may remain `configured_unavailable` / `hardware_unverified` without failing the active runtime.

## Read-only and offline guarantees

Issue #607 introduces no Modbus write function. The transport remains the existing strict FC03 read-only client.

No mandatory internet, cloud service, CDN, external API, telemetry service or paid runtime dependency is introduced. Bus configuration, registry persistence, diagnostics and scheduling are local.

## Relationship to Issue #589

Issue #589 owns persistent acquisition cadence and capacity validation. Its implementation must consume the first-class `bus_id` boundary established here:

- capacity is evaluated independently per physical bus;
- measured request latency/retries/timeouts are available per bus;
- one bus overload cannot be represented as a single global capacity number;
- device cadence resolution must preserve device-to-bus ownership;
- browser/WebSocket activity remains absent from physical job creation.

Issue #607 does **not** implement the operator cadence mutation domain from #589.

## Hardware acceptance boundary

Software tests can prove logical isolation and concurrency without physical adapters. They cannot prove wiring or adapter identity.

Until a separately approved hardware action is performed, report:

```text
software: candidate / later software_verified after GREEN CI
hardware: unverified
site cutover: not performed
Modbus writes: none
```

Future hardware acceptance must record the exact two `/dev/serial/by-id/...` paths, simultaneous read-only polling, per-bus request evidence, one-bus disconnect isolation and reboot-stable adapter mapping. No field wiring change is authorized by this Work Package.
