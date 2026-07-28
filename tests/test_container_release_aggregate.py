from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "aggregate-container-release-manifests.py"
SPEC = importlib.util.spec_from_file_location("container_release_aggregate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def inventory(tmp_path: Path) -> Path:
    return write_json(
        tmp_path / "inventory.json",
        {
            "schema_version": 1,
            "images": [
                {
                    "id": "device-agent",
                    "image": "ghcr.io/engine9r/nexolab-device-agent",
                },
                {
                    "id": "telemetry-service",
                    "image": "ghcr.io/engine9r/nexolab-telemetry-service",
                },
            ],
        },
    )


def manifest(image_id: str, image_name: str, commit: str = "a" * 40) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": "eNgine9r/nexolab-platform",
        "commit": commit,
        "image": {"id": image_id, "name": image_name},
        "evidence": {
            "cyclonedx": {"digest": "sha256:" + "1" * 64},
            "spdx": {"digest": "sha256:" + "2" * 64},
            "vulnerabilities": {"digest": "sha256:" + "3" * 64},
        },
    }


def write_complete_manifests(tmp_path: Path) -> Path:
    directory = tmp_path / "manifests"
    directory.mkdir()
    write_json(
        directory / "device-agent.manifest.json",
        manifest("device-agent", "ghcr.io/engine9r/nexolab-device-agent"),
    )
    write_json(
        directory / "telemetry-service.manifest.json",
        manifest(
            "telemetry-service",
            "ghcr.io/engine9r/nexolab-telemetry-service",
        ),
    )
    return directory


def test_aggregate_requires_complete_inventory(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)

    payload = MODULE.aggregate(inventory(tmp_path), directory)

    assert payload["commit"] == "a" * 40
    assert [item["image"]["id"] for item in payload["images"]] == [
        "device-agent",
        "telemetry-service",
    ]


def test_aggregate_rejects_missing_manifest(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    (directory / "telemetry-service.manifest.json").unlink()

    with pytest.raises(MODULE.AggregateFailure, match="missing manifests"):
        MODULE.aggregate(inventory(tmp_path), directory)


def test_aggregate_rejects_mixed_commits(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    write_json(
        directory / "telemetry-service.manifest.json",
        manifest(
            "telemetry-service",
            "ghcr.io/engine9r/nexolab-telemetry-service",
            commit="b" * 40,
        ),
    )

    with pytest.raises(MODULE.AggregateFailure, match="one exact commit"):
        MODULE.aggregate(inventory(tmp_path), directory)


def test_aggregate_rejects_image_name_drift(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    write_json(
        directory / "device-agent.manifest.json",
        manifest("device-agent", "ghcr.io/engine9r/wrong-image"),
    )

    with pytest.raises(MODULE.AggregateFailure, match="does not match inventory"):
        MODULE.aggregate(inventory(tmp_path), directory)
