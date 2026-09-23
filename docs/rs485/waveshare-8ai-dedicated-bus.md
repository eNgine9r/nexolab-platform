# Waveshare 8AI dedicated LOCAL_LAN bus

Issue #1136 prepares the production-safe software path for the already identified Waveshare Modbus RTU Analog Input 8CH (B) V3. It does **not** activate production polling or change hardware configuration.

## Verified identity

- logical candidate bus: `rs485-waveshare`;
- stable host adapter: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q2QYX-if00-port0`;
- container path: `/host/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q2QYX-if00-port0`;
- Modbus Unit: `1`;
- serial: `9600 8N1`;
- driver profile: `waveshare-modbus-rtu-analog-input-8ch-b-v3-readonly-v1`;
- read functions only: FC03 mode + FC04 input.

SDM120 also uses Unit `1`, but on `rs485-sdm120`. Unit identity is bus-scoped, so the two devices are intentionally valid together when each family is pinned to its own explicit bus.

## Candidate runtime contract

Repository defaults keep Waveshare polling disabled. A reviewed production candidate must explicitly add the bus to `RS485_BUS_CONFIG_JSON` and set both:

```text
WAVESHARE_8AI_UNIT_IDS=1
WAVESHARE_8AI_BUS_ID=rs485-waveshare
```

The dedicated bus object is:

```json
{"bus_id":"rs485-waveshare","serial_device":"/host/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q2QYX-if00-port0","unit_ids":[1],"baudrate":9600,"parity":"N","stopbits":1,"timeout_seconds":0.3,"retries":1}
```

This object must be composed with the existing production bus array; it must never replace another bus or reuse its physical serial path.

## Telemetry contract

When explicitly enabled, Device Agent registers eight targets:

```text
WAVESHARE-8AI-1 / 1-ai-1..1-ai-8 / analog.input
```

The raw physical unit is determined from the read-only mode register for each channel: modes 0/1 emit `mV`, modes 2/3 emit `uA`, mode 4 emits `count`. Device Agent does not invent humidity, pressure, flow, or another engineering semantic.

The Live telemetry explorer can therefore show the raw channel immediately after an approved runtime activation and successful hardware read. Engineering `%RH` remains controlled by the Instrument/Signal plus `analog-scaling/v1` contract. In mode `3` the device reports microamps, so the evidence-backed electrical scaling domain is `4000..20000 uA`; only the humidity engineering endpoints remain unknown until the exact transmitter range is confirmed.

## Humidity acceptance gate

The connected humidity channel is intentionally unresolved before the physical work. Hardware acceptance requires all of the following real evidence:

1. the Product Owner moves the correct channel jumper to current input;
2. a read-only FC03 check reports mode `3` for that channel;
3. FC04 returns a plausible non-zero 4–20 mA current value;
4. the exact transmitter engineering range is confirmed from its label/datasheet;
5. NEXOLAB binds that exact `1-ai-N` source to the humidity Instrument/Signal and records the explicit `analog-scaling/v1` profile;
6. a physical comparison establishes whether the profile can move from `hardware_unverified` to `hardware_verified`.

Until steps 2–5 are complete, NEXOLAB may expose raw analog telemetry but must not label it `%RH`.

## Safety boundary

No Modbus write, channel-mode write, hardware write, production restart, production container replacement, or site cutover is authorized by this document. Runtime activation remains a separate Product Owner gate.
