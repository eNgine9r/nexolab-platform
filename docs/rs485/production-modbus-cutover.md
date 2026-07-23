# Production Modbus cutover

## Purpose

Enable the validated combined XJP60D and LE-01MP profile as the persistent Device Agent mode on `nexolab-edge-01`.

This runbook assumes the combined smoke test, soak test, MQTT recovery retest, and simulator rollback have already passed.

## Approved scope

- XJP60D points: `106-03`, `106-04`;
- LE-01MP unit IDs: `200`, `201`, `202`, `203`;
- serial profile: Modbus RTU `9600 8N1`;
- function: FC03 only;
- request size: one register per request;
- expected telemetry records per complete cycle: `34`.

## Preconditions

1. No scanner, profiler, XWEB, PLC, or another Modbus master may poll the same RS-485 segment.
2. The adapter must resolve through its stable `/dev/serial/by-id/...` path.
3. The base `.env` must keep `DEVICE_MODE=simulator` so rollback remains a single Compose command.
4. The hardware override must set `HARDWARE_DEVICE_MODE=modbus`.
5. The latest Device Agent image must contain the MQTT queue recovery fix from PR #30.

## Configuration

The required `.env` values are:

```dotenv
DEVICE_MODE=simulator
HARDWARE_DEVICE_MODE=modbus
RS485_HOST_DEVICE=/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0
RS485_GROUP_GID=20
XJP60D_POINTS=106:3,106:4
XJP60D_SCALE=0.1
LE01MP_UNIT_IDS=200,201,202,203
SERIAL_TIMEOUT_SECONDS=0.30
SERIAL_RETRIES=1
```

## Preflight

```bash
cd ~/nexolab-platform/infrastructure/compose

RS485_HOST_DEVICE="$(
  awk -F= '$1=="RS485_HOST_DEVICE" {
    print substr($0, index($0, "=") + 1)
  }' .env
)"

RESOLVED_DEVICE="$(readlink -f "$RS485_HOST_DEVICE")"

test -e "$RS485_HOST_DEVICE"
sudo fuser -v "$RESOLVED_DEVICE" || true
```

The `fuser` command must not report another local process using the serial port.

Render the final Compose configuration before the cutover:

```bash
docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  config > /tmp/nexolab-production-modbus.yaml

grep -nE \
  'DEVICE_MODE|SERIAL_DEVICE|SERIAL_BAUDRATE|SERIAL_PARITY|SERIAL_STOPBITS|XJP60D_POINTS|LE01MP_UNIT_IDS|/dev/rs485' \
  /tmp/nexolab-production-modbus.yaml
```

Expected values include:

```text
DEVICE_MODE: modbus
SERIAL_DEVICE: /dev/rs485
SERIAL_BAUDRATE: "9600"
SERIAL_PARITY: N
SERIAL_STOPBITS: "1"
XJP60D_POINTS: 106:3,106:4
LE01MP_UNIT_IDS: 200,201,202,203
```

## Cutover

```bash
docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  pull device-agent

docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  up -d --force-recreate device-agent
```

Wait for at least three polling cycles:

```bash
sleep 25
```

## Acceptance checks

Health:

```bash
curl -fsS http://127.0.0.1:8081/health \
  | python3 -m json.tool
```

Required state:

```text
status: ok
device_mode: modbus
configured_points: [106-03, 106-04]
configured_devices: [LE01MP-200, LE01MP-201, LE01MP-202, LE01MP-203]
mqtt_connected: true
queue_size: 0
last_error: null
```

Logs:

```bash
docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  logs --since=5m --no-color device-agent
```

The deployment is rejected when logs contain:

```text
XJP60D read failed
LE-01MP read failed
CRC mismatch
Modbus exception
permission denied
Device-agent cycle failed
```

Verify one full telemetry cycle:

```bash
MQTT_TOPIC="$(
  awk -F= '$1=="MQTT_TOPIC" {
    print substr($0, index($0, "=") + 1)
  }' .env
)"

MQTT_TOPIC="${MQTT_TOPIC:-nexolab/telemetry}"

docker compose -f compose.edge.yaml exec -T mqtt \
  mosquitto_sub \
    -h 127.0.0.1 \
    -t "$MQTT_TOPIC" \
    -C 34 \
    -W 30 \
  > /tmp/nexolab-production-first-cycle.jsonl

wc -l /tmp/nexolab-production-first-cycle.jsonl
```

The file must contain `34` JSON records. All records must have `quality=valid`; the two XJP60D records may retain `alarm=high` while remaining valid.

## Reboot persistence check

The services use `restart: unless-stopped`. After the initial acceptance checks, reboot the node during a controlled maintenance window:

```bash
sudo reboot
```

After reconnecting:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  ps

curl -fsS http://127.0.0.1:8081/health \
  | python3 -m json.tool
```

The Device Agent must return to `device_mode=modbus` with an empty queue and `last_error=null`.

## Rollback

Return to the base simulator configuration:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  -f compose.edge.yaml \
  up -d --force-recreate device-agent

sleep 10

curl -fsS http://127.0.0.1:8081/health \
  | python3 -m json.tool
```

Required rollback state:

```text
device_mode: simulator
configured_points: []
configured_devices: []
queue_size: 0
last_error: null
```

## Registry update after acceptance

Only after the initial cutover and reboot persistence checks pass should the registry change from:

```yaml
production_hardware_mode_enabled: false
```

to:

```yaml
production_hardware_mode_enabled: true
```
