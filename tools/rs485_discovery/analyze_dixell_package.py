#!/usr/bin/env python3
"""Recursively unpack Copeland/Dixell bundles, then run the library analyzer."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import analyze_dixell_library as library_analyzer

MAX_ARCHIVE_DEPTH = 5
MAX_ARCHIVE_MEMBERS = 10_000
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
GZIP_MAGIC = b"\x1f\x8b"


def _safe_target(destination: Path, member_name: str) -> Path:
    if not member_name or member_name.startswith(("/", "\\")):
        raise ValueError(f"Unsafe archive member path: {member_name!r}")
    target = (destination / member_name).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError as exc:
        raise ValueError(f"Unsafe archive member path: {member_name}") from exc
    return target


def extract_zip(archive: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    total_bytes = 0
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"ZIP has too many members: {len(members)}")

        for member in members:
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"ZIP symlinks are not allowed: {member.filename}")
            total_bytes += member.file_size
            if total_bytes > MAX_EXPANDED_BYTES:
                raise ValueError("Expanded ZIP exceeds the safety size limit")
            _safe_target(destination, member.filename)

        for member in members:
            target = _safe_target(destination, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def extract_tar(archive: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    total_bytes = 0
    with tarfile.open(archive, mode="r:*") as package:
        members = package.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"TAR has too many members: {len(members)}")

        for member in members:
            if not (member.isdir() or member.isfile()):
                raise ValueError(
                    f"TAR links and special files are not allowed: {member.name}"
                )
            total_bytes += member.size
            if total_bytes > MAX_EXPANDED_BYTES:
                raise ValueError("Expanded TAR exceeds the safety size limit")
            _safe_target(destination, member.name)

        for member in members:
            target = _safe_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = package.extractfile(member)
            if source is None:
                raise ValueError(f"Cannot read TAR member: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def is_gzip_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == GZIP_MAGIC
    except OSError:
        return False


def extract_gzip(archive: Path, destination: Path) -> list[Path]:
    """Expand one GZIP stream without assuming that its payload is a TAR."""
    lower_name = archive.name.casefold()
    output_name = archive.name[:-3] if lower_name.endswith(".gz") else f"{archive.name}.out"
    output_name = output_name or "gzip-payload"
    target = _safe_target(destination, output_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    try:
        with gzip.open(archive, "rb") as source, target.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_EXPANDED_BYTES:
                    raise ValueError("Expanded GZIP exceeds the safety size limit")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return [target]


def archive_kind(path: Path) -> str | None:
    if zipfile.is_zipfile(path):
        return "zip"
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except OSError:
        pass
    if is_gzip_file(path):
        return "gzip"
    return None


def expand_bundle(source: Path, workspace: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    extraction_counter = 0

    def expand(archive: Path, label: str, depth: int) -> None:
        nonlocal extraction_counter
        kind = archive_kind(archive)
        if kind is None:
            raise ValueError(f"Unsupported package format: {archive}")
        if depth > MAX_ARCHIVE_DEPTH:
            raise ValueError(f"Archive nesting exceeds {MAX_ARCHIVE_DEPTH}: {label}")

        extraction_counter += 1
        destination = workspace / f"archive-{extraction_counter:04d}"
        destination.mkdir(parents=True, exist_ok=True)
        if kind == "zip":
            files = extract_zip(archive, destination)
        elif kind == "tar":
            files = extract_tar(archive, destination)
        else:
            files = extract_gzip(archive, destination)

        manifest.append(
            {
                "source": label,
                "kind": kind,
                "depth": depth,
                "member_file_count": len(files),
            }
        )

        for child in sorted(files):
            child_kind = archive_kind(child)
            if child_kind is None:
                continue
            relative = child.relative_to(destination).as_posix()
            expand(child, f"{label}!/{relative}", depth + 1)
            # Keep only terminal payloads for the downstream JSON/XML analyzer.
            child.unlink()

    expand(source, source.name, 0)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively unpack ZIP/TAR/GZIP Copeland bundles and run the offline "
            "Dixell register-map analyzer. No hardware is contacted."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--model", default="XJP60D")
    parser.add_argument("--version", default="1.6")
    parser.add_argument(
        "--keywords",
        default=",".join(library_analyzer.DEFAULT_KEYWORDS),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "runtime/vendor/dixell/xjp60d-v1.6/library-analysis-v4.json"
        ),
    )
    parser.add_argument("--csv-output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    if not source.is_file():
        parser.error(f"Input package does not exist: {source}")

    keywords = tuple(
        dict.fromkeys(
            keyword.strip().casefold()
            for keyword in args.keywords.split(",")
            if keyword.strip()
        )
    )
    if not keywords:
        parser.error("At least one keyword is required")

    try:
        with tempfile.TemporaryDirectory(prefix="nexolab-dixell-package-") as temp_dir:
            workspace = Path(temp_dir)
            manifest = expand_bundle(source, workspace)
            report = library_analyzer.analyze(
                workspace,
                args.model,
                args.version,
                keywords,
            )
    except (
        OSError,
        ValueError,
        gzip.BadGzipFile,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    report["schema_version"] = 4
    report["tool"] = "nexolab-dixell-package-analyzer"
    report["source"] = {
        "path": str(source),
        "sha256": library_analyzer.sha256_file(source),
        "model": args.model,
        "version": args.version,
    }
    report["package_extraction"] = {
        "archive_count": len(manifest),
        "archives": manifest,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_output = args.csv_output or args.output.with_suffix(".csv")
    library_analyzer.write_csv(csv_output, report)

    stats = report["statistics"]
    print(f"JSON analysis: {args.output}")
    print(f"CSV candidates: {csv_output}")
    print(
        "Archives: "
        f"{len(manifest)}; documents: {stats['document_count']}; "
        f"parsed: {stats['parsed_document_count']}; "
        f"candidates: {stats['candidate_count']}; "
        f"keyword hits: {stats['keyword_hit_count']}; "
        f"parse errors: {stats['parse_error_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
