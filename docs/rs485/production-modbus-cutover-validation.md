# Production Modbus cutover validation

## Result

The controlled production Modbus cutover, reboot persistence check, and final hardware activation passed on `nexolab-edge-01` on 2026-07-23.

The validated runtime state after reboot was:

```text
status: ok
device_mode: modbus
configured_points: [106-03, 106-04]
configured_devices: [LE01MP-200, LE01MP-201, LE01MP-202, LE01MP-203]
mqtt_connected: true
queue_size: 0
samples_total: 136
last_error: null
```

## Runtime evidence

- Device Agent container: healthy;
- MQTT container: healthy;
- XJP60D points: `106-03`, `106-04`;
- LE-01MP units: `200`, `201`, `202`, `203`;
- restart after node reboot: passed;
- MQTT connection after reboot: passed;
- offline queue after reboot: empty;
- Device Agent error state: none.

The Device Agent started at `2026-07-23T11:57:49.703696+00:00`. The last observed sample timestamp was `2026-07-23T11:58:17.768837+00:00`, and the last publish timestamp was `2026-07-23T11:58:22.669245+00:00`.

## Controlled rollback verification

After the successful reboot verification, the operator intentionally ran the base Compose stack without `compose.hardware.yaml`:

```bash
docker compose \
  -f compose.edge.yaml \
  up -d --force-recreate device-agent
```

This confirmed that rollback to the safe base `simulator` configuration remained available as a single command.

## Final production activation

The operator then re-applied the validated hardware override and left it running:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  up -d --force-recreate device-agent
```

The final observed runtime state was:

```text
status: ok
device_mode: modbus
configured_points: [106-03, 106-04]
configured_devices: [LE01MP-200, LE01MP-201, LE01MP-202, LE01MP-203]
mqtt_connected: true
queue_size: 0
samples_total: 68
last_error: null
```

The Device Agent started at `2026-07-23T12:05:09.277274+00:00`. The last observed sample timestamp was `2026-07-23T12:05:20.442225+00:00`, and the last publish timestamp was `2026-07-23T12:05:26.879040+00:00`.

The error-log acceptance filter returned:

```text
Production Modbus logs: clean
```

No XJP60D read failure, LE-01MP read failure, CRC mismatch, Modbus exception, permission error, or Device Agent cycle failure was observed.

## Deployment decision

The production hardware mode is enabled.

The active profile remains:

```text
compose.edge.yaml + compose.hardware.yaml
HARDWARE_DEVICE_MODE=modbus
XJP60D_POINTS=106:3,106:4
LE01MP_UNIT_IDS=200,201,202,203
```

The base `.env` still keeps `DEVICE_MODE=simulator`, preserving the tested one-command rollback path.
