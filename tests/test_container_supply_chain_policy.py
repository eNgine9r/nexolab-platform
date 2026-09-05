from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate-container-supply-chain.py"
SPEC = importlib.util.spec_from_file_location("container_supply_chain", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ValidationFailure = MODULE.ValidationFailure


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_inventory(root: Path) -> dict[str, object]:
    context = root / "image"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    return {
        "schema_version": 1,
        "images": [
            {
                "id": "example-image",
                "image": "ghcr.io/engine9r/example-image",
                "context": "image",
                "dockerfile": "image/Dockerfile",
                "platforms": ["linux/amd64", "linux/arm64"],
            }
        ],
    }


def valid_exception() -> dict[str, str]:
    return {
        "image_id": "example-image",
        "package": "openssl",
        "vulnerability": "CVE-2026-12345",
        "reason": "No fixed package exists; exposure is blocked by the runtime profile.",
        "owner": "security-team",
        "expires_on": "2026-08-31",
    }


def test_inventory_accepts_existing_context_and_dockerfile(tmp_path: Path) -> None:
    path = write_json(tmp_path / "inventory.json", valid_inventory(tmp_path))
    MODULE.validate_inventory(path, tmp_path)


def test_inventory_rejects_missing_dockerfile(tmp_path: Path) -> None:
    payload = valid_inventory(tmp_path)
    payload["images"][0]["dockerfile"] = "image/missing.Dockerfile"
    path = write_json(tmp_path / "inventory.json", payload)
    with pytest.raises(ValidationFailure, match="does not exist"):
        MODULE.validate_inventory(path, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image_id", "telemetry-*"),
        ("package", "libcjson*"),
        ("vulnerability", "CVE-2026-*"),
    ],
)
def test_exceptions_reject_broad_match_patterns(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    entry = valid_exception()
    entry[field] = value
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="wildcard"):
        MODULE.validate_exceptions(path, date(2026, 8, 6))


def test_exceptions_reject_expired_entries(tmp_path: Path) -> None:
    entry = valid_exception()
    entry["expires_on"] = "2026-08-05"
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="expired"):
        MODULE.validate_exceptions(path, date(2026, 8, 6))


def test_exceptions_reject_long_lived_entries(tmp_path: Path) -> None:
    entry = valid_exception()
    entry["expires_on"] = "2026-09-21"
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="within 45 days"):
        MODULE.validate_exceptions(path, date(2026, 8, 6))


def test_exceptions_require_exact_cve(tmp_path: Path) -> None:
    entry = valid_exception()
    entry["vulnerability"] = "GHSA-example"
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="exact CVE"):
        MODULE.validate_exceptions(path, date(2026, 8, 6))


def test_empty_exception_registry_is_valid(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": []},
    )
    MODULE.validate_exceptions(path, date(2026, 8, 6))


def test_current_cjson_exception_is_exact_and_short_lived() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["image_id"] == "telemetry-service"
        and entry["package"] == "libcjson1"
        and entry["vulnerability"] == "CVE-2026-67216"
    ]

    assert len(matches) == 1
    decision = matches[0]
    assert decision["owner"] == "platform-security"
    assert decision["expires_on"] == "2026-09-12"
    assert "mosquitto_ctrl" in decision["reason"]
    assert "Reviewed 2026-08-17" in decision["reason"]
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 8, 17),
    )


def test_openssl_quic_exception_is_fully_retired_after_fresh_scan() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["vulnerability"] == "CVE-2026-14456"
    ]

    assert matches == []
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 8, 28),
    )


def test_expat_exception_is_retired_after_2026_09_05_fresh_scan() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["package"] == "libexpat1"
        and entry["vulnerability"] == "CVE-2026-66046"
    ]

    assert matches == []
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 5),
    )


def test_util_linux_78409_disagreement_is_explicit_and_short_lived() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["vulnerability"] == "CVE-2026-78409"
    ]

    assert len(matches) == 11
    assert {entry["image_id"] for entry in matches} == {
        "device-agent",
        "telegram-gateway",
        "telemetry-service",
    }
    assert all(entry["owner"] == "platform-security" for entry in matches)
    assert all(entry["expires_on"] == "2026-09-12" for entry in matches)
    assert all("33957510014" in entry["reason"] for entry in matches)
    assert all("2.41.5-0+deb13u1" in entry["reason"] for entry in matches)
    assert all("Red Hat CNA" in entry["reason"] for entry in matches)
    assert all("GHSA-8f2p-47x3-43mv" in entry["reason"] for entry in matches)
    assert all("Debian Security Tracker" in entry["reason"] for entry in matches)
    assert all("authoritative source data currently disagrees" in entry["reason"] for entry in matches)
    assert all("severity becomes Critical" in entry["reason"] for entry in matches)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 5),
    )


def test_current_device_agent_sqlite_exceptions_are_exact_and_short_lived() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["image_id"] == "device-agent"
        and entry["package"] == "libsqlite3-0"
        and entry["vulnerability"] in {"CVE-2026-11822", "CVE-2026-11824"}
    ]

    assert {entry["vulnerability"] for entry in matches} == {
        "CVE-2026-11822",
        "CVE-2026-11824",
    }
    assert all(entry["owner"] == "platform-security" for entry in matches)
    assert all(entry["expires_on"] == "2026-09-12" for entry in matches)
    assert all("33637555344" in entry["reason"] for entry in matches)
    assert all("e606b96cb65118b03e3807367322887529988d28" in entry["reason"] for entry in matches)
    assert all("FTS5" in entry["reason"] for entry in matches)
    assert all("arbitrary-SQL" in entry["reason"] for entry in matches)
    assert all("severity becomes Critical" in entry["reason"] for entry in matches)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 8, 26),
    )


def test_current_telemetry_fresh_scan_exceptions_are_exact_and_short_lived() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    expected = {
        ("libsqlite3-0", "CVE-2026-11822"),
        ("libsqlite3-0", "CVE-2026-11824"),
        ("libcjson1", "CVE-2026-16554"),
        ("libwebsockets19t64", "CVE-2026-78161"),
    }
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["image_id"] == "telemetry-service"
        and (entry["package"], entry["vulnerability"]) in expected
    ]

    assert {(entry["package"], entry["vulnerability"]) for entry in matches} == expected
    assert len(matches) == 4
    assert all(entry["owner"] == "platform-security" for entry in matches)
    assert all(entry["expires_on"] == "2026-09-12" for entry in matches)
    assert all("33637555344" in entry["reason"] for entry in matches)
    assert all("e606b96cb65118b03e3807367322887529988d28" in entry["reason"] for entry in matches)
    assert all("severity becomes Critical" in entry["reason"] for entry in matches)

    sqlite = [entry for entry in matches if entry["package"] == "libsqlite3-0"]
    assert all("FTS5" in entry["reason"] for entry in sqlite)
    assert all("arbitrary-SQL" in entry["reason"] for entry in sqlite)

    cjson = next(entry for entry in matches if entry["vulnerability"] == "CVE-2026-16554")
    assert "32-bit" in cjson["reason"]
    assert "linux/amd64" in cjson["reason"]
    assert "linux/arm64" in cjson["reason"]
    assert "mosquitto_ctrl" in cjson["reason"]

    websockets = next(entry for entry in matches if entry["vulnerability"] == "CVE-2026-78161")
    assert "4.3.5-1+deb13u1" in websockets["reason"]
    assert "4.5.0" in websockets["reason"]
    assert "LECP CBOR Recording" in websockets["reason"]
    assert "FastAPI/ASGI" in websockets["reason"]

    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 8, 27),
    )



def test_telemetry_systemd_homed_cve_exceptions_are_exact_and_short_lived() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["image_id"] == "telemetry-service"
        and entry["vulnerability"] == "CVE-2026-16742"
    ]

    assert {(entry["package"], entry["vulnerability"]) for entry in matches} == {
        ("libsystemd0", "CVE-2026-16742"),
        ("libudev1", "CVE-2026-16742"),
    }
    assert all(entry["owner"] == "platform-security" for entry in matches)
    assert all(entry["expires_on"] == "2026-09-12" for entry in matches)
    assert all("33683425564" in entry["reason"] for entry in matches)
    assert all("0f9327f40e9a2f4b8527be78f94c925246ab1c8d" in entry["reason"] for entry in matches)
    assert all("systemd-homed" in entry["reason"] for entry in matches)
    assert all("D-Bus and polkit are absent" in entry["reason"] for entry in matches)
    assert all("purge simulation is not dependency-safe" in entry["reason"] for entry in matches)
    assert all("severity becomes Critical" in entry["reason"] for entry in matches)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 3),
    )


def test_telemetry_image_installs_only_required_dynsec_client() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[1]
        / "services/telemetry-service/Dockerfile"
    ).read_text(encoding="utf-8")

    assert "mosquitto-clients" not in dockerfile
    assert "command -v mosquitto_ctrl >/dev/null" in dockerfile
    assert "! command -v mosquitto_pub >/dev/null" in dockerfile


def test_telemetry_image_hardens_python_supply_chain() -> None:
    root = Path(__file__).resolve().parents[1]
    requirements = (
        root / "services/telemetry-service/requirements.txt"
    ).read_text(encoding="utf-8")
    dockerfile = (
        root / "services/telemetry-service/Dockerfile"
    ).read_text(encoding="utf-8")
    exceptions = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )

    assert "msgpack==1.2.1" in requirements.splitlines()
    assert "python -m pip uninstall --yes setuptools" in dockerfile
    assert "! python -m pip show setuptools >/dev/null 2>&1" in dockerfile
    assert 'msgpack; print(msgpack.__version__)' in dockerfile
    assert '"1.2.1"' in dockerfile
    assert "python -m pip check" in dockerfile

    telemetry_exceptions = [
        entry
        for entry in exceptions["exceptions"]
        if entry["image_id"] == "telemetry-service"
    ]
    assert not any(
        entry["vulnerability"] == "CVE-2025-47273"
        for entry in telemetry_exceptions
    )
    assert not any(
        entry["package"] in {"msgpack", "setuptools"}
        for entry in telemetry_exceptions
    )


def test_workflow_refreshes_base_and_versions_device_agent_cache() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/container-supply-chain.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("pull: true") == 2
    assert '"supply-chain-v2-device-agent"' in workflow
    assert 'if image["id"] == "device-agent"' in workflow
    assert (
        workflow.count("cache-from: type=gha,scope=${{ matrix.cache_scope }}")
        == 2
    )
    assert (
        workflow.count(
            "cache-to: type=gha,mode=max,scope=${{ matrix.cache_scope }}"
        )
        == 2
    )
    assert (
        "cache-from: type=gha,scope=supply-chain-${{ matrix.id }}"
        not in workflow
    )


def test_workflow_binds_pull_request_evidence_to_head_sha() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/container-supply-chain.yml"
    ).read_text(encoding="utf-8")

    assert "SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert workflow.count("ref: ${{ env.SOURCE_SHA }}") == 4
    assert (
        "LOCAL_IMAGE: local/nexolab-${{ matrix.id }}:${{ github.event.pull_request.head.sha || github.sha }}"
        in workflow
    )
    assert (
        workflow.count(
            "org.opencontainers.image.revision=${{ env.SOURCE_SHA }}"
        )
        == 2
    )
    assert 'test "$revision" = "$SOURCE_SHA"' in workflow
    assert '--commit "$SOURCE_SHA"' in workflow
    assert '"commit": os.environ["SOURCE_SHA"],' in workflow
    assert workflow.count("github.sha") == 2
