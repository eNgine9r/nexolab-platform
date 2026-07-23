# NEXOLAB Device Agent

The Device Agent samples Edge telemetry, publishes it to MQTT with QoS 1, and stores events in SQLite while MQTT is unavailable.

## Modes

### Simulator

`DEVICE_MODE=simulator` remains the default and does not access serial hardware.

### Dixell XJP60D

The opt-in hardware mode reads the validated XJP60D v1.6 profile:

- Modbus RTU `9600 8N1`;
- FC03 only;
- exactly one register per request;
- signed 16-bit probe value with scale `0.1`;
- adjacent status register masked with `0x0003`;
- no Modbus writes.

Example configuration:

```dotenv
DEVICE_MODE=xjp60d
SERIAL_DEVICE=/dev/rs485
SERIAL_BAUDRATE=9600
SERIAL_PARITY=N
SERIAL_STOPBITS=1
SERIAL_TIMEOUT_SECONDS=0.30
SERIAL_RETRIES=1
XJP60D_POINTS=106:3,106:4
XJP60D_SCALE=0.1
```

Point syntax is `UNIT_ID:CHANNEL`, where the channel is `1..6`.

## Telemetry

A valid high-alarm reading is published as:

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

When the status mask is `3`, the raw value is retained for diagnostics but the published value is `null`, quality is `sensor_error`, and alarm is `probe_error`. Communication failures use `quality=communication_error`.

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

Before cutover, stop every other Modbus master on the same RS-485 segment and confirm `RS485_HOST_DEVICE` points to the stable `/dev/serial/by-id/...` adapter path.
