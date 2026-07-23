# Production Modbus cutover validation

## Result

The controlled production Modbus cutover and reboot persistence check passed on `nexolab-edge-01` on 2026-07-23.

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

## Operator rollback

After the successful reboot verification, the operator intentionally ran the base Compose stack without `compose.hardware.yaml`:

```bash
docker compose \
  -f compose.edge.yaml \
  up -d --force-recreate device-agent
```

This returned the node to the safe base `simulator` configuration. Therefore:

- production hardware mode is technically validated and approved;
- reboot persistence is validated;
- the node's current mode is `simulator`;
- `production_hardware_mode_enabled` remains `false` until the operator explicitly reactivates the hardware override and leaves it running.

## Re-activation command

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  up -d --force-recreate device-agent
```

After re-activation, verify `/health` returns `device_mode=modbus`, `queue_size=0`, and `last_error=null` before marking production hardware mode as enabled in the registry.
