from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate-rs485-evidence.py"
SPEC = importlib.util.spec_from_file_location("validate_rs485_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

SCHEMA = validator.load_json(ROOT / "schemas/rs485-register-evidence.schema.json")
VALID_FIXTURE = ROOT / "tests/fixtures/rs485-evidence/valid-confirmed.json"


def fixture() -> dict[str, object]:
    return json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))


def write_payload(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_confirmed_fixture_is_valid() -> None:
    evidence_id, sample_ids, frame_hashes = validator.validate_evidence(
        VALID_FIXTURE, SCHEMA
    )
    assert evidence_id == "le01mp-201-voltage-register-0000"
    assert len(sample_ids) == 2
    assert len(frame_hashes) == 2


def test_one_sample_cannot_be_confirmed(tmp_path: Path) -> None:
    payload = fixture()
    payload["samples"] = payload["samples"][:1]
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="confirmed evidence requires repeated"):
        validator.validate_evidence(path, SCHEMA)


def test_bad_modbus_crc_is_rejected(tmp_path: Path) -> None:
    payload = fixture()
    payload["samples"][0]["response_frame"] = "01030208E17FCD"
    payload["samples"][0]["frame_sha256"] = validator.frame_digest(
        payload["samples"][0]["request_frame"], payload["samples"][0]["response_frame"]
    )
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="calculated Modbus CRC16"):
        validator.validate_evidence(path, SCHEMA)


def test_frame_hash_tampering_is_rejected(tmp_path: Path) -> None:
    payload = fixture()
    payload["samples"][0]["frame_sha256"] = "0" * 64
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="does not bind"):
        validator.validate_evidence(path, SCHEMA)


def test_decoded_value_must_match_raw_scale_and_offset(tmp_path: Path) -> None:
    payload = fixture()
    payload["samples"][1]["decoded_value"] = 999.0
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="decoded_value does not match"):
        validator.validate_evidence(path, SCHEMA)


def test_correlated_requires_distinct_conditions(tmp_path: Path) -> None:
    payload = fixture()
    payload["decision"]["confidence"] = "correlated"
    payload["samples"][1]["test_condition"] = payload["samples"][0]["test_condition"]
    payload["samples"][0]["correlation"] = "observed"
    payload["samples"][1]["correlation"] = "observed"
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="distinct conditions"):
        validator.validate_evidence(path, SCHEMA)


def test_portable_requires_multiple_devices(tmp_path: Path) -> None:
    payload = fixture()
    payload["decision"]["confidence"] = "portable"
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="two physical device IDs"):
        validator.validate_evidence(path, SCHEMA)


def test_rejected_decision_retains_reason(tmp_path: Path) -> None:
    payload = fixture()
    payload["decision"]["confidence"] = "rejected"
    payload["decision"]["rejection_reason"] = None
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="rejection_reason"):
        validator.validate_evidence(path, SCHEMA)


def test_schema_rejects_missing_profiler_version(tmp_path: Path) -> None:
    payload = deepcopy(fixture())
    del payload["profiler"]["version"]
    path = write_payload(tmp_path, payload)

    with pytest.raises(validator.EvidenceError, match="schema validation failed"):
        validator.validate_evidence(path, SCHEMA)
