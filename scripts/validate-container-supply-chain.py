#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

IMAGE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IMAGE_NAME = re.compile(r"^ghcr\.io/[a-z0-9-]+/[a-z0-9-]+$")
CVE_ID = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+:-]*$")
SUPPORTED_PLATFORMS = {"linux/amd64", "linux/arm64"}
MAX_EXCEPTION_LIFETIME_DAYS = 45


class ValidationFailure(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"cannot read valid JSON from {path}") from exc
    if not isinstance(payload, dict):
        raise ValidationFailure(f"{path} must contain a JSON object")
    return payload


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailure(f"{label} must be a non-empty string")
    return value.strip()


def validate_inventory(path: Path, root: Path) -> None:
    payload = load_json(path)
    if payload.get("schema_version") != 1:
        raise ValidationFailure("container inventory schema_version must equal 1")
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        raise ValidationFailure("container inventory must contain images")

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, item in enumerate(images):
        label = f"images[{index}]"
        if not isinstance(item, dict):
            raise ValidationFailure(f"{label} must be an object")
        image_id = require_string(item.get("id"), f"{label}.id")
        image_name = require_string(item.get("image"), f"{label}.image")
        context = require_string(item.get("context"), f"{label}.context")
        dockerfile = require_string(item.get("dockerfile"), f"{label}.dockerfile")
        platforms = item.get("platforms")

        if not IMAGE_ID.fullmatch(image_id):
            raise ValidationFailure(f"{label}.id has invalid format")
        if not IMAGE_NAME.fullmatch(image_name):
            raise ValidationFailure(f"{label}.image must be an immutable GHCR repository name")
        if image_id in seen_ids or image_name in seen_names:
            raise ValidationFailure(f"duplicate image inventory entry: {image_id}")
        seen_ids.add(image_id)
        seen_names.add(image_name)

        context_path = (root / context).resolve()
        dockerfile_path = (root / dockerfile).resolve()
        if root.resolve() not in context_path.parents and context_path != root.resolve():
            raise ValidationFailure(f"{label}.context escapes repository root")
        if root.resolve() not in dockerfile_path.parents:
            raise ValidationFailure(f"{label}.dockerfile escapes repository root")
        if not context_path.is_dir():
            raise ValidationFailure(f"{label}.context does not exist: {context}")
        if not dockerfile_path.is_file():
            raise ValidationFailure(f"{label}.dockerfile does not exist: {dockerfile}")
        if context_path not in dockerfile_path.parents:
            raise ValidationFailure(f"{label}.dockerfile must be inside its build context")

        if not isinstance(platforms, list) or not platforms:
            raise ValidationFailure(f"{label}.platforms must be a non-empty list")
        normalized = set(platforms)
        if len(normalized) != len(platforms):
            raise ValidationFailure(f"{label}.platforms contains duplicates")
        if not normalized.issubset(SUPPORTED_PLATFORMS):
            raise ValidationFailure(f"{label}.platforms contains unsupported values")


def validate_exceptions(path: Path, today: date) -> None:
    payload = load_json(path)
    if payload.get("schema_version") != 1:
        raise ValidationFailure("vulnerability exceptions schema_version must equal 1")
    entries = payload.get("exceptions")
    if not isinstance(entries, list):
        raise ValidationFailure("exceptions must be a list")

    seen: set[tuple[str, str, str]] = set()
    latest_allowed_expiry = today + timedelta(days=MAX_EXCEPTION_LIFETIME_DAYS)
    for index, item in enumerate(entries):
        label = f"exceptions[{index}]"
        if not isinstance(item, dict):
            raise ValidationFailure(f"{label} must be an object")
        image_id = require_string(item.get("image_id"), f"{label}.image_id")
        package = require_string(item.get("package"), f"{label}.package")
        vulnerability = require_string(item.get("vulnerability"), f"{label}.vulnerability")
        reason = require_string(item.get("reason"), f"{label}.reason")
        owner = require_string(item.get("owner"), f"{label}.owner")
        expires_on = require_string(item.get("expires_on"), f"{label}.expires_on")

        if "*" in image_id or "*" in package or "*" in vulnerability:
            raise ValidationFailure(f"{label} may not use wildcard exceptions")
        if not IMAGE_ID.fullmatch(image_id):
            raise ValidationFailure(f"{label}.image_id has invalid format")
        if not PACKAGE.fullmatch(package):
            raise ValidationFailure(f"{label}.package has invalid format")
        if not CVE_ID.fullmatch(vulnerability):
            raise ValidationFailure(f"{label}.vulnerability must be an exact CVE identifier")
        if len(reason) < 20:
            raise ValidationFailure(f"{label}.reason must document a specific risk decision")
        if len(owner) < 3:
            raise ValidationFailure(f"{label}.owner is too short")
        try:
            expiry = date.fromisoformat(expires_on)
        except ValueError as exc:
            raise ValidationFailure(f"{label}.expires_on must use YYYY-MM-DD") from exc
        if expiry < today:
            raise ValidationFailure(f"{label} expired on {expires_on}")
        if expiry > latest_allowed_expiry:
            raise ValidationFailure(
                f"{label}.expires_on must be within "
                f"{MAX_EXCEPTION_LIFETIME_DAYS} days of the validation date"
            )

        key = (image_id, package, vulnerability)
        if key in seen:
            raise ValidationFailure(f"duplicate vulnerability exception: {key}")
        seen.add(key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--inventory", type=Path, default=Path("security/container-images.json"))
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=Path("security/vulnerability-exceptions.json"),
    )
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    root = args.root.resolve()
    validate_inventory(root / args.inventory, root)
    validate_exceptions(root / args.exceptions, args.today)
    print("Container supply-chain policy validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationFailure as exc:
        print(f"Container supply-chain policy validation failed: {exc}")
        raise SystemExit(1) from exc
