# Dixell XJP60D v1.6 library analysis

This procedure replaces broad register sweeps with analysis of the official Copeland XWEB library for the exact device version.

## Confirmed scope

- model: Dixell XJP60D;
- library/profile version: `1.6`;
- official library identifier: `XJP60D_000E00100001`;
- Modbus profile observed on the current bus: `9600 8N1`, FC03;
- climate chamber 2: physical controllers `K101-K114`, observed online IDs `101-114`;
- climate chamber 1: physical controllers `K115-K138`, observed online IDs `126-138`;
- `115-125` remain communication-unreachable on the current connection;
- connector `503` in chamber 2 maps to controller `K106`, paired channels `3/4`;
- connector `200` in chamber 1 maps to controller `K115`, channel `4`.

Do not interpret panel connector numbers as Modbus unit IDs.

## Download the official package

Run from the repository root on the Raspberry Pi:

```bash
mkdir -p runtime/vendor/dixell/xjp60d-v1.6

curl --fail --location --show-error \
  "https://webapps.copeland.com/Dixell/Content/Libraries/Xweb_EVO_Pub/LIBPackage-LIB20250704-XJP60D_000E00100001-json.zip" \
  --output runtime/vendor/dixell/xjp60d-v1.6/library.zip

sha256sum runtime/vendor/dixell/xjp60d-v1.6/library.zip \
  | tee runtime/vendor/dixell/xjp60d-v1.6/library.sha256
```

The vendor ZIP is runtime evidence. Do not commit it unless its redistribution terms have been reviewed.

## Analyze the package

```bash
python tools/rs485_discovery/analyze_dixell_library.py \
  --input runtime/vendor/dixell/xjp60d-v1.6/library.zip \
  --model XJP60D \
  --version 1.6 \
  --output runtime/vendor/dixell/xjp60d-v1.6/library-analysis.json
```

The analyzer:

- never contacts hardware and never executes vendor code;
- rejects unsafe ZIP paths;
- recursively opens nested ZIP payloads;
- detects `.json`, `.JSON`, `.jsn` and JSON-like files without relying only on a case-sensitive suffix;
- parses XML payloads when a vendor package uses XML instead of JSON;
- records the package SHA-256;
- finds probable register definitions;
- matches semantic keywords in both field names and values;
- scores temperature, probe, channel, input, sensor and alarm candidates;
- inventories package members and records normalized schema keys;
- produces JSON and CSV outputs.

Outputs:

```text
runtime/vendor/dixell/xjp60d-v1.6/library-analysis.json
runtime/vendor/dixell/xjp60d-v1.6/library-analysis.csv
```

## When the first report contains zero candidates

A zero-candidate result does not prove that the library has no register map. Older analyzer versions could miss nested archives, uppercase `.JSON` files or vendor-specific schemas.

Update the repository and rerun:

```bash
git switch main
git pull --ff-only

python tools/rs485_discovery/analyze_dixell_library.py \
  --input runtime/vendor/dixell/xjp60d-v1.6/library.zip \
  --model XJP60D \
  --version 1.6 \
  --output runtime/vendor/dixell/xjp60d-v1.6/library-analysis-v2.json
```

Inspect the package diagnostics:

```bash
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(
    Path("runtime/vendor/dixell/xjp60d-v1.6/library-analysis-v2.json").read_text()
)

print("statistics:", report["statistics"])
print("\ndocuments:")
for item in report["diagnostics"]["documents"]:
    print(item)

print("\ninventory:")
for item in report["diagnostics"]["inventory"][:100]:
    print(item)

print("\nnormalized keys:")
for item in report["diagnostics"]["normalized_key_counts"][:100]:
    print(item)

print("\nunknown address-like fields:")
for item in report["diagnostics"]["unknown_address_like_fields"][:100]:
    print(item)
PY
```

This distinguishes four cases:

1. `document_count = 0`: the useful payload is in an unsupported or opaque file format;
2. documents found but parse errors exist: encoding or malformed payload problem;
3. documents parsed but no candidates: vendor field names need additional aliases;
4. candidates found: proceed to a narrow read-only hardware correlation.

## Show the strongest candidates

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("runtime/vendor/dixell/xjp60d-v1.6/library-analysis-v2.json")
report = json.loads(path.read_text())

print("statistics:", report["statistics"])
for item in report["candidates"][:40]:
    print(
        f'score={item["score"]:2d} '
        f'address={str(item["address"]):>6} '
        f'fc={str(item["function"]):>4} '
        f'name={item["name"]!r} '
        f'scale={item["scale"]!r} '
        f'unit={item["unit"]!r} '
        f'keywords={item["matched_keywords"]} '
        f'file={item["source_file"]} '
        f'path={item["json_path"]}'
    )
PY
```

## Hardware validation after library analysis

Do not use placeholder addresses such as `A,B,C,D,E,F`. Only numeric addresses extracted from the official package may be passed to `profile_registers.py`.

Once the candidate addresses for the six probes are known, validate only the reachable active controller first:

```bash
SERIAL_DEVICE="/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0"

python tools/rs485_discovery/profile_registers.py \
  --port "$SERIAL_DEVICE" \
  --unit-ids "106" \
  --addresses "<NUMERIC_CANDIDATE_ADDRESSES>" \
  --function 3 \
  --baudrate 9600 \
  --parity N \
  --stopbits 1 \
  --samples 24 \
  --sample-interval 5 \
  --timeout 0.25 \
  --retries 1 \
  --progress \
  --output runtime/discovery/xjp60d-v1.6/k106-library-correlation.json
```

Correlate the resulting values with paired channels `106-03` and `106-04`. Keep `115-04` in the registry as physically present but communication-unreachable until Unit ID `115` becomes accessible.

All hardware validation remains read-only. Do not switch the Device Agent from `simulator` to `hardware` until the register meanings, data types, scales and missing-sensor representation are confirmed.
