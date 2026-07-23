# Combined Modbus soak validation

## Result

The combined XJP60D and LE-01MP soak gate passed on 2026-07-23.

The validated production scope is:

- XJP60D points `106-03` and `106-04`;
- LE-01MP units `200`, `201`, `202`, and `203`;
- 34 telemetry records per complete polling cycle;
- Modbus RTU `9600 8N1`;
- FC03 only;
- one register per request;
- MQTT QoS 1 with a persistent SQLite offline queue.

## Initial soak run

The initial run started at `2026-07-23T10:37:54+00:00`.

| Check                           | Result     |
| ------------------------------- | ---------- |
| Combined Modbus precheck        | passed     |
| Continuous hardware polling     | passed     |
| Samples before                  | 102        |
| Samples after                   | 5848       |
| Queue growth during MQTT outage | 34 records |
| MQTT reconnect                  | passed     |
| Offline queue drain             | passed     |
| Device Agent restart            | passed     |
| Rollback to simulator           | passed     |

The initial validator reported a failure because its log classifier counted the application-level message `Device-agent cycle failed` as a serial error. Investigation established that `flush_queue()` allowed an MQTT publish exception to escape when the broker disappeared between the connection-state check and the queued-message publish.

No CRC failure, Modbus exception, serial timeout, or permission error was established.

## MQTT recovery fix

PR #30 hardened `flush_queue()` so an interrupted MQTT publish:

- leaves the queued record intact;
- returns control to the regular retry loop;
- logs `MQTT queue flush deferred`;
- does not produce an application-cycle crash;
- retries after MQTT reconnect.

The change does not alter Modbus polling behavior.

## Recovery retest

The focused recovery retest started at `2026-07-23T11:32:17+00:00`.

| Check                             | Result     |
| --------------------------------- | ---------- |
| Healthy combined-mode precheck    | passed     |
| Queue growth during MQTT outage   | passed     |
| MQTT recovery                     | passed     |
| Continuous polling after recovery | passed     |
| Serial or Modbus error lines      | 0          |
| Device Agent cycle failures       | 0          |
| Expected MQTT diagnostics present | yes        |
| Rollback to simulator             | passed     |
| Samples before                    | 136        |
| Samples after                     | 612        |
| Outage queue size                 | 34 records |

The final retest result was `PASSED`.

## Deployment decision

The shared RS-485 profile is approved for a controlled persistent deployment using:

```text
compose.edge.yaml + compose.hardware.yaml
HARDWARE_DEVICE_MODE=modbus
XJP60D_POINTS=106:3,106:4
LE01MP_UNIT_IDS=200,201,202,203
```

The repository approval does not itself switch the Raspberry Pi into hardware mode. The registry keeps `production_hardware_mode_enabled: false` until the controlled cutover is completed and verified on the node.

## Remaining constraints

- Do not run a scanner, profiler, or another Modbus master while the Device Agent owns the bus.
- Do not use Modbus write functions.
- Keep the unknown Unit ID `1` quarantined.
- Keep LE-01MP register `7` excluded until its engineering scale and rollover behavior are validated.
- Use the stable `/dev/serial/by-id/...` path rather than `/dev/ttyUSB0`.
