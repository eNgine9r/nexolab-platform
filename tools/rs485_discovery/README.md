# NEXOLAB RS-485 discovery

Read-only utility for discovering Modbus RTU endpoints when the unit ID and serial settings are unknown.

The scanner:

- iterates through selected baud rate, parity, stop-bit and unit-ID combinations;
- uses only read functions `03`, `04` and `43/14`;
- accepts both normal Modbus responses and valid exception responses as proof that an endpoint exists;
- attempts standard Modbus Device Identification;
- collects a small read-only fingerprint for legacy devices;
- writes a JSON discovery report that can become the local device registry.

It never writes registers and never changes a device address or communication setting.

## Protocol limitation

Modbus RTU has no universal bus-discovery command. Exact naming is automatic only when a device implements function `43/14 Read Device Identification` or matches a verified fingerprint. Older devices can remain `Unknown Modbus RTU device` or a low-confidence candidate until their register map is confirmed.

Dixell XJP modules may expose several serial addresses for one physical module because separate sections can have separate addresses. Two physical devices with the same unit ID and the same serial settings will answer simultaneously and can produce invalid CRC frames; in that situation disconnect one device temporarily or change one address with the manufacturer's configuration method.

## Raspberry Pi setup

From the repository root:

```bash
sudo apt update
sudo apt install -y python3-venv

python3 -m venv .venv-rs485
. .venv-rs485/bin/activate
python -m pip install --upgrade pip
python -m pip install -r tools/rs485_discovery/requirements.txt
```

Confirm that no other process owns the adapter:

```bash
SERIAL_DEVICE="/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F246-if00-port0"
sudo fuser -v "$SERIAL_DEVICE" || true
```

The current Device Agent runs in simulator mode and does not use the serial port.

## First scan

The quick scan checks four common combinations across unit IDs `1..247`:

```bash
python tools/rs485_discovery/scan_rs485.py \
  --port "$SERIAL_DEVICE" \
  --quick \
  --deep \
  --progress
```

Quick profiles:

- 9600 8N1;
- 9600 8E1;
- 19200 8N1;
- 19200 8E1.

The report is written to:

```text
runtime/discovery/rs485-report.json
```

View it with:

```bash
python3 -m json.tool runtime/discovery/rs485-report.json
```

## Targeted scan

When a likely address range is known, reduce scan time:

```bash
python tools/rs485_discovery/scan_rs485.py \
  --port "$SERIAL_DEVICE" \
  --baud-rates 9600,19200 \
  --parities N,E \
  --stop-bits 1 \
  --unit-ids 1-32 \
  --deep \
  --progress
```

## Full scan

Use the full scan only if the quick scan finds nothing:

```bash
python tools/rs485_discovery/scan_rs485.py \
  --port "$SERIAL_DEVICE" \
  --baud-rates 9600,19200,38400,115200 \
  --parities N,E,O \
  --stop-bits 1,2 \
  --unit-ids 1-247 \
  --deep \
  --progress \
  --timeout 0.12
```

A full deep scan can take tens of minutes because every combination must be tested safely and sequentially.

## Result states

- `discovered`: identity confidence is at least 90%;
- `pending_confirmation`: an endpoint exists but the exact model is not proven;
- `warnings`: bytes were received without a valid frame, commonly caused by duplicate addresses, reversed/noisy wiring, local echo or wrong serial settings.

Do not switch the production Device Agent from `simulator` to `hardware` until the discovered endpoints and register profiles are reviewed.
