#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

CANONICAL_DIR = Path("docs/adr")
INDEX_PATH = CANONICAL_DIR / "README.md"
LEGACY_0001_PATH = Path("docs/architecture/adr-0001-telemetry-ingestion.md")
CANONICAL_0001_PATH = CANONICAL_DIR / "0001-central-telemetry-ingestion.md"

FILENAME_RE = re.compile(r"^(?P<id>\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
HEADING_RE = re.compile(r"^#\s+ADR[- ](?P<id>\d{4})(?::|\s+[—-])", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+)\)")
ALLOWED_STATUSES = {"Proposed", "Accepted", "Deprecated", "Superseded"}


class AdrValidationError(ValueError):
    pass


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdrValidationError(f"cannot read {path}") from exc


def canonical_records(root: Path) -> dict[str, Path]:
    directory = root / CANONICAL_DIR
    if not directory.is_dir():
        raise AdrValidationError(f"canonical ADR directory is missing: {CANONICAL_DIR}")

    records: dict[str, Path] = {}
    heading_ids: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        filename_match = FILENAME_RE.fullmatch(path.name)
        if not filename_match:
            raise AdrValidationError(f"invalid canonical ADR filename: {path.relative_to(root)}")

        text = read_text(path)
        heading_match = HEADING_RE.search(text)
        if not heading_match:
            raise AdrValidationError(f"missing ADR heading identifier: {path.relative_to(root)}")

        filename_id = filename_match.group("id")
        heading_id = heading_match.group("id")
        if filename_id != heading_id:
            raise AdrValidationError(
                f"filename/heading identifier mismatch in {path.relative_to(root)}: "
                f"{filename_id} != {heading_id}"
            )
        heading_ids.append(heading_id)
        if heading_id in records:
            raise AdrValidationError(f"duplicate canonical ADR identifier: {heading_id}")
        records[heading_id] = path

        status = extract_status(text)
        if status not in ALLOWED_STATUSES:
            raise AdrValidationError(
                f"unsupported ADR status in {path.relative_to(root)}: {status or 'missing'}"
            )

    duplicates = [identifier for identifier, count in Counter(heading_ids).items() if count > 1]
    if duplicates:
        raise AdrValidationError(f"duplicate canonical ADR identifiers: {', '.join(duplicates)}")
    if not records:
        raise AdrValidationError("no canonical ADR records found")
    return records


def extract_status(text: str) -> str | None:
    bullet = re.search(
        r"^-\s*(?:\*\*)?Status(?::)?(?:\*\*)?:?\s*"
        r"(?P<status>Proposed|Accepted|Deprecated|Superseded)\b",
        text,
        re.MULTILINE,
    )
    if bullet:
        return bullet.group("status")

    section = re.search(
        r"^##\s+Status\s*$\s*(?P<status>Proposed|Accepted|Deprecated|Superseded)\b",
        text,
        re.MULTILINE,
    )
    return section.group("status") if section else None


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AdrValidationError(f"missing index section: {heading}")
    return match.group("body")


def table_rows(body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] in {"ID", "---"} or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


def registry_entries(root: Path) -> dict[str, Path]:
    index = root / INDEX_PATH
    text = read_text(index)
    rows = table_rows(section(text, "Registry"))
    entries: dict[str, Path] = {}
    for cells in rows:
        if len(cells) != 6:
            raise AdrValidationError(f"registry row must have six columns: {' | '.join(cells)}")
        identifier = cells[0]
        if not re.fullmatch(r"\d{4}", identifier):
            raise AdrValidationError(f"invalid registry identifier: {identifier}")
        if identifier in entries:
            raise AdrValidationError(f"duplicate registry identifier: {identifier}")
        links = list(MARKDOWN_LINK_RE.finditer(cells[5]))
        if len(links) != 1:
            raise AdrValidationError(f"registry {identifier} must contain one canonical link")
        target = links[0].group("target")
        entries[identifier] = (index.parent / target).resolve()
    return entries


def documented_gaps(root: Path) -> set[str]:
    text = read_text(root / INDEX_PATH)
    rows = table_rows(section(text, "Historical numbering gaps"))
    gaps: set[str] = set()
    for cells in rows:
        if len(cells) != 3:
            raise AdrValidationError(f"gap row must have three columns: {' | '.join(cells)}")
        identifier = cells[0]
        if not re.fullmatch(r"\d{4}", identifier):
            raise AdrValidationError(f"invalid gap identifier: {identifier}")
        if identifier in gaps:
            raise AdrValidationError(f"duplicate documented gap: {identifier}")
        if "Unassigned historical gap" not in cells[1]:
            raise AdrValidationError(f"unsupported gap classification for {identifier}")
        gaps.add(identifier)
    return gaps


def validate_links(root: Path, paths: list[Path]) -> None:
    for path in paths:
        text = read_text(path)
        for match in MARKDOWN_LINK_RE.finditer(text):
            target = match.group("target").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                raise AdrValidationError(
                    f"broken Markdown link in {path.relative_to(root)}: {match.group('target')}"
                )


def validate(root: Path) -> None:
    root = root.resolve()
    records = canonical_records(root)
    entries = registry_entries(root)

    if set(records) != set(entries):
        missing = sorted(set(records) - set(entries))
        unknown = sorted(set(entries) - set(records))
        raise AdrValidationError(
            f"registry/filesystem mismatch; missing={missing}, unknown={unknown}"
        )

    for identifier, target in entries.items():
        expected = records[identifier].resolve()
        if target != expected:
            raise AdrValidationError(
                f"registry target mismatch for {identifier}: "
                f"{target.relative_to(root)} != {expected.relative_to(root)}"
            )
        if not target.is_file():
            raise AdrValidationError(f"registry target is missing for {identifier}")

    numeric_ids = sorted(int(identifier) for identifier in records)
    expected_gaps = {
        f"{identifier:04d}"
        for identifier in range(numeric_ids[0], numeric_ids[-1] + 1)
        if f"{identifier:04d}" not in records
    }
    gaps = documented_gaps(root)
    if gaps != expected_gaps:
        raise AdrValidationError(
            f"historical gap mismatch; documented={sorted(gaps)}, expected={sorted(expected_gaps)}"
        )
    if gaps & set(records):
        raise AdrValidationError("documented gaps overlap published ADR identifiers")

    legacy = root / LEGACY_0001_PATH
    canonical_0001 = root / CANONICAL_0001_PATH
    if not legacy.is_file():
        raise AdrValidationError(f"legacy ADR-0001 path is missing: {LEGACY_0001_PATH}")
    if records.get("0001", Path()).resolve() != canonical_0001.resolve():
        raise AdrValidationError("ADR-0001 canonical target is not the governed path")
    legacy_text = read_text(legacy)
    expected_relative = "../adr/0001-central-telemetry-ingestion.md"
    if expected_relative not in legacy_text:
        raise AdrValidationError("legacy ADR-0001 file does not point to the canonical record")

    validate_links(root, [root / INDEX_PATH, legacy])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the NEXOLAB ADR registry")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    validate(args.root)
    print("ADR registry validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdrValidationError as exc:
        print(f"ADR registry validation failed: {exc}")
        raise SystemExit(1) from exc
