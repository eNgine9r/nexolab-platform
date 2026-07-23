# Combined Modbus hardware validation

## Result

The read-only Device Agent combined-mode smoke test passed on 2026-07-23.

The test used one Modbus RTU bus at `9600 8N1` and polled both supported device families in one cycle:

- XJP60D points `106-03` and `106-04`;
- LE-01MP units `200`, `201`, `202`, and `203`;
- FC03 only;
- one register per request;
- MQTT QoS 1;
- no Modbus write functions.

The complete batch timestamp was `2026-07-23T10:14:01.033804+00:00`.

## Validation summary

| Family | Expected records | Valid records | Result |
| --- | ---: | ---: | --- |
| Dixell XJP60D | 2 | 2 | passed |
| F&F LE-01MP | 32 | 32 | passed |
| Total | 34 | 34 | passed |

Operational checks also passed:

- Device Agent mode: `modbus`;
- MQTT connected: yes;
- offline queue: empty;
- Device Agent errors: none observed;
- rollback to `simulator`: passed.

## XJP60D values

| Point | Value | Quality | Alarm |
| --- | ---: | --- | --- |
| `106-03` | 26.0 °C | `valid` | `high` |
| `106-04` | 25.6 °C | `valid` | `high` |

The `high` state is a controller alarm state, not a communication failure. Both temperature values remain valid.

## LE-01MP values

| Unit | Voltage | Current | Frequency | Active power | Reactive power | Apparent power | Power factor | Internal temperature |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `200` | 226.4 V | 0.0 A | 50.0 Hz | 0 W | 0 var | 0 VA | 0.000 | 33 °C |
| `201` | 226.9 V | 3.3 A | 50.0 Hz | 716 W | 184 var | 750 VA | 0.956 | 34 °C |
| `202` | 227.6 V | 0.0 A | 50.0 Hz | 0 W | 0 var | 0 VA | 0.000 | 34 °C |
| `203` | 228.7 V | 0.0 A | 50.0 Hz | 0 W | 0 var | 0 VA | 0.000 | 36 °C |

The meter registers are read sequentially as separate FC03 requests. Cross-metric arithmetic must therefore not be treated as an atomic electrical snapshot.

## Safety status

The base Edge Compose configuration remains `DEVICE_MODE=simulator`. Hardware mode still requires the explicit `compose.hardware.yaml` override.

The cumulative-energy candidate at register `7` remains excluded because its scale, rollover behavior, and final engineering unit are not yet sufficiently validated.

## Next validation gate

Run a controlled combined-mode soak test before enabling persistent hardware operation.

The soak test must verify:

- continuous polling of all 34 records per cycle;
- no CRC errors, timeouts, or Modbus exceptions;
- no growth of the offline queue while MQTT is available;
- recovery after a controlled MQTT interruption;
- clean restart of the Device Agent;
- clean rollback to `simulator`.
