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

### Combined Modbus polling

`DEVICE_MODE=modbus` polls both configured driver families sequentially through one serial client:

```dotenv
DEVICE_MODE=modbus
XJP60D_POINTS=106:3,106:4
XJP60D_SCALE=0.1
LE01MP_UNIT_IDS=200,201,202,203
```

The legacy `xjp60d` mode remains supported for the already validated two-channel hardware smoke test.

## Serial configuration

```dotenv
SERIAL_DEVICE=/dev/rs485
SERIAL_BAUDRATE=9600
SERIAL_PARITY=N
SERIAL_STOPBITS=1
SERIAL_TIMEOUT_SECONDS=0.30
SERIAL_RETRIES=1
```

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

XJP60D status mask `3` suppresses the decoded value and publishes `quality=sensor_error`. Per-register Modbus failures publish `quality=communication_error` without dropping healthy points from the same cycle.

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

Before cutover, stop every other Modbus master on the same RS-485 segment and confirm `RS485_HOST_DEVICE` points to the stable `/dev/serial/by-id/...` adapter path.
