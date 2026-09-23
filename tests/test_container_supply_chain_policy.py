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
    assert decision["expires_on"] == "2026-09-29"
    assert "mosquitto_ctrl" in decision["reason"]
    assert "Reviewed 2026-08-17" in decision["reason"]
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 8, 17),
    )


def test_2026_09_22_fresh_review_is_exact_owner_bound_and_seven_day_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    exceptions = payload["exceptions"]
    reviewed = [
        entry for entry in exceptions if entry["vulnerability"] != "CVE-2026-93990"
    ]
    keys = {
        (entry["image_id"], entry["package"], entry["vulnerability"])
        for entry in reviewed
    }

    assert len(reviewed) == 90
    assert len(keys) == 90
    assert {entry["image_id"] for entry in reviewed} == {
        "device-agent",
        "telegram-gateway",
        "telemetry-service",
    }
    assert all(entry["owner"] == "platform-security" for entry in reviewed)
    assert all(entry["expires_on"] == "2026-09-29" for entry in reviewed)
    assert all("35704565417" in entry["reason"] for entry in reviewed)
    assert all(
        "2524f9c0c15218cc56a0416ecc76cb46040fab79" in entry["reason"]
        for entry in reviewed
    )
    assert all("90 HIGH / 0 CRITICAL" in entry["reason"] for entry in reviewed)
    assert all("supersedes the prior expiry wording" in entry["reason"] for entry in reviewed)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 22),
    )


def test_2026_09_23_expat_93990_findings_are_exact_and_short_lived() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["package"] == "libexpat1"
        and entry["vulnerability"] == "CVE-2026-93990"
    ]

    assert len(matches) == 2
    assert {entry["image_id"] for entry in matches} == {"device-agent", "telegram-gateway"}
    assert all(entry["owner"] == "platform-security" for entry in matches)
    assert all(entry["expires_on"] == "2026-09-29" for entry in matches)
    assert all("35866744217" in entry["reason"] for entry in matches)
    assert all("2.8.3-1~deb13u1" in entry["reason"] for entry in matches)
    assert all("no XML, pyexpat, Expat, ElementTree, SAX, minidom, or lxml" in entry["reason"] for entry in matches)
    assert all("severity becomes Critical" in entry["reason"] for entry in matches)


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


def test_2026_09_17_expat_66046_findings_are_current_and_bounded() -> None:
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

    assert len(matches) == 2
    assert {entry["image_id"] for entry in matches} == {"device-agent", "telegram-gateway"}
    assert all(entry["owner"] == "platform-security" for entry in matches)
    assert all(entry["expires_on"] == "2026-09-29" for entry in matches)
    assert all("35156866062" in entry["reason"] for entry in matches)
    assert all("2.8.4" in entry["reason"] for entry in matches)
    assert all("no XML/pyexpat parser path" in entry["reason"] for entry in matches)
    assert all("severity becomes Critical" in entry["reason"] for entry in matches)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 17),
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
    assert all(entry["expires_on"] == "2026-09-29" for entry in matches)
    assert all("34826380930" in entry["reason"] for entry in matches)
    assert all("02f42ff68c6189bc4c0cf2fcfa4be0503b0667bf" in entry["reason"] for entry in matches)
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


def test_2026_09_14_expat_findings_are_current_and_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["package"] == "libexpat1"
        and entry["vulnerability"] in {"CVE-2026-76956", "CVE-2026-76957"}
    ]

    assert len(matches) == 4
    assert {entry["image_id"] for entry in matches} == {"device-agent", "telegram-gateway"}
    assert all(entry["expires_on"] == "2026-09-29" for entry in matches)
    assert all("34826380930" in entry["reason"] for entry in matches)
    assert all("2.8.3-1~deb13u1" in entry["reason"] for entry in matches)
    assert all("2.8.4" in entry["reason"] for entry in matches)
    assert all("no XML/pyexpat/XMLParser/UnknownEncodingHandler path" in entry["reason"] for entry in matches)


def test_2026_09_17_fresh_scan_keeps_stale_python_and_sqlite_retired_and_bounds_new_python_findings() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    exceptions = payload["exceptions"]
    stale = {
        (image_id, package, vulnerability)
        for image_id in {"device-agent", "telegram-gateway"}
        for package, vulnerability in {
            ("libpython3.13-minimal", "CVE-2026-11940"),
            ("libpython3.13-stdlib", "CVE-2026-11940"),
            ("python3.13-minimal", "CVE-2026-11940"),
            ("python3.13-venv", "CVE-2026-11940"),
            ("libsqlite3-0", "CVE-2026-11822"),
            ("libsqlite3-0", "CVE-2026-11824"),
        }
    }
    keys = {
        (entry["image_id"], entry["package"], entry["vulnerability"])
        for entry in exceptions
    }
    current_python = [
        entry for entry in exceptions if entry["vulnerability"] == "CVE-2026-82049"
    ]
    prior_review = [
        entry
        for entry in exceptions
        if entry["vulnerability"] not in {"CVE-2026-66046", "CVE-2026-82049", "CVE-2026-93990"}
    ]

    assert len(keys) == len(exceptions)
    assert keys.isdisjoint(stale)
    assert len(prior_review) == 80
    assert all("34826380930" in entry["reason"] for entry in prior_review)
    assert all("02f42ff68c6189bc4c0cf2fcfa4be0503b0667bf" in entry["reason"] for entry in prior_review)
    assert len(current_python) == 8
    assert {entry["image_id"] for entry in current_python} == {"device-agent", "telegram-gateway"}
    assert {entry["package"] for entry in current_python} == {
        "libpython3.13-minimal",
        "libpython3.13-stdlib",
        "python3.13-minimal",
        "python3.13-venv",
    }
    assert all(entry["owner"] == "platform-security" for entry in exceptions)
    assert all(entry["expires_on"] == "2026-09-29" for entry in exceptions)
    assert all("35156866062" in entry["reason"] for entry in current_python)
    assert all("no tarfile/archive extraction path" in entry["reason"] for entry in current_python)
    assert all("severity becomes Critical" in entry["reason"] for entry in current_python)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 17),
    )


def test_2026_09_12_consolidated_review_keeps_telemetry_stale_findings_retired() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    exceptions = payload["exceptions"]
    stale = {
        ("telemetry-service", "gzip", "CVE-2026-41992"),
        ("telemetry-service", "libsqlite3-0", "CVE-2026-11822"),
        ("telemetry-service", "libsqlite3-0", "CVE-2026-11824"),
        ("telemetry-service", "libwebsockets19t64", "CVE-2026-78161"),
    }
    keys = {
        (entry["image_id"], entry["package"], entry["vulnerability"])
        for entry in exceptions
    }

    assert keys.isdisjoint(stale)
    assert all(entry["owner"] == "platform-security" for entry in exceptions)
    MODULE.validate_exceptions(
        root / "security/vulnerability-exceptions.json",
        date(2026, 9, 14),
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
    assert all(entry["expires_on"] == "2026-09-29" for entry in matches)
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


def test_telemetry_cjson_mergepatch_exception_is_exact_and_unreachable() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "security/vulnerability-exceptions.json").read_text(encoding="utf-8")
    )
    matches = [
        entry
        for entry in payload["exceptions"]
        if entry["image_id"] == "telemetry-service"
        and entry["package"] == "libcjson1"
        and entry["vulnerability"] == "CVE-2026-87933"
    ]

    assert len(matches) == 1
    decision = matches[0]
    assert decision["owner"] == "platform-security"
    assert decision["expires_on"] == "2026-09-29"
    assert "34826380930" in decision["reason"]
    assert "34702355254" in decision["reason"]
    assert "1e1576b9edc5eac5f3be017753c382fc39c19278" in decision["reason"]
    assert "libcjson_utils.so.1.7.18" in decision["reason"]
    assert "DT_NEEDED" in decision["reason"]
    assert "mosquitto_ctrl" in decision["reason"]
    assert "Merge Patch" in decision["reason"]
    assert "severity becomes Critical" in decision["reason"]



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
