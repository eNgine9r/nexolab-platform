#!/usr/bin/env python3
"""Analyze a Copeland/Dixell XWEB JSON library without executing vendor code."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ADDRESS_KEYS = {
    "address",
    "addr",
    "register",
    "register_address",
    "registeraddress",
    "reg",
    "offset",
    "word",
    "modbus_address",
    "modbusaddress",
    "modbus_register",
}
FUNCTION_KEYS = {
    "function",
    "function_code",
    "functioncode",
    "fc",
    "modbus_function",
    "modbusfunction",
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
    "short_name",
    "shortname",
}
SCALE_KEYS = {
    "scale",
    "multiplier",
    "factor",
    "resolution",
    "decimal",
    "decimals",
    "divisor",
}
UNIT_KEYS = {"unit", "uom", "measure_unit", "measurement_unit", "engineering_unit"}
TYPE_KEYS = {"type", "data_type", "datatype", "format", "encoding", "value_type"}
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
    json_path: str
    value: str
    matched_keywords: list[str]


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
    return " ".join(str(value) for value in fields.values() if value is not None)


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


def candidate_from_mapping(
    source_file: str,
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
        score += min(6, len(matches) * 2)
    if scale_value is not None:
        score += 1
    if unit_value is not None:
        score += 1
    if type_value is not None:
        score += 1

    return Candidate(
        source_file=source_file,
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


def discover_json_files(source: Path, extraction_root: Path) -> list[Path]:
    if source.is_dir():
        return sorted(source.rglob("*.json"))
    if source.suffix.casefold() == ".json":
        return [source]
    if zipfile.is_zipfile(source):
        safe_extract_zip(source, extraction_root)
        return sorted(extraction_root.rglob("*.json"))
    raise ValueError("Input must be a JSON file, directory, or ZIP archive")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze(
    source: Path,
    model: str,
    version: str,
    keywords: tuple[str, ...],
) -> dict[str, Any]:
    candidates: list[Candidate] = []
    keyword_hits: list[KeywordHit] = []
    parse_errors: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="nexolab-dixell-") as temp_dir:
        extraction_root = Path(temp_dir)
        json_files = discover_json_files(source, extraction_root)

        for json_file in json_files:
            relative_name = (
                json_file.name
                if source.is_file() and source.suffix.casefold() == ".json"
                else str(
                    json_file.relative_to(
                        extraction_root if zipfile.is_zipfile(source) else source
                    )
                )
            )
            try:
                data = json.loads(json_file.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                parse_errors.append({"source_file": relative_name, "error": str(exc)})
                continue

            for json_path, node in walk_json(data):
                if isinstance(node, Mapping):
                    candidate = candidate_from_mapping(
                        relative_name,
                        json_path,
                        node,
                        keywords,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
                elif isinstance(node, str):
                    matches = matched_keywords(node, keywords)
                    if matches:
                        keyword_hits.append(
                            KeywordHit(
                                source_file=relative_name,
                                json_path=json_path,
                                value=node,
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
    keyword_hits.sort(key=lambda item: (item.source_file, item.json_path))

    return {
        "schema_version": 1,
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
        },
        "candidates": [asdict(item) for item in candidates],
        "keyword_hits": [asdict(item) for item in keyword_hits],
        "parse_errors": parse_errors,
    }


def write_csv(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_file",
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
            "Inspect a Copeland/Dixell XWEB JSON library and surface probable "
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
        f"parse errors: {stats['parse_error_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
