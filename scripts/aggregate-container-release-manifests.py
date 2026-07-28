#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def aggregate(inventory_path: Path, manifests_dir: Path) -> dict[str, Any]:
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
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != {
            "cyclonedx",
            "spdx",
            "vulnerabilities",
        }:
            raise AggregateFailure(f"{path} has incomplete evidence metadata")
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = aggregate(args.inventory, args.manifests_dir)
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
