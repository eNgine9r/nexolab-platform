# NEXOLAB Device Agent

The Device Agent samples Edge telemetry, publishes it to MQTT with QoS 1, and stores events in SQLite while MQTT is unavailable.

## Modes

### Simulator

`DEVICE_MODE=simulator` remains the default and does not access serial hardware.

### Dixell XJP60D

`DEVICE_MODE=xjp60d` reads the validated XJP60D v1.6 profile:

- Modbus RTU `9600 8N1`;
- FC03 only;
- exactly one register per request;
- signed 16-bit probe value with scale `0.1`;
- adjacent status register masked with `0x0003`;
- no Modbus writes.

```dotenv
DEVICE_MODE=xjp60d
XJP60D_POINTS=106:3,106:4
XJP60D_SCALE=0.1
```

Point syntax is `UNIT_ID:CHANNEL`, where the channel is `1..6`.

### F&F LE-01MP

`DEVICE_MODE=le01mp` reads the validated high-confidence subset for meters `200–203`:

- voltage, current and frequency with scale `0.1`;
- active, reactive and apparent power with scale `1`;
- power factor with scale `0.001`;
- internal temperature from register `37`;
- one FC03 register per request;
- no Modbus writes.

```dotenv
DEVICE_MODE=le01mp
LE01MP_UNIT_IDS=200,201,202,203
```

Register `7`, observed as a cumulative-energy candidate, is deliberately excluded from production telemetry until its scale and rollover behavior are independently confirmed.

### Combined Modbus acquisition

`DEVICE_MODE=modbus` schedules both configured driver families through the read-only adaptive acquisition runtime. In legacy single-bus mode both families use the configured `SERIAL_DEVICE`. In explicit multi-bus mode each registry device is dispatched to the `ModbusRTUClient` owned by its logical `bus_id`.

```dotenv
DEVICE_MODE=modbus
XJP60D_POINTS=106:3,106:4
XJP60D_SCALE=0.1
LE01MP_UNIT_IDS=200,201,202,203
```

The legacy `xjp60d` mode remains supported for the already validated two-channel hardware smoke test.

## Persisted adaptive acquisition

Hardware modes derive recurring jobs only from registry-eligible targets.

Acquisition Registry schema v2 is the durable cadence authority. Effective cadence resolves as:

1. device-specific override;
2. logical bus + device-family default.

Supported operator presets are `10`, `30` and `60` seconds. Custom values are bounded to `10..3600` seconds. Values below 10 seconds fail closed.

Scheduler priority remains separate from cadence:

- XJP60D temperature/status targets are `high` priority;
- operational LE-01MP metrics are `medium` priority;
- slower LE-01MP diagnostics are `low` priority;
- discovery/configuration operations are `on_demand`.

Priority controls ordering and bounded fairness among due jobs only. It does not determine the recurring polling interval.

Legacy acquisition interval environment values are used only when bootstrapping an old registry into schema v2. Migration never accelerates the historical polling policy, increments the registry revision and records a one-time audit event.

Cadence is available through the local Device Agent control plane:

```text
GET /api/v1/acquisition-cadence
PUT /api/v1/acquisition-cadence
```

A PUT requires optimistic `expected_revision`, an audit reason and the existing authorized actor boundary. The proposed candidate is evaluated against the RS-485 capacity model before SQLite commit. Unsafe cadence returns `422 acquisition_capacity_exceeded` without changing revision, audit or scheduler state.

Capacity is evaluated per physical `bus_id` with a 75% maximum estimated utilization and 25% safety margin. The model includes production request count, retry reserve, Modbus RTU inter-frame silence and timeout or sufficiently sampled measured p95 latency. Measured p95 becomes authoritative only after at least 20 physical request samples on that bus. Cooldown is never counted as spare capacity.

A lifecycle change that adds new poll-eligible targets also receives the same pre-commit capacity check. Deactivation remains permitted even when the current baseline is overloaded.

Scheduler and latest-value evidence is available locally:

```text
GET /metrics
GET /health
GET /ready
GET /api/v1/acquisition-latest
GET /api/v1/acquisition-cadence
```

Reading these endpoints never initiates Modbus acquisition.

See:

- `docs/architecture/persisted-acquisition-cadence.md`;
- `docs/operations/adaptive-acquisition-scheduler.md`.

Final physical site cadence remains hardware-unverified until measured on the actual Raspberry Pi, adapters and RS-485 topology.

## Serial configuration

### Legacy single-bus configuration

```dotenv
SERIAL_DEVICE=/dev/rs485
SERIAL_BAUDRATE=9600
SERIAL_PARITY=N
SERIAL_STOPBITS=1
SERIAL_TIMEOUT_SECONDS=0.30
SERIAL_RETRIES=1
```

### Explicit isolated buses

The hardware Compose overlay uses `dual_bus_main.py`. When `RS485_BUS_CONFIG_JSON` is empty, the entrypoint preserves the exact legacy `SERIAL_DEVICE` / `rs485-main` path.

When the variable is set, it must describe every physical bus explicitly. Production device paths must be stable `/dev/serial/by-id/...` identities as visible in the container under `/host/dev/serial/by-id/...`.

Example shape:

```json
[
  {
    "bus_id": "rs485-kk1",
    "serial_device": "/host/dev/serial/by-id/REPLACE_WITH_KK1_ADAPTER",
    "unit_ids": [126, 127, 128],
    "baudrate": 9600,
    "parity": "N",
    "stopbits": 1,
    "timeout_seconds": 0.3,
    "retries": 1
  },
  {
    "bus_id": "rs485-kk2",
    "serial_device": "/host/dev/serial/by-id/REPLACE_WITH_KK2_ADAPTER",
    "unit_ids": [101, 102, 103],
    "baudrate": 9600,
    "parity": "N",
    "stopbits": 1,
    "timeout_seconds": 0.3,
    "retries": 1
  }
]
```

The current XJP60D catalog maps KK2 to Unit IDs `101..115` and KK1 to `126..138`. LE-01MP Unit IDs `200..203` have no repository-backed KK1/KK2 ownership yet and must be assigned explicitly before combined dual-bus operation.

Duplicate bus IDs, duplicate stable paths, ambiguous Unit ownership, malformed serial settings and unassigned registry devices fail closed. Discovery is partitioned by bus and newly responsive controllers are persisted as `discovery_only` on the bus where they were read.

`GET /metrics` and health payloads expose per-bus scheduler state plus bounded physical request rate, retry/timeout/error counters and recent latency average/p95/max. A missing configured bus with active targets fails health closed. A configured bus with no active targets remains hardware-unverified without failing the active runtime.

See:

- `docs/architecture/dual-rs485-bus-isolation.md`;
- `infrastructure/compose/.env.dual-rs485.example`.

## Telemetry

A valid XJP60D high-alarm reading is published as:

```json
{
  "metric": "temperature.probe",
  "value": 26.0,
  "unit": "degC",
  "quality": "valid",
  "source": "dixell-xjp60d",
  "equipment_id": "K106",
  "channel_id": "106-03",
  "alarm": "high",
  "raw_value": 260,
  "raw_status": 4354
}
```

A meter voltage reading is published as:

```json
{
  "metric": "electrical.voltage",
  "value": 230.1,
  "unit": "V",
  "quality": "valid",
  "source": "f-and-f-le-01mp",
  "equipment_id": "LE01MP-201",
  "channel_id": "201-voltage",
  "raw_value": 2301
}
```

XJP60D status mask `3` suppresses the decoded value and publishes `quality=sensor_error`. Per-target Modbus failures publish `quality=communication_error` without removing the last successful value from the local latest-value read model.

## Tests

```bash
python -m pip install -r services/device-agent/requirements.txt
PYTHONPATH=services/device-agent \
  python -m unittest discover -s services/device-agent/tests -v
```

## Hardware cutover

The serial device is not mounted by the default Edge stack. Hardware mode requires the explicit override:

```bash
cd infrastructure/compose

docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  up -d device-agent
```

`compose.hardware.yaml` defaults to `HARDWARE_DEVICE_MODE=xjp60d` for backward compatibility. Set `HARDWARE_DEVICE_MODE=modbus` only for an explicit combined validation of XJP60D and LE-01MP.

Before any physical cutover, stop every other Modbus master on the affected RS-485 segment and confirm every configured adapter path is the intended stable `/dev/serial/by-id/...` identity. Issue #589 does not authorize wiring changes, hardware writes or site cutover.
