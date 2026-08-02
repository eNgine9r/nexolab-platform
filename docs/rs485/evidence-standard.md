# RS-485 register evidence standard

## Purpose

This standard prevents a register map from being promoted on plausibility, a single successful read, or an undocumented decoding assumption. Every decision remains traceable to immutable Modbus request/response frames, calculated CRC16, a physical reference, the profiler build and the register-profile version used at capture time.

The canonical schema is `schemas/rs485-register-evidence.schema.json`. The semantic validator is `scripts/validate-rs485-evidence.py`.

## Confidence levels

| Level        | Minimum evidence                                                                                                                                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `candidate`  | At least one CRC-valid passing sample whose decoded value is physically plausible. No physical correlation is claimed.                                                   |
| `correlated` | At least two passing samples under distinct controlled conditions. Each sample has a physical/display/control reference and an observed or confirmed correlation.        |
| `confirmed`  | At least two passing samples under distinct conditions. Every passing sample is matched to a device display or reference instrument and marked `correlation: confirmed`. |
| `portable`   | Confirmed evidence repeated at least twice on each of at least two physical device IDs.                                                                                  |
| `rejected`   | The candidate is explicitly disproved or unsupported. Raw samples remain archived and `rejection_reason` is mandatory.                                                   |

A single passing sample can never produce `confirmed`. A CRC-valid response proves frame integrity only; it does not prove register meaning, scale, sign, engineering unit or portability.

## Archive structure

Committed evidence is append-only and must use:

```text
evidence/rs485/YYYY/MM/DD/<node_id>/<evidence_id>.json
```

Example:

```text
evidence/rs485/2026/07/29/edge-rpi5-01/le01mp-201-voltage-register-0000.json
```

`created_at_utc` determines the date path. The filename must equal `<evidence_id>.json`.

Never edit, delete, overwrite, copy over or rename committed raw evidence. When a conclusion changes, commit a new evidence file with a new ID and updated decision. Rejected candidates remain in the archive with the reason they were rejected.

## Naming rules

- `evidence_id`: lowercase, stable and descriptive, for example `le01mp-201-voltage-register-0000`.
- `sample_id`: unique across the repository and tied to the physical condition, for example `le01mp-201-voltage-controlled-load-002`.
- Raw frames: uppercase compact hexadecimal, including the two Modbus CRC bytes; no spaces or `0x` prefix.
- `device_id`: physical device identity, not only the Modbus Unit ID.
- `node_id`: stable edge-node identity.
- `register_profile.profile_id`: versioned profile family; increment `version` whenever address, type, byte/word order, scale, offset or unit changes.
- `profiler.commit`: exact Git commit that produced the evidence.

## Required capture workflow

1. Record the physical device ID, edge node, adapter path and exact serial settings.
2. Record the profiler name, semantic version and exact commit.
3. Record the register-profile ID and version used for decoding.
4. Capture the complete request and response frames, including CRC bytes.
5. Record latency, unsigned value, signed value, decoded value, scale and offset.
6. Record a display, reference instrument or controlled-condition observation. Link the photo, test log or instrument reading in `physical_reference.source`.
7. Repeat under a meaningfully different condition before requesting `correlated` or `confirmed` status.
8. For `portable`, repeat confirmation on at least two physical devices, with at least two passing samples per device.
9. Keep failed and disproved samples. Use `sample_pass: false` or `decision.confidence: rejected` with a reason instead of removing evidence.
10. Validate the file before committing it to the archive.

## Manual capture checklist

- [ ] Device, node and adapter identities are exact.
- [ ] Baud rate, parity, stop bits and data bits match the live bus.
- [ ] Unit ID, function code, register address and quantity match the raw request.
- [ ] Request and response include CRC bytes.
- [ ] `crc_ok` matches calculated Modbus CRC16 for both frames.
- [ ] `frame_sha256` binds the exact request and response strings.
- [ ] Response byte count and register quantity agree.
- [ ] Unsigned and signed values are derived from the response bytes.
- [ ] Decoded value matches type, byte/word order, scale and offset.
- [ ] Physical/display reference identifies where the comparison came from.
- [ ] Test conditions are distinct, not the same observation renamed.
- [ ] Profiler version/commit and register-profile version are preserved.
- [ ] Confidence level meets the minimum evidence above.
- [ ] Rejected candidates retain raw evidence and a rejection reason.
- [ ] Archive path matches the UTC date, node and evidence ID.

## Validation commands

Install the pinned validation dependencies:

```bash
python -m pip install jsonschema==4.25.1 pytest==8.4.1
```

Validate one evidence file:

```bash
python scripts/validate-rs485-evidence.py \
  tests/fixtures/rs485-evidence/valid-confirmed.json \
  --require-files
```

Validate the committed archive:

```bash
python scripts/validate-rs485-evidence.py evidence/rs485
```

Run the semantic regression suite:

```bash
python -m pytest -q tests/test_validate_rs485_evidence.py
```

Check append-only changes against the target branch:

```bash
bash scripts/check-rs485-evidence-immutability.sh origin/main
```

## Validator guarantees

The validator checks JSON Schema, explicit UTC timestamps, ordering and uniqueness, Modbus CRC16, frame SHA-256, request/response identity, byte count, raw integer decoding, scale/offset consistency, confidence progression, profiler/profile versions and archive naming. CI separately blocks modification, deletion or renaming of committed evidence.

The validator does not replace physical engineering judgment. It ensures that any judgment is attached to complete, reproducible and immutable evidence.
