#!/usr/bin/env python3
"""Analyze a Copeland/Dixell XWEB library without executing vendor code."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

MAX_NESTED_ARCHIVE_DEPTH = 4
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_ITEMS = 1000
MAX_DIAGNOSTIC_ITEMS = 300

ADDRESS_KEYS = {
    "address",
    "addr",
    "register",
    "register_address",
    "registeraddress",
    "register_addr",
    "registeraddr",
    "reg",
    "reg_address",
    "regaddress",
    "reg_addr",
    "regaddr",
    "register_no",
    "register_number",
    "offset",
    "word",
    "word_address",
    "modbus_address",
    "modbusaddress",
    "modbus_addr",
    "modbusaddr",
    "modbus_register",
    "mb_address",
    "mb_addr",
    "mbaddr",
    "variable_address",
    "var_address",
    "memory_address",
    "parameter_address",
    "start_address",
    "read_address",
}
FUNCTION_KEYS = {
    "function",
    "function_code",
    "functioncode",
    "fc",
    "modbus_function",
    "modbusfunction",
    "read_function",
    "read_function_code",
    "read_fc",
}
NAME_KEYS = {
    "name",
    "label",
    "description",
    "desc",
    "text",
    "symbol",
    "parameter",
    "variable",
    "title",
    "caption",
    "mnemonic",
    "tag",
    "code",
    "short_name",
    "shortname",
}
SCALE_KEYS = {
    "scale",
    "scale_factor",
    "scalefactor",
    "multiplier",
    "factor",
    "gain",
    "resolution",
    "precision",
    "decimal",
    "decimals",
    "divisor",
}
UNIT_KEYS = {
    "unit",
    "units",
    "uom",
    "measure_unit",
    "measurement_unit",
    "engineering_unit",
    "unit_of_measure",
}
TYPE_KEYS = {
    "type",
    "data_type",
    "datatype",
    "format",
    "encoding",
    "value_type",
    "word_type",
    "signed",
}
DEFAULT_KEYWORDS = (
    "probe",
    "temperature",
    "temp",
    "sonda",
    "sensor",
    "channel",
    "input",
    "analog",
    "alarm",
)


@dataclass(frozen=True)
class Candidate:
    source_file: str
    document_type: str
    json_path: str
    score: int
    address: int | None
    function: int | None
    name: str | None
    scale: str | None
    unit: str | None
    data_type: str | None
    matched_keywords: list[str]
    scalar_fields: dict[str, Any]


@dataclass(frozen=True)
class KeywordHit:
    source_file: str
    document_type: str
    json_path: str
    value: str
    matched_keywords: list[str]


@dataclass(frozen=True)
class Document:
    path: Path
    source_file: str
    document_type: str
    size_bytes: int


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def parse_int_like(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        match = re.fullmatch(r"(?:4x|3x)?(\d+)", text, re.IGNORECASE)
        return int(match.group(1)) if match else None


def scalar_items(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in node.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def first_scalar(fields: Mapping[str, Any], accepted_keys: set[str]) -> Any:
    for key, value in fields.items():
        if normalize_key(key) in accepted_keys:
            return value
    return None


def combined_text(fields: Mapping[str, Any]) -> str:
    # Vendor schemas often place semantic meaning in a key and the numeric value
    # in the corresponding scalar. Include both sides in keyword matching.
    return " ".join(
        f"{key} {value}" for key, value in fields.items() if value is not None
    )


def matched_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    folded = text.casefold()
    return sorted({keyword for keyword in keywords if keyword.casefold() in folded})


def walk_json(node: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from walk_json(value, f"{path}/{escaped}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_json(value, f"{path}/{index}")


def walk_xml(root: ElementTree.Element) -> Iterator[tuple[str, dict[str, Any]]]:
    def visit(
        element: ElementTree.Element,
        path: str,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        fields: dict[str, Any] = {"xml_tag": element.tag}
        fields.update({str(key): value for key, value in element.attrib.items()})
        if element.text and element.text.strip():
            fields["text"] = element.text.strip()
        yield path, fields

        tag_counts: Counter[str] = Counter()
        for child in list(element):
            tag_counts[child.tag] += 1
            child_path = f"{path}/{child.tag}[{tag_counts[child.tag]}]"
            yield from visit(child, child_path)

    yield from visit(root, f"/{root.tag}[1]")


def candidate_from_mapping(
    source_file: str,
    document_type: str,
    json_path: str,
    node: Mapping[str, Any],
    keywords: tuple[str, ...],
) -> Candidate | None:
    fields = scalar_items(node)
    if not fields:
        return None

    address = parse_int_like(first_scalar(fields, ADDRESS_KEYS))
    function = parse_int_like(first_scalar(fields, FUNCTION_KEYS))
    name_value = first_scalar(fields, NAME_KEYS)
    scale_value = first_scalar(fields, SCALE_KEYS)
    unit_value = first_scalar(fields, UNIT_KEYS)
    type_value = first_scalar(fields, TYPE_KEYS)

    matches = matched_keywords(combined_text(fields), keywords)
    if address is None and not matches:
        return None

    score = 0
    if address is not None:
        score += 5
    if function is not None:
        score += 2
    if matches:
        score += min(8, len(matches) * 2)
    if scale_value is not None:
        score += 1
    if unit_value is not None:
        score += 1
    if type_value is not None:
        score += 1

    return Candidate(
        source_file=source_file,
        document_type=document_type,
        json_path=json_path,
        score=score,
        address=address,
        function=function,
        name=str(name_value) if name_value is not None else None,
        scale=str(scale_value) if scale_value is not None else None,
        unit=str(unit_value) if unit_value is not None else None,
        data_type=str(type_value) if type_value is not None else None,
        matched_keywords=matches,
        scalar_fields=fields,
    )


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError(f"Unsafe ZIP member path: {member.filename}") from exc
        package.extractall(destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_document_type(path: Path) -> str | None:
    suffix = path.suffix.casefold()
    if suffix in {".json", ".jsn"}:
        return "json"
    if suffix == ".xml":
        return "xml"
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        return None

    try:
        prefix = path.read_bytes()[:512]
    except OSError:
        return None

    compact = prefix.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    if compact.startswith((b"{", b"[")):
        return "json"
    if compact.startswith(b"<"):
        return "xml"
    return None


def discover_documents(
    source: Path,
    workspace: Path,
) -> tuple[list[Document], list[dict[str, Any]], list[str], int]:
    documents: list[Document] = []
    inventory: list[dict[str, Any]] = []
    warnings: list[str] = []
    archive_count = 0
    extraction_counter = 0

    def add_inventory(path_label: str, file_path: Path, kind: str, depth: int) -> None:
        if len(inventory) >= MAX_INVENTORY_ITEMS:
            return
        inventory.append(
            {
                "path": path_label,
                "size_bytes": file_path.stat().st_size if file_path.exists() else None,
                "suffix": file_path.suffix,
                "kind": kind,
                "depth": depth,
            }
        )

    def visit(file_path: Path, label: str, depth: int) -> None:
        nonlocal archive_count, extraction_counter
        if not file_path.is_file():
            return

        if zipfile.is_zipfile(file_path):
            archive_count += 1
            add_inventory(label, file_path, "zip", depth)
            if depth >= MAX_NESTED_ARCHIVE_DEPTH:
                warnings.append(f"Nested archive depth limit reached at {label}")
                return
            extraction_counter += 1
            destination = workspace / f"archive-{extraction_counter:04d}"
            destination.mkdir(parents=True, exist_ok=True)
            safe_extract_zip(file_path, destination)
            for child in sorted(destination.rglob("*")):
                if child.is_file():
                    relative = child.relative_to(destination).as_posix()
                    visit(child, f"{label}!/{relative}", depth + 1)
            return

        document_type = sniff_document_type(file_path)
        add_inventory(label, file_path, document_type or "other", depth)
        if document_type:
            documents.append(
                Document(
                    path=file_path,
                    source_file=label,
                    document_type=document_type,
                    size_bytes=file_path.stat().st_size,
                )
            )

    if source.is_dir():
        for child in sorted(source.rglob("*")):
            if child.is_file():
                visit(child, child.relative_to(source).as_posix(), 0)
    else:
        visit(source, source.name, 0)

    return documents, inventory, warnings, archive_count


def is_address_like_key(key: str) -> bool:
    normalized = normalize_key(key)
    return any(
        token in normalized for token in ("addr", "register", "modbus", "offset", "word")
    )


def analyze(
    source: Path,
    model: str,
    version: str,
    keywords: tuple[str, ...],
) -> dict[str, Any]:
    candidates: list[Candidate] = []
    keyword_hits: list[KeywordHit] = []
    parse_errors: list[dict[str, str]] = []
    key_counts: Counter[str] = Counter()
    unknown_address_like_fields: list[dict[str, Any]] = []
    parsed_document_count = 0

    with tempfile.TemporaryDirectory(prefix="nexolab-dixell-") as temp_dir:
        workspace = Path(temp_dir)
        documents, inventory, discovery_warnings, archive_count = discover_documents(
            source, workspace
        )

        for document in documents:
            try:
                if document.document_type == "json":
                    data = json.loads(document.path.read_bytes())
                    nodes: Iterator[tuple[str, Any]] = walk_json(data)
                elif document.document_type == "xml":
                    root = ElementTree.parse(document.path).getroot()
                    nodes = iter(walk_xml(root))
                else:
                    continue
                parsed_document_count += 1
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ElementTree.ParseError,
            ) as exc:
                parse_errors.append(
                    {
                        "source_file": document.source_file,
                        "document_type": document.document_type,
                        "error": str(exc),
                    }
                )
                continue

            for json_path, node in nodes:
                if isinstance(node, Mapping):
                    fields = scalar_items(node)
                    for key in node:
                        key_counts[normalize_key(str(key))] += 1

                    candidate = candidate_from_mapping(
                        document.source_file,
                        document.document_type,
                        json_path,
                        node,
                        keywords,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

                    key_matches = matched_keywords(
                        " ".join(map(str, node.keys())), keywords
                    )
                    value_matches = matched_keywords(combined_text(fields), keywords)
                    matches = sorted(set(key_matches + value_matches))
                    if matches:
                        keyword_hits.append(
                            KeywordHit(
                                source_file=document.source_file,
                                document_type=document.document_type,
                                json_path=json_path,
                                value=combined_text(fields)[:1000],
                                matched_keywords=matches,
                            )
                        )

                    if len(unknown_address_like_fields) < MAX_DIAGNOSTIC_ITEMS:
                        for key, value in fields.items():
                            normalized = normalize_key(key)
                            if (
                                normalized not in ADDRESS_KEYS
                                and is_address_like_key(key)
                                and parse_int_like(value) is not None
                            ):
                                unknown_address_like_fields.append(
                                    {
                                        "source_file": document.source_file,
                                        "document_type": document.document_type,
                                        "json_path": json_path,
                                        "key": key,
                                        "value": value,
                                    }
                                )
                elif isinstance(node, str):
                    matches = matched_keywords(node, keywords)
                    if matches:
                        keyword_hits.append(
                            KeywordHit(
                                source_file=document.source_file,
                                document_type=document.document_type,
                                json_path=json_path,
                                value=node[:1000],
                                matched_keywords=matches,
                            )
                        )

    candidates.sort(
        key=lambda item: (
            -item.score,
            item.address if item.address is not None else 1_000_000,
            item.source_file,
            item.json_path,
        )
    )
    keyword_hits.sort(
        key=lambda item: (item.source_file, item.document_type, item.json_path)
    )

    source_is_archive = source.is_file() and zipfile.is_zipfile(source)
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "nexolab-dixell-library-analyzer",
        "read_only": True,
        "source": {
            "path": str(source),
            "sha256": sha256_file(source) if source.is_file() else None,
            "model": model,
            "version": version,
        },
        "keywords": list(keywords),
        "statistics": {
            "candidate_count": len(candidates),
            "keyword_hit_count": len(keyword_hits),
            "parse_error_count": len(parse_errors),
            "document_count": len(documents),
            "parsed_document_count": parsed_document_count,
            "archive_count": archive_count,
            "nested_archive_count": max(0, archive_count - int(source_is_archive)),
            "inventory_item_count": len(inventory),
        },
        "candidates": [asdict(item) for item in candidates],
        "keyword_hits": [asdict(item) for item in keyword_hits],
        "parse_errors": parse_errors,
        "diagnostics": {
            "documents": [
                {
                    "source_file": document.source_file,
                    "document_type": document.document_type,
                    "size_bytes": document.size_bytes,
                }
                for document in documents[:MAX_DIAGNOSTIC_ITEMS]
            ],
            "inventory": inventory,
            "normalized_key_counts": [
                {"key": key, "count": count}
                for key, count in key_counts.most_common(MAX_DIAGNOSTIC_ITEMS)
            ],
            "unknown_address_like_fields": unknown_address_like_fields,
            "warnings": discovery_warnings,
        },
    }


def write_csv(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_file",
        "document_type",
        "json_path",
        "score",
        "address",
        "function",
        "name",
        "scale",
        "unit",
        "data_type",
        "matched_keywords",
        "scalar_fields_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in report["candidates"]:
            writer.writerow(
                {
                    **{key: item.get(key) for key in fieldnames[:-2]},
                    "matched_keywords": ",".join(item["matched_keywords"]),
                    "scalar_fields_json": json.dumps(
                        item["scalar_fields"], ensure_ascii=False, sort_keys=True
                    ),
                }
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a Copeland/Dixell XWEB library and surface probable "
            "Modbus register definitions. The tool never contacts hardware."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--model", default="XJP60D")
    parser.add_argument("--version", default="1.6")
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated case-insensitive keywords",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/vendor/dixell/xjp60d-v1.6/library-analysis.json"),
    )
    parser.add_argument("--csv-output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    if not source.exists():
        parser.error(f"Input does not exist: {source}")

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
        report = analyze(source, args.model, args.version, keywords)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_output = args.csv_output or args.output.with_suffix(".csv")
    write_csv(csv_output, report)

    stats = report["statistics"]
    print(f"JSON analysis: {args.output}")
    print(f"CSV candidates: {csv_output}")
    print(
        "Candidates: "
        f"{stats['candidate_count']}; keyword hits: {stats['keyword_hit_count']}; "
        f"documents: {stats['parsed_document_count']}/{stats['document_count']}; "
        f"archives: {stats['archive_count']}; parse errors: {stats['parse_error_count']}"
    )
    if stats["candidate_count"] == 0:
        print(
            "No register candidates were extracted. Review diagnostics.inventory, "
            "diagnostics.documents, and diagnostics.normalized_key_counts."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
