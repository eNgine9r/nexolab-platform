#!/usr/bin/env python3
"""NEXOLAB byte-identical archive deduplication by hard link (#1710).

Owner-run as root. Frees the space of duplicate archives inside one scan root
(for example a retired Commander workspace) WITHOUT removing any path: each
verified duplicate is atomically replaced by a hard link to a byte-identical
retained copy, so every deployment/recovery record that names the duplicate's
path still finds identical content. Retained copies are never modified.

    report:  nexolab-archive-dedupe.py --scan-root DIR [--keep-root DIR ...] --plan-out FILE
    apply:   nexolab-archive-dedupe.py --apply-plan FILE --plan-sha256 HEX

Rules: regular files only (never symlinks), archive/package suffixes only,
at least --min-bytes, same filesystem, equal size AND equal full SHA-256.
The retained copy is preferably outside the scan root (keep roots), otherwise
the oldest copy inside it. Apply refuses a plan whose SHA-256 differs, then
re-hashes both files immediately before linking and skips any entry that
changed. After linking it verifies the path's content hash again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.zst", ".tar.xz", ".zip", ".img", ".deb", ".dump", ".zst", ".gz", ".xz")
CHUNK = 4 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _is_archive(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _candidates(root: Path, device: int, min_bytes: int) -> list[Path]:
    found: list[Path] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not Path(directory, d).is_symlink()]
        for name in files:
            path = Path(directory, name)
            try:
                info = path.lstat()
            except OSError:
                continue
            if path.is_symlink() or not path.is_file() or info.st_dev != device or info.st_size < min_bytes:
                continue
            if _is_archive(path):
                found.append(path)
    return found


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def build_plan(scan_root: Path, keep_roots: list[Path], min_bytes: int) -> dict[str, object]:
    scan_root = scan_root.resolve()
    if not scan_root.is_dir() or scan_root.is_symlink():
        raise SystemExit(f"scan root is not a real directory: {scan_root}")
    device = scan_root.stat().st_dev
    roots = [scan_root] + [root.resolve() for root in keep_roots if root.resolve().is_dir()]
    files: dict[str, Path] = {}
    for root in roots:
        for path in _candidates(root, device, min_bytes):
            files[str(path)] = path
    by_size: dict[int, list[Path]] = {}
    for path in files.values():
        by_size.setdefault(path.lstat().st_size, []).append(path)
    entries = []
    for size, paths in sorted(by_size.items(), reverse=True):
        if len(paths) < 2 or not any(_inside(p, scan_root) for p in paths):
            continue
        by_hash: dict[str, list[Path]] = {}
        for path in paths:
            by_hash.setdefault(sha256(path), []).append(path)
        for digest, same in by_hash.items():
            inodes = {p.lstat().st_ino for p in same}
            if len(same) < 2 or len(inodes) < 2:
                continue
            outside = sorted((p for p in same if not _inside(p, scan_root)), key=lambda p: p.lstat().st_mtime)
            inside = sorted((p for p in same if _inside(p, scan_root)), key=lambda p: p.lstat().st_mtime)
            retained = outside[0] if outside else inside[0]
            for duplicate in inside:
                if duplicate == retained or duplicate.lstat().st_ino == retained.lstat().st_ino:
                    continue
                entries.append({"duplicate": str(duplicate), "retained": str(retained), "bytes": size, "sha256": digest})
    return {
        "schema_version": 1,
        "kind": "nexolab-archive-dedupe-plan",
        "created_at": datetime.now(UTC).isoformat(),
        "scan_root": str(scan_root),
        "entries": entries,
        "bytes": sum(entry["bytes"] for entry in entries),
    }


def apply_plan(path: Path, expected: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    data = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", expected or "") or hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit("REFUSED: plan SHA-256 does not match the approved value")
    plan = json.loads(data)
    if plan.get("kind") != "nexolab-archive-dedupe-plan":
        raise SystemExit("REFUSED: not an archive dedupe plan")
    scan_root = Path(plan["scan_root"])
    done, skipped = [], []
    for entry in plan["entries"]:
        duplicate, retained = Path(entry["duplicate"]), Path(entry["retained"])
        reason = None
        try:
            if not _inside(duplicate, scan_root):
                reason = "duplicate outside scan root"
            elif duplicate.is_symlink() or retained.is_symlink() or not duplicate.is_file() or not retained.is_file():
                reason = "not regular files any more"
            elif duplicate.lstat().st_dev != retained.lstat().st_dev:
                reason = "different filesystems"
            elif duplicate.lstat().st_ino == retained.lstat().st_ino:
                reason = "already linked"
            elif duplicate.lstat().st_size != entry["bytes"] or retained.lstat().st_size != entry["bytes"]:
                reason = "size changed"
            elif sha256(duplicate) != entry["sha256"] or sha256(retained) != entry["sha256"]:
                reason = "content changed"
        except OSError as error:
            reason = f"unreadable: {error.__class__.__name__}"
        if reason:
            skipped.append({**entry, "reason": reason})
            continue
        temporary = duplicate.with_name(f".{duplicate.name}.dedupe-tmp")
        os.link(retained, temporary)
        os.replace(temporary, duplicate)
        if sha256(duplicate) != entry["sha256"]:
            raise SystemExit(f"VERIFY FAILED after linking {duplicate}")
        done.append(entry)
    return done, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan-root")
    parser.add_argument("--keep-root", action="append", default=[])
    parser.add_argument("--min-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--plan-out")
    parser.add_argument("--apply-plan")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    if args.apply_plan:
        done, skipped = apply_plan(Path(args.apply_plan), args.plan_sha256 or "")
        for entry in done:
            print(f"linked: {entry['duplicate']} -> {entry['retained']} ({entry['bytes']} bytes)")
        for entry in skipped:
            print(f"skipped: {entry['duplicate']} ({entry['reason']})")
        print(json.dumps({"linked": len(done), "skipped": len(skipped), "bytes_freed": sum(e["bytes"] for e in done)}))
        return 0
    if not args.scan_root or not args.plan_out:
        parser.error("report mode needs --scan-root and --plan-out")
    plan = build_plan(Path(args.scan_root), [Path(p) for p in args.keep_root], args.min_bytes)
    text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    Path(args.plan_out).write_text(text, encoding="utf-8")
    for entry in plan["entries"]:
        print(f"duplicate: {entry['duplicate']} == {entry['retained']} ({entry['bytes']} bytes, sha256 {entry['sha256']})")
    print(json.dumps({"plan": args.plan_out, "plan_sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "entries": len(plan["entries"]), "bytes": plan["bytes"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
