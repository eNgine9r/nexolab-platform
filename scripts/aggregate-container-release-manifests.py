#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class AggregateFailure(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AggregateFailure(f"cannot read valid JSON from {path}") from exc
    if not isinstance(payload, dict):
        raise AggregateFailure(f"{path} must contain a JSON object")
    return payload


def sha256_file(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise AggregateFailure(f"cannot read release evidence {path}") from exc
    if not content:
        raise AggregateFailure(f"release evidence is empty: {path}")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def resolve_evidence_path(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise AggregateFailure(f"{label}.path is required")
    path = (root / value).resolve()
    resolved_root = root.resolve()
    if resolved_root not in path.parents and path != resolved_root:
        raise AggregateFailure(f"{label}.path escapes evidence root")
    return path


def verify_digest(path: Path, expected: Any, label: str) -> None:
    if not isinstance(expected, str) or not DIGEST.fullmatch(expected):
        raise AggregateFailure(f"{label}.digest has invalid format")
    actual = sha256_file(path)
    if actual != expected:
        raise AggregateFailure(
            f"{label}.digest mismatch: expected {expected}, calculated {actual}"
        )


def aggregate(
    inventory_path: Path,
    manifests_dir: Path,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    root = (evidence_root or manifests_dir.parent).resolve()
    inventory = load_json(inventory_path)
    images = inventory.get("images")
    if not isinstance(images, list) or not images:
        raise AggregateFailure("container inventory must contain images")
    expected = {item["id"]: item for item in images if isinstance(item, dict)}
    if len(expected) != len(images):
        raise AggregateFailure("container inventory contains invalid or duplicate images")

    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(manifests_dir.glob("*.manifest.json")):
        payload = load_json(path)
        if payload.get("schema_version") != 1:
            raise AggregateFailure(f"{path} has unsupported schema_version")
        image = payload.get("image")
        if not isinstance(image, dict):
            raise AggregateFailure(f"{path} is missing image metadata")
        image_id = image.get("id")
        if not isinstance(image_id, str) or image_id not in expected:
            raise AggregateFailure(f"{path} references unknown image id")
        if image_id in manifests:
            raise AggregateFailure(f"duplicate manifest for {image_id}")
        if image.get("name") != expected[image_id]["image"]:
            raise AggregateFailure(f"{path} image name does not match inventory")

        dockerfile_path = resolve_evidence_path(
            root,
            image.get("dockerfile"),
            f"{path}.image.dockerfile",
        )
        verify_digest(
            dockerfile_path,
            image.get("dockerfile_digest"),
            f"{path}.image.dockerfile",
        )

        evidence = payload.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != {
            "cyclonedx",
            "spdx",
            "vulnerabilities",
        }:
            raise AggregateFailure(f"{path} has incomplete evidence metadata")
        for evidence_name, metadata in evidence.items():
            label = f"{path}.evidence.{evidence_name}"
            if not isinstance(metadata, dict):
                raise AggregateFailure(f"{label} must be an object")
            evidence_path = resolve_evidence_path(root, metadata.get("path"), label)
            verify_digest(evidence_path, metadata.get("digest"), label)
        manifests[image_id] = payload

    missing = sorted(set(expected) - set(manifests))
    if missing:
        raise AggregateFailure("missing manifests: " + ", ".join(missing))

    commits = {payload.get("commit") for payload in manifests.values()}
    repositories = {payload.get("repository") for payload in manifests.values()}
    if len(commits) != 1 or None in commits:
        raise AggregateFailure("all manifests must bind to one exact commit")
    if len(repositories) != 1 or None in repositories:
        raise AggregateFailure("all manifests must bind to one repository")

    return {
        "schema_version": 1,
        "repository": next(iter(repositories)),
        "commit": next(iter(commits)),
        "images": [manifests[image_id] for image_id in sorted(manifests)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("security/container-images.json"),
    )
    parser.add_argument("--manifests-dir", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = aggregate(
        args.inventory,
        args.manifests_dir,
        evidence_root=args.evidence_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote aggregate release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AggregateFailure as exc:
        print(f"Aggregate container release manifest failed: {exc}")
        raise SystemExit(1) from exc
