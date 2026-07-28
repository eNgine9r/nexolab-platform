#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit(
        "jsonschema is required: python -m pip install jsonschema==4.25.1"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas/rs485-register-evidence.schema.json"
ARCHIVE_ROOT = ROOT / "evidence/rs485"
UTC_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
HEX_PATTERN = re.compile(r"^(?:[0-9A-F]{2})+$")


class EvidenceError(ValueError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvidenceError(f"{path}: unable to read file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc


def modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def verify_crc(frame: str) -> bool:
    if not HEX_PATTERN.fullmatch(frame) or len(frame) < 8:
        return False
    payload = bytes.fromhex(frame)
    expected = modbus_crc(payload[:-2])
    actual = payload[-2] | payload[-1] << 8
    return expected == actual


def frame_digest(request_frame: str, response_frame: str) -> str:
    canonical = f"{request_frame}\n{response_frame}".encode()
    return hashlib.sha256(canonical).hexdigest()


def parse_utc(value: str, label: str) -> datetime:
    if not UTC_PATTERN.fullmatch(value):
        raise EvidenceError(f"{label}: timestamp must be explicit UTC with Z suffix")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{label}: invalid UTC timestamp: {value}") from exc


def schema_errors(schema: dict[str, Any], payload: Any) -> list[str]:
    validator = Draft202012Validator(schema)
    messages = []
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    return messages


def request_contract(payload: dict[str, Any], sample: dict[str, Any], label: str) -> None:
    frame = bytes.fromhex(sample["request_frame"])
    if frame[0] != payload["unit_id"]:
        raise EvidenceError(f"{label}: request Unit ID does not match evidence unit_id")
    if frame[1] != payload["function_code"]:
        raise EvidenceError(f"{label}: request function code does not match evidence")
    if len(frame) < 8:
        raise EvidenceError(f"{label}: request frame is too short")
    address = int.from_bytes(frame[2:4], "big")
    quantity = int.from_bytes(frame[4:6], "big")
    if address != payload["register"]["address"]:
        raise EvidenceError(f"{label}: request register address mismatch")
    if quantity != payload["register"]["quantity"]:
        raise EvidenceError(f"{label}: request register quantity mismatch")


def response_register_bytes(
    payload: dict[str, Any], sample: dict[str, Any], label: str
) -> bytes:
    frame = bytes.fromhex(sample["response_frame"])
    if frame[0] != payload["unit_id"]:
        raise EvidenceError(f"{label}: response Unit ID does not match evidence unit_id")
    if frame[1] != payload["function_code"]:
        if frame[1] == payload["function_code"] | 0x80 and not sample["sample_pass"]:
            return b""
        raise EvidenceError(f"{label}: response function code does not match evidence")
    if len(frame) < 7:
        raise EvidenceError(f"{label}: response frame is too short")
    byte_count = frame[2]
    register_bytes = frame[3:-2]
    if byte_count != len(register_bytes):
        raise EvidenceError(f"{label}: response byte-count field is inconsistent")
    expected = payload["register"]["quantity"] * 2
    if len(register_bytes) != expected:
        raise EvidenceError(
            f"{label}: response contains {len(register_bytes)} register bytes; expected {expected}"
        )
    return register_bytes


def decoded_raw_value(
    value_type: str, register_bytes: bytes, byte_order: str, word_order: str
) -> tuple[int, int]:
    if value_type in {"uint16", "int16", "bits"}:
        unsigned = int.from_bytes(register_bytes[:2], byte_order, signed=False)
        signed = int.from_bytes(register_bytes[:2], byte_order, signed=True)
        return unsigned, signed

    if value_type in {"uint32", "int32"}:
        raw = register_bytes[:4]
        if word_order == "little":
            raw = raw[2:4] + raw[0:2]
        unsigned = int.from_bytes(raw, byte_order, signed=False)
        signed = int.from_bytes(raw, byte_order, signed=True)
        return unsigned, signed

    # float32 still retains the raw unsigned/signed integer representation in evidence.
    raw = register_bytes[:4]
    if word_order == "little":
        raw = raw[2:4] + raw[0:2]
    return (
        int.from_bytes(raw, byte_order, signed=False),
        int.from_bytes(raw, byte_order, signed=True),
    )


def sample_contract(payload: dict[str, Any], sample: dict[str, Any], index: int) -> None:
    label = f"samples[{index}] ({sample['sample_id']})"
    parse_utc(sample["timestamp_utc"], f"{label}.timestamp_utc")

    crc_request = verify_crc(sample["request_frame"])
    crc_response = verify_crc(sample["response_frame"])
    if sample["crc_ok"] != (crc_request and crc_response):
        raise EvidenceError(
            f"{label}: crc_ok={sample['crc_ok']} disagrees with calculated Modbus CRC16"
        )
    if sample["sample_pass"] and not sample["crc_ok"]:
        raise EvidenceError(f"{label}: a passing sample must have valid request and response CRC")

    expected_digest = frame_digest(sample["request_frame"], sample["response_frame"])
    if sample["frame_sha256"] != expected_digest:
        raise EvidenceError(f"{label}: frame_sha256 does not bind the raw request/response")

    request_contract(payload, sample, label)
    register_bytes = response_register_bytes(payload, sample, label)
    if not register_bytes:
        return

    register = payload["register"]
    value_type = register["value_type"]
    byte_order = register.get("byte_order", "big")
    word_order = register.get("word_order", "not-applicable")
    unsigned, signed = decoded_raw_value(value_type, register_bytes, byte_order, word_order)
    if sample["unsigned_value"] != unsigned:
        raise EvidenceError(f"{label}: unsigned_value does not match response frame")
    if sample["signed_value"] != signed:
        raise EvidenceError(f"{label}: signed_value does not match response frame")
    if not math.isclose(sample["scale"], register["scale"], rel_tol=0, abs_tol=1e-12):
        raise EvidenceError(f"{label}: sample scale does not match register profile scale")

    source_value = signed if value_type in {"int16", "int32"} else unsigned
    expected_decoded = source_value * register["scale"] + register.get("offset", 0)
    if value_type != "float32" and not math.isclose(
        sample["decoded_value"], expected_decoded, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise EvidenceError(
            f"{label}: decoded_value does not match raw value, scale, and offset"
        )


def decision_contract(payload: dict[str, Any]) -> None:
    samples = payload["samples"]
    decision = payload["decision"]
    confidence = decision["confidence"]
    passing = [sample for sample in samples if sample["sample_pass"]]
    conditions = {sample["test_condition"].strip().casefold() for sample in passing}
    devices = {sample["device_id"] for sample in passing}
    supported_references = {
        "display",
        "reference-instrument",
        "controlled-condition",
    }

    if confidence == "candidate":
        if not passing:
            raise EvidenceError("candidate evidence requires at least one passing sample")
        return

    if confidence == "correlated":
        if len(passing) < 2 or len(conditions) < 2:
            raise EvidenceError(
                "correlated evidence requires at least two passing samples under distinct conditions"
            )
        if any(
            sample["physical_reference"]["kind"] not in supported_references
            or sample["correlation"] not in {"observed", "confirmed"}
            for sample in passing
        ):
            raise EvidenceError(
                "correlated evidence requires physical references and observed correlation"
            )
        return

    if confidence == "confirmed":
        if len(passing) < 2 or len(conditions) < 2:
            raise EvidenceError(
                "confirmed evidence requires repeated passing samples under distinct conditions"
            )
        if any(
            sample["physical_reference"]["kind"]
            not in {"display", "reference-instrument"}
            or sample["correlation"] != "confirmed"
            for sample in passing
        ):
            raise EvidenceError(
                "confirmed evidence requires display/reference matching with confirmed correlation"
            )
        return

    if confidence == "portable":
        if len(devices) < 2:
            raise EvidenceError("portable evidence requires at least two physical device IDs")
        per_device = Counter(sample["device_id"] for sample in passing)
        if any(per_device[device] < 2 for device in devices) or len(conditions) < 2:
            raise EvidenceError(
                "portable evidence requires repeated passing confirmation on every device"
            )
        if any(
            sample["physical_reference"]["kind"]
            not in {"display", "reference-instrument"}
            or sample["correlation"] != "confirmed"
            for sample in passing
        ):
            raise EvidenceError(
                "portable evidence requires confirmed physical correlation for every passing sample"
            )
        return

    if confidence == "rejected":
        reason = decision.get("rejection_reason")
        if not isinstance(reason, str) or len(reason.strip()) < 5:
            raise EvidenceError("rejected evidence requires a retained rejection_reason")
        return

    raise EvidenceError(f"unsupported confidence level: {confidence}")


def archive_path_contract(path: Path, payload: dict[str, Any]) -> None:
    try:
        relative = path.resolve().relative_to(ARCHIVE_ROOT.resolve())
    except ValueError:
        return

    created = parse_utc(payload["created_at_utc"], "created_at_utc")
    expected = Path(
        f"{created.year:04d}",
        f"{created.month:02d}",
        f"{created.day:02d}",
        payload["node_id"],
        f"{payload['evidence_id']}.json",
    )
    if relative != expected:
        raise EvidenceError(
            f"archive path must be evidence/rs485/{expected.as_posix()}, got {relative.as_posix()}"
        )


def validate_evidence(
    path: Path, schema: dict[str, Any]
) -> tuple[str, set[str], set[str]]:
    payload = load_json(path)
    errors = schema_errors(schema, payload)
    if errors:
        raise EvidenceError(f"{path}: schema validation failed:\n  - " + "\n  - ".join(errors))

    parse_utc(payload["created_at_utc"], "created_at_utc")
    sample_ids = [sample["sample_id"] for sample in payload["samples"]]
    if len(sample_ids) != len(set(sample_ids)):
        raise EvidenceError(f"{path}: sample_id values must be unique inside evidence")

    timestamps = [
        parse_utc(sample["timestamp_utc"], f"samples[{index}].timestamp_utc")
        for index, sample in enumerate(payload["samples"])
    ]
    if timestamps != sorted(timestamps):
        raise EvidenceError(f"{path}: samples must be stored in ascending timestamp order")

    for index, sample in enumerate(payload["samples"]):
        sample_contract(payload, sample, index)
    decision_contract(payload)
    archive_path_contract(path, payload)

    evidence_id = payload["evidence_id"]
    frame_hashes = {sample["frame_sha256"] for sample in payload["samples"]}
    return evidence_id, set(sample_ids), frame_hashes


def discover(paths: Iterable[str]) -> list[Path]:
    discovered: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            discovered.update(path.rglob("*.json"))
        else:
            discovered.add(path)
    return sorted(path.resolve() for path in discovered if path.name != DEFAULT_SCHEMA.name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate immutable NEXOLAB RS-485 register evidence"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[str(ARCHIVE_ROOT)],
        help="Evidence JSON files or directories",
    )
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--require-files", action="store_true")
    args = parser.parse_args()

    schema_path = Path(args.schema)
    try:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"RS-485 evidence schema invalid: {exc}", file=sys.stderr)
        return 1

    files = discover(args.paths)
    if not files:
        if args.require_files:
            print("No RS-485 evidence files found", file=sys.stderr)
            return 1
        print("RS-485 evidence schema valid; no archive evidence files found")
        return 0

    evidence_ids: dict[str, Path] = {}
    sample_ids: dict[str, Path] = {}
    failures: list[str] = []
    confidence_counts: defaultdict[str, int] = defaultdict(int)

    for path in files:
        try:
            evidence_id, samples, _ = validate_evidence(path, schema)
            payload = load_json(path)
            confidence_counts[payload["decision"]["confidence"]] += 1
            if evidence_id in evidence_ids:
                raise EvidenceError(
                    f"duplicate evidence_id {evidence_id} also exists in {evidence_ids[evidence_id]}"
                )
            evidence_ids[evidence_id] = path
            for sample_id in samples:
                if sample_id in sample_ids:
                    raise EvidenceError(
                        f"duplicate sample_id {sample_id} also exists in {sample_ids[sample_id]}"
                    )
                sample_ids[sample_id] = path
        except EvidenceError as exc:
            failures.append(str(exc))

    if failures:
        print("RS-485 evidence validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    summary = ", ".join(
        f"{key}={confidence_counts[key]}" for key in sorted(confidence_counts)
    )
    print(
        f"RS-485 evidence valid: files={len(files)} samples={len(sample_ids)}"
        + (f" {summary}" if summary else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
