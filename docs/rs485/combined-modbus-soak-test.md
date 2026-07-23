# Combined Modbus soak test

## Purpose

Validate sustained read-only polling of the combined XJP60D and LE-01MP profile before persistent hardware operation is enabled.

## Scope

- XJP60D points: `106-03`, `106-04`;
- LE-01MP units: `200`, `201`, `202`, `203`;
- expected telemetry records per complete cycle: `34`;
- serial profile: Modbus RTU `9600 8N1`;
- function: FC03 only;
- request policy: one register per request;
- duration: 30 minutes;
- base Compose mode remains `simulator`;
- hardware mode requires `compose.hardware.yaml`.

## Pass criteria

The soak test passes only when all of the following are true:

1. The Device Agent remains healthy in `modbus` mode for 30 minutes.
2. `configured_points` contains `106-03` and `106-04`.
3. `configured_devices` contains all four LE-01MP units.
4. No CRC errors, Modbus exceptions, serial timeouts, or permission errors occur.
5. `last_error` is `null` before the MQTT interruption.
6. A controlled MQTT interruption causes telemetry to enter the offline queue.
7. The queue drains automatically after MQTT is restored.
8. MQTT publishing resumes without restarting the Device Agent.
9. A controlled Device Agent restart returns to a healthy `modbus` state.
10. Rollback to the base `simulator` configuration succeeds.

## Evidence to retain

Store the following files under `runtime/validation/combined-modbus-soak/`:

- `health-before.json`;
- `health-during-mqtt-outage.json`;
- `health-after-mqtt-recovery.json`;
- `health-after-agent-restart.json`;
- `health-after-rollback.json`;
- `device-agent.log`;
- `mqtt.log`;
- `summary.txt`.

## Safety constraints

- Do not run a scanner, profiler, or another Modbus master during the soak test.
- Do not change physical wiring while equipment is energized.
- Do not use any Modbus write function.
- Stop the test and roll back to `simulator` after repeated CRC failures, persistent timeouts, or unexpected bus contention.

## Log classification

MQTT interruption messages are transport-recovery diagnostics and must not be counted as RS-485 failures. Expected outage diagnostics include:

- `MQTT disconnected`;
- `MQTT publish failed; queueing event`;
- `MQTT queue flush deferred`;
- `MQTT unavailable; telemetry queued locally` in the health state.

Count only the following patterns as serial or Modbus failures:

```text
XJP60D read failed
LE-01MP read failed
CRC mismatch
Modbus exception
permission denied
```

`Device-agent cycle failed` is a separate application-level failure and must remain zero after the MQTT queue recovery fix. It is reported separately from the serial error count.
