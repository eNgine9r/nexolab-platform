# LE-01MP Unit 201 hardware validation

## Result

The read-only Device Agent hardware smoke test for F&F LE-01MP Modbus unit `201` passed on 2026-07-23.

- bus: `rs485-main-01`;
- serial: Modbus RTU `9600 8N1`;
- function: FC03;
- policy: one register per request;
- active Device Agent mode: `le01mp`;
- configured devices: `LE01MP-201` only;
- MQTT QoS: 1;
- communication errors: none observed;
- local queue after test: empty;
- rollback to `simulator`: passed.

## Published telemetry

All eight production metrics were published with `quality=valid`, `source=f-and-f-le-01mp`, and `equipment_id=LE01MP-201`.

| Metric                      | Register |  Raw | Published value |
| --------------------------- | -------: | ---: | --------------: |
| `electrical.voltage`        |        0 | 2273 |         227.3 V |
| `electrical.current`        |        1 |    5 |           0.5 A |
| `electrical.frequency`      |        2 |  500 |         50.0 Hz |
| `electrical.power.active`   |        3 |  123 |           123 W |
| `electrical.power.reactive` |        4 |   17 |          17 var |
| `electrical.power.apparent` |        5 |  131 |          131 VA |
| `electrical.power_factor`   |        6 | 1000 |           1.000 |
| `temperature.internal`      |       37 |   35 |           35 °C |

All records in the batch used the timestamp `2026-07-23T09:27:52.785640+00:00`.

## Interpretation limits

The Device Agent assigns one batch timestamp, but the Modbus values are read sequentially as separate FC03 requests. Voltage, current, power, apparent power, reactive power, and power factor must therefore not be treated as an atomic electrical snapshot. Small cross-metric inconsistencies can reflect load variation during the polling sequence or device-specific calculation windows.

The cumulative energy candidate at register `7` remains excluded. Its engineering scale, rollover behavior, and final unit are not sufficiently validated.

## Safety status

No write function is implemented. Production hardware mode remains opt-in through `compose.hardware.yaml`; the base Edge Compose configuration remains `DEVICE_MODE=simulator`.

## Next validation gate

Run the same read-only eight-register test for units `200`, `202`, and `203`. Only after all four meters pass should the energy-meter profile be marked as a complete hardware smoke-test pass and considered for combined `modbus` polling with XJP60D.
