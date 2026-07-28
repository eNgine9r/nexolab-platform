#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


class EvidenceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise EvidenceError("artifact path must be a non-empty string")
    if "\\" in value:
        raise EvidenceError(f"artifact path uses backslashes: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise EvidenceError(f"artifact path must be relative: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError(f"unsafe artifact path: {value}")
    return path


def verify_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"unable to load manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise EvidenceError("manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise EvidenceError("manifest schema_version must equal 1")
    if manifest.get("repository") != "eNgine9r/nexolab-platform":
        raise EvidenceError("manifest repository mismatch")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise EvidenceError("manifest artifacts must be a non-empty list")

    required = {
        "results.json",
        "database-summary.json",
        "rest-latencies.json",
        "websocket-summary.json",
        "failure-recovery.json",
        "metrics-before.prom",
        "metrics-after.prom",
        "resource-observations.json",
        "compose-ps.txt",
        "services.log",
    }
    seen: set[str] = set()
    total_bytes = 0
    root_resolved = root.resolve(strict=True)
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise EvidenceError("artifact entry must be an object")
        relative = _safe_relative_path(entry.get("path"))
        key = relative.as_posix()
        if key in seen:
            raise EvidenceError(f"duplicate artifact path: {key}")
        seen.add(key)
        path = root.joinpath(*relative.parts)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise EvidenceError(f"missing artifact {key}: {exc}") from exc
        if root_resolved not in resolved.parents:
            raise EvidenceError(f"artifact escapes evidence root: {key}")
        if not resolved.is_file():
            raise EvidenceError(f"artifact is not a regular file: {key}")

        size = resolved.stat().st_size
        expected_size = entry.get("size_bytes")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            raise EvidenceError(f"invalid size for artifact: {key}")
        if expected_size != size:
            raise EvidenceError(
                f"artifact size mismatch for {key}: expected {expected_size}, got {size}"
            )
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise EvidenceError(f"invalid sha256 for artifact: {key}")
        actual_sha = sha256_file(resolved)
        if actual_sha != expected_sha:
            raise EvidenceError(
                f"artifact sha256 mismatch for {key}: expected {expected_sha}, got {actual_sha}"
            )
        total_bytes += size

    missing = sorted(required - seen)
    if missing:
        raise EvidenceError(f"required evidence missing from manifest: {missing}")

    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        raise EvidenceError("manifest policy entry is required")
    policy_path = _safe_relative_path(policy.get("path"))
    policy_file = root.parent.joinpath(*policy_path.parts)
    if not policy_file.is_file():
        raise EvidenceError(f"versioned policy not found: {policy_path}")
    policy_sha = policy.get("sha256")
    if policy_sha != sha256_file(policy_file):
        raise EvidenceError("workload policy digest mismatch")

    max_bytes = manifest.get("max_evidence_bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise EvidenceError("manifest max_evidence_bytes must be a positive integer")
    if total_bytes > max_bytes:
        raise EvidenceError(
            f"evidence exceeds configured limit: {total_bytes} > {max_bytes}"
        )

    results = manifest.get("results")
    if not isinstance(results, dict) or results.get("status") != "passed":
        raise EvidenceError("manifest results must report passed")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify NEXOLAB capacity evidence")
    parser.add_argument("evidence_dir", nargs="?", default="test-results-capacity")
    parser.add_argument("--manifest", default="release-readiness-manifest.json")
    args = parser.parse_args()

    root = Path(args.evidence_dir)
    try:
        manifest = verify_manifest(root, root / args.manifest)
    except EvidenceError as exc:
        print(f"capacity evidence invalid: {exc}")
        return 1
    print(
        "capacity evidence valid: "
        f"commit={manifest.get('commit')} artifacts={len(manifest['artifacts'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
