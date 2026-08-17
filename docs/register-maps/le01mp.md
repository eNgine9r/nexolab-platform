# F&F LE-01MP read-only register map

Status: production read semantics with explicit evidence boundaries  
Issue: #201

## Safety boundary

This profile is read-only. NEXOLAB uses Modbus RTU function `03` only for the fields below. It does not write meter configuration, reset counters, change addresses, or perform hardware control.

## Confirmed registers

| Key | Metric | FC | Start | Count | Encoding | Scale | Unit | Evidence state |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- |
| `voltage` | `electrical.voltage` | 03 | 0 | 1 | uint16 | 0.1 | V | confirmed |
| `current` | `electrical.current` | 03 | 1 | 1 | uint16 | 0.1 | A | confirmed |
| `frequency` | `electrical.frequency` | 03 | 2 | 1 | uint16 | 0.1 | Hz | confirmed |
| `active_power` | `electrical.power.active` | 03 | 3 | 1 | uint16 | 1 | W | confirmed |
| `reactive_power` | `electrical.power.reactive` | 03 | 4 | 1 | uint16 | 1 | var | confirmed |
| `apparent_power` | `electrical.power.apparent` | 03 | 5 | 1 | uint16 | 1 | VA | confirmed |
| `power_factor` | `electrical.power_factor` | 03 | 6 | 1 | uint16 | 0.001 | ratio | confirmed |
| `active_energy` | `electrical.energy.active` | 03 | 7 | 2 | uint32, high word then low word | 0.01 | kWh | confirmed for normal operation on Units 200–203 |
| `internal_temperature` | `temperature.internal` | 03 | 37 | 1 | int16 | 1 | degC | confirmed |

## Cumulative active energy

The cumulative energy value must be read atomically as one FC03 request starting at address `7` with `count=2`.

```text
high_word = R7
low_word = R8
raw32 = (high_word << 16) | low_word
energy_kWh = raw32 * 0.01
```

R7 and R8 must not be sampled as two independent physical requests because a low-word change between requests could create a torn cumulative value.

The emitted telemetry field is:

```text
metric = electrical.energy.active
unit = kWh
raw_value = raw32
value = raw32 * 0.01
```

`raw_value` is the immutable cumulative counter captured from the device. Derived interval consumption is a separate concept and must not overwrite or be confused with this cumulative metric.

## Accepted real-hardware frames — 2026-08-17

Read-only Raspberry Pi validation on installed Units 200–203 produced:

| Unit | R7 | R8 | raw32 | decoded kWh |
| ---: | ---: | ---: | ---: | ---: |
| 200 / W1 | 20 | 63791 | 1374511 | 13745.11 |
| 201 / W2 | 38 | 49806 | 2540174 | 25401.74 |
| 202 / W3 | 17 | 15498 | 1129610 | 11296.10 |
| 203 / W4 | 21 | 2364 | 1378620 | 13786.20 |

The decoded values were correlated with the physical meter displays.

A second read approximately 9 minutes 50 seconds later showed normal cumulative behavior:

- Unit 200: `0 W`, delta `0.00 kWh`;
- Unit 201: `2520 W`, delta `+0.28 kWh`;
- Unit 202: `228 W`, delta `+0.04 kWh`;
- Unit 203: `0 W`, delta `0.00 kWh`.

The Device Agent was restored to `healthy` after each bounded probe. No Modbus write or meter mutation occurred.

## Quality and discontinuity policy

A successful atomic read is emitted with normal valid quality. Existing acquisition handling maps transport/protocol failure to `communication_error` and does not substitute stale or demo data.

Until controlled restart/power-cycle and rollover evidence is completed:

- do not infer or fabricate a rollover threshold from the host integer representation;
- do not silently convert a decreasing cumulative value into positive interval consumption;
- a consumer computing deltas must treat any negative delta as a discontinuity/reset/rollover candidate rather than normal consumption;
- the cumulative raw sample itself remains preserved exactly as read.

## Remaining evidence boundary

Normal-operation address/count/type/word-order/scale/unit/display correlation is hardware-confirmed for Units 200–203. Full Issue #201 hardware acceptance still requires an approved restart/power-cycle observation and explicit rollover/reset/discontinuity classification. No unsafe action is authorized to accelerate that evidence.
