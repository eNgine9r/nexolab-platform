#!/usr/bin/env python3
"""Resolve a tracked, checksum-bound layered Device Agent runtime baseline.

This helper does not inspect or mutate running services. It binds the formal
source-deployment authority to a separately accepted Device Agent compatibility
runtime recorded in canonical project state and immutable runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class AuthorityFailure(ValueError):
    """Fail-closed layered-runtime authority error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AuthorityFailure(f"{label} is unavailable") from exc
    if path.is_symlink() or not resolved.is_file():
        raise AuthorityFailure(f"{label} is not a safe regular file")
    return resolved


def read_json(path: Path, label: str) -> dict:
    path = safe_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityFailure(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise AuthorityFailure(f"{label} must be a JSON object")
    return value


def parse_key_values(path: Path, label: str) -> dict[str, str]:
    path = safe_file(path, label)
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        if "=" not in raw:
            raise AuthorityFailure(f"{label} contains a non key-value row")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in result:
            raise AuthorityFailure(f"{label} contains a duplicate or empty key")
        result[key] = value
    return result


def resolve_evidence(repo: Path, relative: str, label: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise AuthorityFailure(f"{label} path must be repository-relative")
    root = (repo / "runtime" / "evidence").resolve()
    candidate = repo / relative
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AuthorityFailure(f"{label} is unavailable") from exc
    if candidate.is_symlink() or resolved.parent != root or not resolved.is_dir():
        raise AuthorityFailure(f"{label} must be a direct safe directory under runtime/evidence")
    return resolved


def verify_checksum_manifest(evidence: Path, required_names: tuple[str, ...]) -> None:
    manifest = safe_file(evidence / "SHA256SUMS", "runtime checksum manifest")
    required = {
        name: safe_file(evidence / name, f"runtime evidence {name}")
        for name in required_names
    }
    matches = {name: 0 for name in required_names}
    seen_targets: set[Path] = set()
    rows = 0
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw)
        if not match:
            raise AuthorityFailure("runtime checksum manifest contains an invalid row")
        expected, recorded = match.groups()
        candidate = Path(recorded)
        if not candidate.is_absolute():
            candidate = evidence / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise AuthorityFailure(f"checksum target is unavailable: {recorded}") from exc
        if candidate.is_symlink() or not resolved.is_file() or resolved.parent != evidence:
            raise AuthorityFailure("runtime checksum target escapes its evidence directory")
        if resolved in seen_targets:
            raise AuthorityFailure("runtime checksum manifest contains a duplicate target")
        seen_targets.add(resolved)
        if sha256_file(resolved) != expected:
            raise AuthorityFailure(f"runtime checksum mismatch: {resolved.name}")
        for name, required_path in required.items():
            if resolved == required_path:
                matches[name] += 1
        rows += 1
    if rows < len(required_names) or any(matches[name] != 1 for name in required_names):
        raise AuthorityFailure("runtime checksum manifest does not uniquely cover required authority files")


def resolve(
    repo: Path,
    *,
    expected_deployed_source: str,
    expected_formal_image: str,
) -> dict[str, str] | None:
    repo = repo.resolve()
    state = read_json(repo / ".project" / "ACTIVE_SPRINT.json", "canonical ACTIVE_SPRINT")
    baselines = state.get("baselines")
    if not isinstance(baselines, dict):
        raise AuthorityFailure("canonical ACTIVE_SPRINT baselines are missing")

    layered_keys = (
        "device_agent_compatibility_source_sha",
        "device_agent_image_id",
        "device_agent_rollback_image_id",
        "device_agent_runtime_evidence",
        "device_agent_pre_cutover_evidence",
    )
    configured = [key for key in layered_keys if baselines.get(key) not in {None, ""}]
    if not configured:
        return None
    if len(configured) != len(layered_keys) or baselines.get("deployed_product_sha") in {None, ""}:
        raise AuthorityFailure("layered Device Agent baseline is partially configured")

    deployed = str(baselines["deployed_product_sha"])
    compatibility = str(baselines["device_agent_compatibility_source_sha"])
    image = str(baselines["device_agent_image_id"])
    rollback_image = str(baselines["device_agent_rollback_image_id"])
    evidence_ref = str(baselines["device_agent_runtime_evidence"])
    pre_cutover_ref = str(baselines["device_agent_pre_cutover_evidence"])

    if not all(SHA_RE.fullmatch(value) for value in (deployed, compatibility, expected_deployed_source)):
        raise AuthorityFailure("layered Device Agent source identity is invalid")
    if not all(IMAGE_RE.fullmatch(value) for value in (image, rollback_image, expected_formal_image)):
        raise AuthorityFailure("layered Device Agent image identity is invalid")
    if deployed != expected_deployed_source:
        raise AuthorityFailure("layered Device Agent baseline does not match formal deployed source")
    if rollback_image != expected_formal_image:
        raise AuthorityFailure("layered Device Agent rollback image does not match formal deployment authority")

    pre_cutover = resolve_evidence(repo, pre_cutover_ref, "Device Agent pre-cutover evidence")
    verify_checksum_manifest(
        pre_cutover,
        ("source-lineage.txt", "candidate-device-agent.txt", "rollback-authority.txt"),
    )
    lineage = parse_key_values(pre_cutover / "source-lineage.txt", "Device Agent pre-cutover lineage evidence")
    candidate = parse_key_values(pre_cutover / "candidate-device-agent.txt", "Device Agent pre-cutover candidate evidence")
    rollback = parse_key_values(pre_cutover / "rollback-authority.txt", "Device Agent pre-cutover rollback evidence")

    lineage_required = {
        "status": "PASS",
        "formal_deployed_product_sha": deployed,
        "candidate_compatibility_source_sha": compatibility,
        "package_manifest_identity": "PASS",
        "accepted_identity_mismatches": "0",
        "release_ci": "PASS",
    }
    for key, expected in lineage_required.items():
        if lineage.get(key) != expected:
            raise AuthorityFailure(f"Device Agent pre-cutover lineage evidence mismatch: {key}")
    if not SHA_RE.fullmatch(lineage.get("candidate_parent_sha", "")):
        raise AuthorityFailure("Device Agent pre-cutover candidate parent identity is invalid")

    candidate_required = {
        "status": "PASS",
        "source_sha": compatibility,
        "image_id": image,
        "platform": "linux/arm64",
    }
    for key, expected in candidate_required.items():
        if candidate.get(key) != expected:
            raise AuthorityFailure(f"Device Agent pre-cutover candidate evidence mismatch: {key}")

    rollback_required = {
        "status": "READY",
        "current_device_agent_image_id": rollback_image,
        "active_env_mutated": "false",
        "dashboard_mutated": "false",
        "device_agent_mutated": "false",
        "telemetry_mutated": "false",
        "postgres_mutated": "false",
        "mqtt_mutated": "false",
        "modbus_write": "none",
        "hardware_write": "none",
        "persistent_data_deletion": "none",
        "named_volume_deletion": "none",
    }
    for key, expected in rollback_required.items():
        if rollback.get(key) != expected:
            raise AuthorityFailure(f"Device Agent pre-cutover rollback evidence mismatch: {key}")

    evidence = resolve_evidence(repo, evidence_ref, "Device Agent runtime evidence")
    verify_checksum_manifest(evidence, ("final-runtime.txt",))
    facts = parse_key_values(evidence / "final-runtime.txt", "Device Agent final runtime evidence")
    required = {
        "status": "PASS",
        "cutover_authorized_by_product_owner": "true",
        "compatibility_source": compatibility,
        "device_agent_image_id": image,
        "device_agent_previous_image_id": rollback_image,
        "modbus_write": "none",
        "hardware_write": "none",
        "persistent_data_deletion": "none",
        "named_volume_deletion": "none",
    }
    for key, expected in required.items():
        if facts.get(key) != expected:
            raise AuthorityFailure(f"Device Agent runtime evidence mismatch: {key}")

    return {
        "compatibility_source": compatibility,
        "device_agent_image_id": image,
        "device_agent_previous_image_id": rollback_image,
        "runtime_evidence": str(evidence.relative_to(repo)),
        "pre_cutover_evidence": str(pre_cutover.relative_to(repo)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-deployed-source", required=True)
    parser.add_argument("--expected-formal-image", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = resolve(
            args.repo,
            expected_deployed_source=args.expected_deployed_source,
            expected_formal_image=args.expected_formal_image,
        )
    except AuthorityFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if result is None:
        print("configured=false")
        return 0
    print("configured=true")
    for key in (
        "compatibility_source",
        "device_agent_image_id",
        "device_agent_previous_image_id",
        "runtime_evidence",
        "pre_cutover_evidence",
    ):
        print(f"{key}={result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
