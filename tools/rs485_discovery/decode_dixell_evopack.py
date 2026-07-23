#!/usr/bin/env python3
"""Decode Copeland/Dixell evopack ZIP members without executing vendor code."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KEY_WIDTH = 20
XOR_CONSTANT = 0xA1
MAX_MEMBERS = 10_000
MAX_TOTAL_BYTES = 256 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_member_key(member_name: str) -> bytes:
    """Derive the 20-byte evopack key from the member basename.

    Copeland evopack members use the first 20 basename bytes, NUL padded,
    XORed with 0xA1. The resulting key repeats across the member payload.
    """

    basename = Path(member_name).name.encode("utf-8")
    material = basename[:KEY_WIDTH].ljust(KEY_WIDTH, b"\x00")
    return bytes(byte ^ XOR_CONSTANT for byte in material)


def decode_member(member_name: str, payload: bytes) -> bytes:
    key = derive_member_key(member_name)
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(payload))


def detect_kind(payload: bytes) -> str:
    compact = payload.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    if payload.startswith(b"\x1f\x8b"):
        return "gzip"
    if payload.startswith(b"PK\x03\x04"):
        return "zip"
    if len(payload) >= 262 and payload[257:262] == b"ustar":
        return "tar"
    if compact.startswith((b"{", b"[")):
        return "json"
    if compact.startswith(b"<"):
        return "xml"
    if compact.startswith(b"#!"):
        return "script"
    return "opaque"


def safe_target(output_dir: Path, member_name: str) -> Path:
    if not member_name or member_name.startswith(("/", "\\")):
        raise ValueError(f"Unsafe ZIP member path: {member_name!r}")
    target = (output_dir / member_name).resolve()
    try:
        target.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Unsafe ZIP member path: {member_name}") from exc
    return target


def decode_archive(source: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    members_report: list[dict[str, Any]] = []
    total_bytes = 0

    with zipfile.ZipFile(source) as package:
        members = package.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError(f"ZIP has too many members: {len(members)}")

        for member in members:
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"ZIP symlinks are not allowed: {member.filename}")
            if member.is_dir():
                safe_target(output_dir, member.filename).mkdir(parents=True, exist_ok=True)
                continue

            total_bytes += member.file_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("ZIP payload exceeds the safety size limit")

            encoded = package.read(member)
            decoded = decode_member(member.filename, encoded)
            target = safe_target(output_dir, member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(decoded)

            members_report.append(
                {
                    "name": member.filename,
                    "encoded_size": len(encoded),
                    "encoded_sha256": sha256_bytes(encoded),
                    "decoded_size": len(decoded),
                    "decoded_sha256": sha256_bytes(decoded),
                    "decoded_kind": detect_kind(decoded),
                    "output": str(target),
                }
            )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "nexolab-dixell-evopack-decoder",
        "read_only": True,
        "vendor_code_executed": False,
        "source": {
            "path": str(source),
            "sha256": sha256_bytes(source.read_bytes()),
        },
        "key_derivation": {
            "basename_bytes": KEY_WIDTH,
            "nul_padded": True,
            "xor_constant": f"0x{XOR_CONSTANT:02X}",
            "repeating_key": True,
        },
        "members": members_report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Decode Copeland/Dixell evopack ZIP members offline. "
            "The tool never executes decoded scripts or contacts hardware."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    manifest_path = (
        args.manifest.expanduser().resolve()
        if args.manifest
        else output_dir / "decode-manifest.json"
    )

    if not source.is_file():
        parser.error(f"Input ZIP does not exist: {source}")

    try:
        report = decode_archive(source, output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Decoded directory: {output_dir}")
    print(f"Manifest: {manifest_path}")
    for member in report["members"]:
        print(
            f"  {member['name']}: {member['decoded_kind']} "
            f"({member['decoded_size']} bytes)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
