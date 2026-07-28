from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_capacity_evidence import EvidenceError, verify_manifest  # noqa: E402

REQUIRED = {
    "results.json": "{}\n",
    "database-summary.json": "{}\n",
    "rest-latencies.json": "{}\n",
    "websocket-summary.json": "{}\n",
    "failure-recovery.json": "{}\n",
    "metrics-before.prom": "metric 0\n",
    "metrics-after.prom": "metric 1\n",
    "resource-observations.json": "{}\n",
    "compose-ps.txt": "healthy\n",
    "services.log": "sanitized\n",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_evidence(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "test-results-capacity"
    root.mkdir()
    for name, content in REQUIRED.items():
        (root / name).write_text(content, encoding="utf-8")

    policy = tmp_path / "release-workload.v1.yaml"
    policy.write_text("schema_version: 1\n", encoding="utf-8")
    artifacts = [
        {
            "path": name,
            "sha256": digest(root / name),
            "size_bytes": (root / name).stat().st_size,
        }
        for name in sorted(REQUIRED)
    ]
    manifest = {
        "schema_version": 1,
        "repository": "eNgine9r/nexolab-platform",
        "commit": "test",
        "policy": {
            "path": "release-workload.v1.yaml",
            "sha256": digest(policy),
            "schema_version": 1,
        },
        "max_evidence_bytes": 1_048_576,
        "results": {"status": "passed"},
        "artifacts": artifacts,
    }
    manifest_path = root / "release-readiness-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, manifest_path


def test_valid_manifest_passes(tmp_path: Path) -> None:
    root, manifest_path = make_evidence(tmp_path)
    assert verify_manifest(root, manifest_path)["results"]["status"] == "passed"


def test_tampered_artifact_fails(tmp_path: Path) -> None:
    root, manifest_path = make_evidence(tmp_path)
    (root / "results.json").write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(EvidenceError, match="mismatch"):
        verify_manifest(root, manifest_path)


def test_duplicate_artifact_path_fails(tmp_path: Path) -> None:
    root, manifest_path = make_evidence(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(EvidenceError, match="duplicate artifact path"):
        verify_manifest(root, manifest_path)


def test_path_traversal_fails(tmp_path: Path) -> None:
    root, manifest_path = make_evidence(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../escape.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(EvidenceError, match="unsafe artifact path"):
        verify_manifest(root, manifest_path)


def test_missing_required_artifact_fails(tmp_path: Path) -> None:
    root, manifest_path = make_evidence(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [
        entry for entry in manifest["artifacts"] if entry["path"] != "services.log"
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(EvidenceError, match="required evidence missing"):
        verify_manifest(root, manifest_path)
