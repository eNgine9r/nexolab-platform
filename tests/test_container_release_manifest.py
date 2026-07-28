from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate-container-release-manifest.py"
SPEC = importlib.util.spec_from_file_location("container_release_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def args(tmp_path: Path) -> argparse.Namespace:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    cyclonedx = write_json(
        tmp_path / "image.cdx.json",
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "library", "name": "example"}],
        },
    )
    spdx = write_json(
        tmp_path / "image.spdx.json",
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [{"name": "example", "SPDXID": "SPDXRef-Package-example"}],
        },
    )
    vulnerabilities = write_json(
        tmp_path / "image.trivy.json",
        {"SchemaVersion": 2, "Results": []},
    )
    return argparse.Namespace(
        repository="eNgine9r/nexolab-platform",
        commit="a" * 40,
        image_id="device-agent",
        image_name="ghcr.io/engine9r/nexolab-device-agent",
        platform="linux/amd64",
        image_digest="sha256:" + "b" * 64,
        dockerfile=dockerfile,
        cyclonedx=cyclonedx,
        spdx=spdx,
        vulnerabilities=vulnerabilities,
        generated_at="2026-07-28T08:00:00Z",
    )


def test_manifest_binds_image_and_evidence_digests(tmp_path: Path) -> None:
    manifest = MODULE.build_manifest(args(tmp_path))

    assert manifest["repository"] == "eNgine9r/nexolab-platform"
    assert manifest["commit"] == "a" * 40
    assert manifest["image"]["digest"] == "sha256:" + "b" * 64
    assert manifest["image"]["dockerfile_digest"].startswith("sha256:")
    assert manifest["evidence"]["cyclonedx"]["digest"].startswith("sha256:")
    assert manifest["evidence"]["spdx"]["digest"].startswith("sha256:")
    assert manifest["evidence"]["vulnerabilities"]["digest"].startswith("sha256:")
    assert manifest["generated_at"] == "2026-07-28T08:00:00Z"


def test_manifest_rejects_short_commit(tmp_path: Path) -> None:
    values = args(tmp_path)
    values.commit = "abc123"

    with pytest.raises(MODULE.ManifestFailure, match="full lowercase Git SHA"):
        MODULE.build_manifest(values)


def test_manifest_rejects_empty_cyclonedx_components(tmp_path: Path) -> None:
    values = args(tmp_path)
    write_json(
        values.cyclonedx,
        {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []},
    )

    with pytest.raises(MODULE.ManifestFailure, match="must contain components"):
        MODULE.build_manifest(values)


def test_manifest_rejects_invalid_spdx_document(tmp_path: Path) -> None:
    values = args(tmp_path)
    write_json(
        values.spdx,
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "wrong",
            "packages": [{"name": "example"}],
        },
    )

    with pytest.raises(MODULE.ManifestFailure, match="SPDXRef-DOCUMENT"):
        MODULE.build_manifest(values)


def test_manifest_rejects_empty_evidence_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_bytes(b"")

    with pytest.raises(MODULE.ManifestFailure, match="evidence file is empty"):
        MODULE.sha256_file(path)
