# Waveshare Modbus RTU Analog Input 8CH (B) V3 — read-only discovery

- Status: protocol/transport hardware-discovered; humidity engineering signal not yet accepted
- Issue: #1125
- Production polling: driver implemented; production activation remains separately gated
- Physical module marking: `Waveshare Modbus RTU Analog Input 8CH (B) V3`

## Safety boundary

This discovery uses Modbus FC03 and FC04 only. No FC05/FC06/FC15/FC16 request, device configuration change, analog-range change, address change, baud/parity change, calibration change, or hardware output write is permitted.

The module is an acquisition device. Humidity, pressure, mass-flow and other engineering semantics belong to separately configured NEXOLAB Instruments/Signals and must not be hardcoded into the acquisition driver.

## Vendor read-only contract

Waveshare documents the following Development Protocol V2 read surface for this family:

- input registers `0x0000..0x0007`, FC04: channels 1–8 raw input values;
- holding registers `0x1000..0x1007`, FC03: per-channel input mode;
- holding register `0x2000`, FC03: UART parameter;
- holding register `0x4000`, FC03: device address;
- holding register `0x8000`, FC03: software version.

For the `(B)` hardware variant the mode table is:

- `0`: 0–10 V, returned in mV;
- `1`: 2–10 V, returned in mV;
- `2`: 0–20 mA, returned in µA;
- `3`: 4–20 mA, returned in µA;
- `4`: direct 12-bit ADC code.
  Vendor documentation also states that the `(B)` variant defaults to voltage input and that the per-channel internal jumper must match voltage/current operation. A software range value alone is not sufficient evidence of correct current measurement.

Vendor references:

- `https://www.waveshare.com/wiki/Modbus_RTU_Analog_Input_8CH_%28B%29`
- `https://www.waveshare.com/modbus-rtu-analog-input-8ch.htm`

## Real hardware evidence — 2026-09-23

The installed module responds on the otherwise unused FTDI adapter:

`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q2QYX-if00-port0`

Confirmed transport:

- Modbus address: `1`;
- baud rate: `9600`;
- data/parity/stop: `8N1`;
- UART parameter register: `0x0001`;
- software-version register: `210` → `V2.10`;
- CRC validation: PASS.

A second free FTDI adapter, `A10Q2SI7`, did not respond to the same bounded Waveshare address/version reads and is not classified as this device path.

Read-only address discovery returned `0x0001` from register `0x4000`; no address-setting command was sent.

## Current analog state

FC03 `0x1000..0x1007` returned:

`0, 0, 0, 0, 0, 0, 0, 0`

Therefore all eight channels are currently configured as mode `0` (0–10 V on the `(B)` variant).

Three repeated FC04 reads of `0x0000..0x0007` returned:

`0, 0, 0, 0, 0, 0, 0, 0`

for every pass.

The physically wired humidity transmitter therefore cannot yet be identified from live channel data. Zero values are not accepted as valid `%RH`, and NEXOLAB must not infer the sensor channel or range from the photograph alone.

If the installed humidity probe is the planned 4–20 mA variant, two separate conditions must be confirmed before hardware acceptance:

1. the corresponding physical channel jumper is in current-input position;
2. the corresponding channel mode is `3` (4–20 mA).

Changing either condition is a hardware/configuration action and is outside this read-only Work Package.

## NEXOLAB integration boundary

The merged read-only Device Agent driver exposes all eight acquisition channels as canonical `analog.input` telemetry and preserves the read mode plus raw value. Issue #1136 adds the disabled-by-default LOCAL_LAN deployment contract for a dedicated `rs485-waveshare` bus. Instrument/Signal bindings and `analog-scaling/v1` remain authoritative for engineering conversion such as `%RH`, bar or mass-flow units.

Production activation remains separate. Before the humidity channel may be represented as `%RH`, the physical channel, current-input jumper, read-back mode `3`, live current and exact transmitter engineering range must be confirmed.
