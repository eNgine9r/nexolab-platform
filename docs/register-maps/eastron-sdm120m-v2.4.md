# Eastron SDM120M read-only register map

- Status: software profile backed by vendor protocol V2.4 and real read-only hardware evidence
- Issue: #1104
- Production polling: not activated by this Work Package

## Safety boundary

NEXOLAB reads SDM120M measurement data with Modbus RTU FC04 only. The implementation contains no meter-configuration write path. It does not change address, baud rate, parity, pulse output, display settings, counters, or any other hardware configuration.

## Confirmed transport

The installed meter responded on the dedicated FTDI adapter:

`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q34QC-if00-port0`

The verified serial contract is Unit `1`, `9600`, `8N1`. The adapter was visible to Device Agent commissioning inventory as `commissioning-22bdefc8766cac4f`. Continuous production polling remains a separate cutover gate; the cutover must bind `SDM120_BUS_ID=rs485-sdm120` explicitly.

## Measurement encoding

The Eastron SDM120 Modbus Protocol Implementation V2.4 defines measurement parameters as FC04 input registers. Every value used by NEXOLAB is a 32-bit IEEE-754 float spanning two adjacent 16-bit Modbus registers, most-significant word first.

NEXOLAB uses this bounded subset:

- `0x0000` voltage → `electrical.voltage` / V
- `0x0006` current → `electrical.current` / A
- `0x000C` active power → `electrical.power.active` / W
- `0x0012` apparent power → `electrical.power.apparent` / VA
- `0x0018` reactive power → `electrical.power.reactive` / var
- `0x001E` power factor → `electrical.power_factor` / ratio
- `0x0046` frequency → `electrical.frequency` / Hz
- `0x0048` import active energy → `electrical.energy.active` / kWh

`temperature.internal` is not part of the accepted SDM120M profile and must be shown as unsupported rather than fabricated or treated as a communication failure.

## Real hardware evidence — 2026-09-22

Read-only FC04 evidence recorded:

- voltage: words `17251, 51411` → `227.7844696044922 V`
- current: words `0, 0` → `0 A`
- active power: words `0, 0` → `0 W`
- frequency: words `16968, 9607` → `50.03664779663086 Hz`
- import active energy: words `15647, 48759` → `0.039000000804662704 kWh`
- total active energy at `0x0156`: same `0.039000000804662704 kWh`

The zero current/power values reflect the unloaded state during the bounded probe; they are not evidence of a fault. FC03 service reads independently confirmed meter ID `1`, baud code `2` (`9600`) and parity/stop code `0` (`8N1`). No write command was sent.

Evidence files on the controlled Raspberry Pi:

- `runtime/evidence/sdm120m-discovery-20260922.json`
- `runtime/evidence/sdm120m-fc04-profile-20260922.json`

## Cumulative energy semantics

Operator consumption uses the native cumulative **Import Active Energy** value at `0x0048`. Interval consumption is the difference between two valid boundary samples. The cumulative meter value remains immutable telemetry evidence and is not replaced by a host-integrated power estimate.

A decrease in the cumulative value remains a discontinuity/reset/rollover condition; NEXOLAB must not silently turn it into positive consumption.

## Discovery regression

The first generic scan incorrectly classified the endpoint as a Dixell XJP-family candidate because FC03 register 256 returned six zero words. The scanner now requires non-zero plausible XJP fingerprint data and independently recognizes a plausible SDM120 family candidate from FC04 voltage/frequency. This removes the recorded false positive without broadening any write capability.
