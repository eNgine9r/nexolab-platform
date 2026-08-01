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
        "expires_on": "2026-12-31",
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


def test_exceptions_reject_wildcards(tmp_path: Path) -> None:
    entry = valid_exception()
    entry["vulnerability"] = "CVE-*"
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="wildcard"):
        MODULE.validate_exceptions(path, date(2026, 7, 28))


def test_exceptions_reject_expired_entries(tmp_path: Path) -> None:
    entry = valid_exception()
    entry["expires_on"] = "2026-07-27"
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="expired"):
        MODULE.validate_exceptions(path, date(2026, 7, 28))


def test_exceptions_require_exact_cve(tmp_path: Path) -> None:
    entry = valid_exception()
    entry["vulnerability"] = "GHSA-example"
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": [entry]},
    )
    with pytest.raises(ValidationFailure, match="exact CVE"):
        MODULE.validate_exceptions(path, date(2026, 7, 28))


def test_empty_exception_registry_is_valid(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "exceptions.json",
        {"schema_version": 1, "exceptions": []},
    )
    MODULE.validate_exceptions(path, date(2026, 7, 28))


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
