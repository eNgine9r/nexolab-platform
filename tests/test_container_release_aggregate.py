from __future__ import annotations

import hashlib
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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


def write_evidence(tmp_path: Path, image_id: str) -> dict[str, object]:
    evidence_dir = tmp_path / "evidence"
    dockerfile = tmp_path / "dockerfiles" / image_id / "Dockerfile"
    dockerfile.parent.mkdir(parents=True, exist_ok=True)
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    files = {}
    for name, suffix in (
        ("cyclonedx", "cdx.json"),
        ("spdx", "spdx.json"),
        ("vulnerabilities", "trivy.json"),
    ):
        path = write_json(
            evidence_dir / f"{image_id}.{suffix}",
            {"image_id": image_id, "kind": name},
        )
        files[name] = {
            "path": str(path.relative_to(tmp_path)),
            "digest": digest(path),
        }
    return {
        "dockerfile": str(dockerfile.relative_to(tmp_path)),
        "dockerfile_digest": digest(dockerfile),
        "evidence": files,
    }


def manifest(
    tmp_path: Path,
    image_id: str,
    image_name: str,
    commit: str = "a" * 40,
) -> dict[str, object]:
    files = write_evidence(tmp_path, image_id)
    return {
        "schema_version": 1,
        "repository": "eNgine9r/nexolab-platform",
        "commit": commit,
        "image": {
            "id": image_id,
            "name": image_name,
            "dockerfile": files["dockerfile"],
            "dockerfile_digest": files["dockerfile_digest"],
        },
        "evidence": files["evidence"],
    }


def write_complete_manifests(tmp_path: Path) -> Path:
    directory = tmp_path / "evidence"
    directory.mkdir(exist_ok=True)
    write_json(
        directory / "device-agent.manifest.json",
        manifest(tmp_path, "device-agent", "ghcr.io/engine9r/nexolab-device-agent"),
    )
    write_json(
        directory / "telemetry-service.manifest.json",
        manifest(
            tmp_path,
            "telemetry-service",
            "ghcr.io/engine9r/nexolab-telemetry-service",
        ),
    )
    return directory


def test_aggregate_requires_complete_inventory(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)

    payload = MODULE.aggregate(
        inventory(tmp_path),
        directory,
        evidence_root=tmp_path,
    )

    assert payload["commit"] == "a" * 40
    assert [item["image"]["id"] for item in payload["images"]] == [
        "device-agent",
        "telemetry-service",
    ]


def test_aggregate_rejects_missing_manifest(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    (directory / "telemetry-service.manifest.json").unlink()

    with pytest.raises(MODULE.AggregateFailure, match="missing manifests"):
        MODULE.aggregate(inventory(tmp_path), directory, evidence_root=tmp_path)


def test_aggregate_rejects_mixed_commits(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    write_json(
        directory / "telemetry-service.manifest.json",
        manifest(
            tmp_path,
            "telemetry-service",
            "ghcr.io/engine9r/nexolab-telemetry-service",
            commit="b" * 40,
        ),
    )

    with pytest.raises(MODULE.AggregateFailure, match="one exact commit"):
        MODULE.aggregate(inventory(tmp_path), directory, evidence_root=tmp_path)


def test_aggregate_rejects_image_name_drift(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    write_json(
        directory / "device-agent.manifest.json",
        manifest(tmp_path, "device-agent", "ghcr.io/engine9r/wrong-image"),
    )

    with pytest.raises(MODULE.AggregateFailure, match="does not match inventory"):
        MODULE.aggregate(inventory(tmp_path), directory, evidence_root=tmp_path)


def test_aggregate_rejects_tampered_evidence(tmp_path: Path) -> None:
    directory = write_complete_manifests(tmp_path)
    evidence = tmp_path / "evidence" / "device-agent.cdx.json"
    evidence.write_text("tampered", encoding="utf-8")

    with pytest.raises(MODULE.AggregateFailure, match="digest mismatch"):
        MODULE.aggregate(inventory(tmp_path), directory, evidence_root=tmp_path)
