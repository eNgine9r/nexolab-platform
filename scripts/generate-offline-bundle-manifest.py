#!/usr/bin/env python3
"""Generate a digest-bound manifest for a NEXOLAB offline bundle."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def docker_inspect(reference: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise SystemExit(f"Unexpected docker inspect response for {reference}")
    return payload[0]


def parse_image(value: str) -> tuple[str, str]:
    logical_id, separator, reference = value.partition("=")
    if not separator or not logical_id or not reference:
        raise argparse.ArgumentTypeError("image must use logical-id=reference")
    return logical_id, reference


def relative_files(bundle_root: Path) -> list[Path]:
    excluded = {"manifest.json", "SHA256SUMS"}
    return sorted(
        path
        for path in bundle_root.rglob("*")
        if path.is_file() and path.relative_to(bundle_root).as_posix() not in excluded
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--bundle-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--platform", required=True, choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--schema-head", required=True)
    parser.add_argument("--upgrade-from-schema-head", action="append", default=[])
    parser.add_argument("--runtime-compatible-schema-head", action="append", default=[])
    parser.add_argument("--dashboard-api-base-url", required=True)
    parser.add_argument("--dashboard-websocket-url", required=True)
    parser.add_argument("--dashboard-origin", required=True)
    parser.add_argument(
        "--dashboard-auth-provider",
        required=True,
        choices=("disabled", "local", "acceptance", "supabase"),
    )
    parser.add_argument("--image", action="append", type=parse_image, required=True)
    parser.add_argument("--output", default="manifest.json")
    args = parser.parse_args()

    bundle_root = args.bundle_root.resolve()
    if not bundle_root.is_dir():
        raise SystemExit(f"Bundle root does not exist: {bundle_root}")
    for label, values in (
        ("schema head", [args.schema_head]),
        ("upgrade schema head", args.upgrade_from_schema_head),
        ("runtime-compatible schema head", args.runtime_compatible_schema_head),
    ):
        if any(not value.strip() or len(value) > 128 for value in values):
            raise SystemExit(f"Invalid {label}")

    expected_arch = args.platform.split("/", maxsplit=1)[1]
    images: list[dict[str, Any]] = []
    logical_ids: set[str] = set()
    for logical_id, reference in args.image:
        if logical_id in logical_ids:
            raise SystemExit(f"Duplicate image id: {logical_id}")
        logical_ids.add(logical_id)
        inspected = docker_inspect(reference)
        architecture = inspected.get("Architecture")
        operating_system = inspected.get("Os")
        if architecture != expected_arch or operating_system != "linux":
            raise SystemExit(
                f"Image {reference} platform mismatch: {operating_system}/{architecture}, "
                f"expected {args.platform}"
            )
        image_id = inspected.get("Id")
        if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
            raise SystemExit(f"Image {reference} has no content-addressed image ID")

        cyclone = bundle_root / "evidence" / f"{logical_id}.cdx.json"
        spdx = bundle_root / "evidence" / f"{logical_id}.spdx.json"
        for evidence in (cyclone, spdx):
            if not evidence.is_file():
                raise SystemExit(f"Missing SBOM evidence: {evidence}")

        images.append(
            {
                "id": logical_id,
                "reference": reference,
                "image_id": image_id,
                "repo_digests": sorted(inspected.get("RepoDigests") or []),
                "platform": f"{operating_system}/{architecture}",
                "size_bytes": int(inspected.get("Size") or 0),
                "sbom": {
                    "cyclonedx": {
                        "path": cyclone.relative_to(bundle_root).as_posix(),
                        "sha256": sha256(cyclone),
                    },
                    "spdx": {
                        "path": spdx.relative_to(bundle_root).as_posix(),
                        "sha256": sha256(spdx),
                    },
                },
            }
        )

    archive = bundle_root / "images" / "nexolab-images.tar"
    if not archive.is_file():
        raise SystemExit(f"Missing image archive: {archive}")

    files = []
    for path in relative_files(bundle_root):
        files.append(
            {
                "path": path.relative_to(bundle_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )

    manifest = {
        "schema_version": 1,
        "bundle_version": args.bundle_version,
        "source_repository": "eNgine9r/nexolab-platform",
        "source_commit": args.source_commit,
        "created_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "platform": args.platform,
        "runtime_network_required": False,
        "paid_runtime_service_required": False,
        "secrets_included": False,
        "dashboard": {
            "origin": args.dashboard_origin,
            "api_base_url": args.dashboard_api_base_url,
            "websocket_url": args.dashboard_websocket_url,
            "auth_provider": args.dashboard_auth_provider,
            "configuration_phase": "image_build",
        },
        "local_auth": {
            "supported": True,
            "selected": args.dashboard_auth_provider == "local",
            "secrets_packaged": False,
            "compose_overlay": "deploy/compose/compose.local-auth.yaml",
        },
        "images_archive": {
            "path": archive.relative_to(bundle_root).as_posix(),
            "size_bytes": archive.stat().st_size,
            "sha256": sha256(archive),
        },
        "images": sorted(images, key=lambda image: image["id"]),
        "files": files,
        "persistent_data_policy": {
            "packaged": False,
            "delete_volumes": False,
            "compose_down_v_allowed": False,
        },
        "version_management": {
            "bundle_id": f"{args.bundle_version}-{expected_arch}-{args.source_commit[:12]}",
            "database_schema": {
                "head": args.schema_head,
                "upgrade_from": sorted(set(args.upgrade_from_schema_head or [args.schema_head])),
                "runtime_compatible_schema_heads": sorted(
                    set(args.runtime_compatible_schema_head or [args.schema_head])
                ),
            },
            "backup_required": True,
            "migration_before_readiness": True,
            "preserve_named_volumes": True,
            "preserve_edge_sqlite": True,
        },
    }

    output = bundle_root / args.output
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
