#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PLATFORMS = {"linux/amd64", "linux/arm64"}


class ManifestFailure(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestFailure(f"cannot read valid JSON from {path}") from exc
    if not isinstance(payload, dict):
        raise ManifestFailure(f"{path} must contain a JSON object")
    return payload


def sha256_file(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ManifestFailure(f"cannot read evidence file {path}") from exc
    if not content:
        raise ManifestFailure(f"evidence file is empty: {path}")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def validate_cyclonedx(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("bomFormat") != "CycloneDX":
        raise ManifestFailure("CycloneDX SBOM has invalid bomFormat")
    if not isinstance(payload.get("specVersion"), str):
        raise ManifestFailure("CycloneDX SBOM specVersion is required")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise ManifestFailure("CycloneDX SBOM must contain components")
    return payload


def validate_spdx(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    spdx_version = payload.get("spdxVersion")
    if not isinstance(spdx_version, str) or not spdx_version.startswith("SPDX-"):
        raise ManifestFailure("SPDX SBOM has invalid spdxVersion")
    if payload.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise ManifestFailure("SPDX SBOM must use SPDXRef-DOCUMENT")
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ManifestFailure("SPDX SBOM must contain packages")
    return payload


def validate_trivy(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload.get("SchemaVersion"), int):
        raise ManifestFailure("Trivy report SchemaVersion is required")
    if not isinstance(payload.get("Results"), list):
        raise ManifestFailure("Trivy report Results must be a list")
    return payload


def utc_timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestFailure("generated-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ManifestFailure("generated-at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(args.repository):
        raise ManifestFailure("repository must use owner/name format")
    if not COMMIT.fullmatch(args.commit):
        raise ManifestFailure("commit must be a full lowercase Git SHA")
    if not DIGEST.fullmatch(args.image_digest):
        raise ManifestFailure("image-digest must be sha256:<64 lowercase hex>")
    if args.platform not in PLATFORMS:
        raise ManifestFailure("platform is unsupported")

    dockerfile = args.dockerfile.resolve()
    cyclonedx = args.cyclonedx.resolve()
    spdx = args.spdx.resolve()
    vulnerabilities = args.vulnerabilities.resolve()
    validate_cyclonedx(cyclonedx)
    validate_spdx(spdx)
    validate_trivy(vulnerabilities)

    return {
        "schema_version": 1,
        "repository": args.repository,
        "commit": args.commit,
        "generated_at": utc_timestamp(args.generated_at),
        "image": {
            "id": args.image_id,
            "name": args.image_name,
            "platform": args.platform,
            "digest": args.image_digest,
            "dockerfile": str(args.dockerfile),
            "dockerfile_digest": sha256_file(dockerfile),
        },
        "evidence": {
            "cyclonedx": {
                "path": str(args.cyclonedx),
                "digest": sha256_file(cyclonedx),
            },
            "spdx": {
                "path": str(args.spdx),
                "digest": sha256_file(spdx),
            },
            "vulnerabilities": {
                "path": str(args.vulnerabilities),
                "digest": sha256_file(vulnerabilities),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--image-name", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--dockerfile", type=Path, required=True)
    parser.add_argument("--cyclonedx", type=Path, required=True)
    parser.add_argument("--spdx", type=Path, required=True)
    parser.add_argument("--vulnerabilities", type=Path, required=True)
    parser.add_argument("--generated-at")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = build_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote container release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManifestFailure as exc:
        print(f"Container release manifest failed: {exc}")
        raise SystemExit(1) from exc
