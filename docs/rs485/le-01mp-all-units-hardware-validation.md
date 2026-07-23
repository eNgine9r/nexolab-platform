# LE-01MP all-unit hardware validation

## Result

The read-only Device Agent hardware smoke test passed for all four F&F LE-01MP meters on `rs485-main-01`.

Validated Modbus unit IDs:

- `200`;
- `201`;
- `202`;
- `203`.

The tests used Modbus RTU `9600 8N1`, FC03, one register per request, MQTT QoS 1, and the explicit hardware Compose override. No communication errors were observed, the offline queue remained empty, and both test sessions rolled back cleanly to `DEVICE_MODE=simulator`.

## Unit 201 loaded-state observation

Captured at `2026-07-23T09:27:52.785640+00:00`:

- voltage: raw `2273`, published `227.3 V`;
- current: raw `5`, published `0.5 A`;
- frequency: raw `500`, published `50.0 Hz`;
- active power: raw `123`, published `123 W`;
- reactive power: raw `17`, published `17 var`;
- apparent power: raw `131`, published `131 VA`;
- power factor: raw `1000`, published `1.000`;
- internal temperature: raw `35`, published `35 °C`.

## Units 200, 202, and 203 idle-state observation

Captured at `2026-07-23T09:56:28.889977+00:00`.

### Unit 200

- voltage: raw `2249`, published `224.9 V`;
- current: raw `0`, published `0.0 A`;
- frequency: raw `500`, published `50.0 Hz`;
- active power: raw `0`, published `0 W`;
- reactive power: raw `0`, published `0 var`;
- apparent power: raw `0`, published `0 VA`;
- power factor: raw `0`, published `0.000`;
- internal temperature: raw `33`, published `33 °C`.

### Unit 202

- voltage: raw `2264`, published `226.4 V`;
- current: raw `0`, published `0.0 A`;
- frequency: raw `500`, published `50.0 Hz`;
- active power: raw `0`, published `0 W`;
- reactive power: raw `0`, published `0 var`;
- apparent power: raw `0`, published `0 VA`;
- power factor: raw `0`, published `0.000`;
- internal temperature: raw `34`, published `34 °C`.

### Unit 203

- voltage: raw `2273`, published `227.3 V`;
- current: raw `0`, published `0.0 A`;
- frequency: raw `500`, published `50.0 Hz`;
- active power: raw `0`, published `0 W`;
- reactive power: raw `0`, published `0 var`;
- apparent power: raw `0`, published `0 VA`;
- power factor: raw `1000`, published `1.000`;
- internal temperature: raw `36`, published `36 °C`.

## Interpretation limits

Each metric is read with a separate FC03 request. The common Device Agent batch timestamp does not make the electrical values an atomic snapshot.

Zero current and zero power are valid for unloaded meters. Power factor at zero load is device-defined: units `200` and `202` returned `0.000`, while unit `203` returned `1.000`. The power-factor value must therefore not be used by itself as a load-validity signal.

The cumulative-energy candidate at register `7` remains excluded because its engineering scale, rollover behavior, and final unit are not sufficiently validated.

## Next validation gate

Run combined read-only polling with:

- XJP60D points `106-03` and `106-04`;
- LE-01MP units `200`, `201`, `202`, and `203`;
- `DEVICE_MODE=modbus` through the explicit hardware Compose override.

Combined mode must pass without timeouts, CRC errors, Modbus exceptions, queue growth, or loss of either driver family before production hardware mode is considered for continuous operation.
