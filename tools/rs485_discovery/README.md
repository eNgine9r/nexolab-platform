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
SERIAL_DEVICE="/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0"
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

## Strict candidate verification

Use the strict verifier before registering scanner candidates. It requires exact response lengths and stores raw evidence:

```bash
python tools/rs485_discovery/verify_candidates.py \
  --port "$SERIAL_DEVICE" \
  --unit-ids "101-114,126-138,200-203" \
  --baudrate 9600 \
  --parities N \
  --stopbits 1 \
  --timeout 0.30
```

## One-register-at-a-time profiling

`profile_registers.py` reads exactly one register in each request. It repeats sampling, records unsigned and signed 16-bit values, marks dynamic registers and writes both JSON and CSV.

Start with a narrow register range. Do not profile all 65,536 addresses.

Energy meters:

```bash
python tools/rs485_discovery/profile_registers.py \
  --port "$SERIAL_DEVICE" \
  --unit-ids "200-203" \
  --addresses "0-63" \
  --function 3 \
  --samples 5 \
  --sample-interval 3 \
  --progress \
  --output runtime/discovery/energy-meters-profile.json
```

Dixell climate chamber 2:

```bash
python tools/rs485_discovery/profile_registers.py \
  --port "$SERIAL_DEVICE" \
  --unit-ids "101-114" \
  --addresses "0-63" \
  --function 3 \
  --samples 3 \
  --sample-interval 3 \
  --progress \
  --output runtime/discovery/dixell-chamber-02-profile.json
```

Dixell climate chamber 1:

```bash
python tools/rs485_discovery/profile_registers.py \
  --port "$SERIAL_DEVICE" \
  --unit-ids "126-138" \
  --addresses "0-63" \
  --function 3 \
  --samples 3 \
  --sample-interval 3 \
  --progress \
  --output runtime/discovery/dixell-chamber-01-profile.json
```

Show only dynamic registers:

```bash
python3 - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("runtime/discovery").glob("*-profile.json")):
    report = json.loads(path.read_text())
    print(f"\n{path.name}")
    for item in report["dynamic_registers"]:
        print(
            f'  unit={item["unit_id"]:3d} '
            f'address={item["address"]:5d} '
            f'values={item["values_u16"]} '
            f'signed={item["values_s16"]}'
        )
PY
```

A changing register is only a candidate for temperature, voltage, current or another live value. Its meaning and scale must be confirmed against the device display or an official register map.

## Result states

- `discovered`: identity confidence is at least 90%;
- `pending_confirmation`: an endpoint exists but the exact model is not proven;
- `warnings`: bytes were received without a valid frame, commonly caused by duplicate addresses, reversed/noisy wiring, local echo or wrong serial settings.

The confirmed bus topology is stored in `config/edge/rs485-device-registry.yaml`.

Do not switch the production Device Agent from `simulator` to `hardware` until the discovered endpoints and register profiles are reviewed.
