# F&F LE-01MP read-only register map

- Status: production read semantics with explicit evidence boundaries
- Issue: #201

## Safety boundary

This profile is read-only. NEXOLAB uses Modbus RTU function `03` only for the fields below. It does not write meter configuration, reset counters, change addresses, or perform hardware control.

## Confirmed registers

- `voltage`: `electrical.voltage`, FC03, start `0`, count `1`, uint16, scale `0.1 V`, confirmed.
- `current`: `electrical.current`, FC03, start `1`, count `1`, uint16, scale `0.1 A`, confirmed.
- `frequency`: `electrical.frequency`, FC03, start `2`, count `1`, uint16, scale `0.1 Hz`, confirmed.
- `active_power`: `electrical.power.active`, FC03, start `3`, count `1`, uint16, scale `1 W`, confirmed.
- `reactive_power`: `electrical.power.reactive`, FC03, start `4`, count `1`, uint16, scale `1 var`, confirmed.
- `apparent_power`: `electrical.power.apparent`, FC03, start `5`, count `1`, uint16, scale `1 VA`, confirmed.
- `power_factor`: `electrical.power_factor`, FC03, start `6`, count `1`, uint16, scale `0.001`, ratio, confirmed.
- `active_energy`: `electrical.energy.active`, FC03, start `7`, count `2`, uint32 high word then low word, scale `0.01 kWh`, confirmed for normal operation on Units 200–203.
- `internal_temperature`: `temperature.internal`, FC03, start `37`, count `1`, int16, scale `1 degC`, confirmed.

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

- Unit 200 / W1: R7 `20`, R8 `63791`, raw32 `1374511`, decoded `13745.11 kWh`.
- Unit 201 / W2: R7 `38`, R8 `49806`, raw32 `2540174`, decoded `25401.74 kWh`.
- Unit 202 / W3: R7 `17`, R8 `15498`, raw32 `1129610`, decoded `11296.10 kWh`.
- Unit 203 / W4: R7 `21`, R8 `2364`, raw32 `1378620`, decoded `13786.20 kWh`.

The decoded values were correlated with the physical meter displays.

A second read approximately 9 minutes 50 seconds later showed normal cumulative behavior:

- Unit 200: `0 W`, delta `0.00 kWh`.
- Unit 201: `2520 W`, delta `+0.28 kWh`.
- Unit 202: `228 W`, delta `+0.04 kWh`.
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
