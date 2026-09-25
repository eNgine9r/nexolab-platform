# Eastron SDM120M dedicated RS-485 topology

Issue #1104 records the new read-only energy meter connection.

## Verified physical identity

- meter: Eastron SDM120M
- Modbus Unit ID: 1
- serial: 9600 8N1
- stable adapter: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q34QC-if00-port0`
- current Device Agent inventory identity: `commissioning-22bdefc8766cac4f`
- observed ttyUSB minor during discovery: `/dev/ttyUSB3` (non-authoritative)
- production polling before #1104 cutover: disabled

Only the stable `/dev/serial/by-id/...` identity is permitted for production configuration. The ttyUSB minor is evidence only and must never be persisted as the production binding.

## Intended production bus

The future cutover should add a dedicated logical bus, for example `rs485-sdm120`, to `RS485_BUS_CONFIG_JSON` with:

- serial device `/host/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q34QC-if00-port0`
- Unit IDs `[1]`
- 9600 baud
- parity `N`
- one stop bit
- existing bounded timeout/retry policy

The same cutover must set `SDM120_UNIT_IDS=1` and `SDM120_BUS_ID=rs485-sdm120`. Repository defaults intentionally keep both values empty so merging #1104 cannot start polling hardware.

## Existing production buses

The currently deployed runtime remains unchanged during #1104 implementation:

- `rs485-main`: CP2104 F090, existing XJP60D and LE-01MP units
- `rs485-embraco`: CP2104 F246, Embraco Unit 2

No existing bus is automatically probed, reassigned, recreated, or reconfigured by this Work Package.

## Safety

All SDM120 acquisition is read-only FC04 measurement polling. Discovery/service evidence may use bounded FC03 reads. Modbus writes and hardware configuration writes are forbidden. Production activation requires a separate exact cutover plan and explicit Product Owner approval.

Unit IDs are scoped to a physical bus. If another RS-485 segment also uses Unit `1`, the explicit `SDM120_BUS_ID` prevents ambiguous enrollment and leaves the other bus identity unchanged.
