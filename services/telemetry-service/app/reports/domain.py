from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID

REPORT_MANIFEST_SCHEMA = "nexolab.report-manifest.v1"
REPORT_GENERATOR_VERSION = "reports-domain-v1"

TELEMETRY_CSV_FIELDS = (
    "event_id",
    "captured_at",
    "node_id",
    "equipment_id",
    "channel_id",
    "metric",
    "value",
    "unit",
    "quality",
    "alarm",
    "source",
    "session_id",
    "stage_id",
    "binding_id",
    "config_snapshot_id",
)

ALERT_TRANSITION_CSV_FIELDS = (
    "alert_id",
    "transition_id",
    "rule_id",
    "rule_version_id",
    "event_type",
    "previous_state",
    "next_state",
    "actor_id",
    "actor_source",
    "reason",
    "occurred_at",
    "severity",
    "node_id",
    "equipment_id",
    "channel_id",
    "metric",
    "session_id",
    "stage_id",
    "binding_id",
)


@dataclass(frozen=True, slots=True)
class TelemetryEvidenceRow:
    event_id: str
    captured_at: datetime
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    value: float | None
    unit: str
    quality: str
    alarm: str | None
    source: str
    session_id: str
    stage_id: str | None
    binding_id: str
    config_snapshot_id: str


@dataclass(frozen=True, slots=True)
class AlertTransitionEvidenceRow:
    alert_id: str
    transition_id: str
    rule_id: str
    rule_version_id: str
    event_type: str
    previous_state: str | None
    next_state: str
    actor_id: str
    actor_source: str
    reason: str | None
    occurred_at: datetime
    severity: str
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    session_id: str | None
    stage_id: str | None
    binding_id: str | None


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    name: str
    media_type: str
    sha256: str
    size_bytes: int
    row_count: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("artifact name is required")
        if not self.media_type.strip():
            raise ValueError("artifact media_type is required")
        _validate_sha256(self.sha256)
        if self.size_bytes < 0:
            raise ValueError("artifact size_bytes must be nonnegative")
        if self.row_count is not None and self.row_count < 0:
            raise ValueError("artifact row_count must be nonnegative")

    @classmethod
    def from_bytes(
        cls,
        *,
        name: str,
        media_type: str,
        content: bytes,
        row_count: int | None = None,
    ) -> ArtifactDescriptor:
        return cls(
            name=name,
            media_type=media_type,
            sha256=sha256_hex(content),
            size_bytes=len(content),
            row_count=row_count,
        )


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    normalized = _normalize_json(value)
    return (
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def telemetry_csv_bytes(rows: Iterable[TelemetryEvidenceRow]) -> bytes:
    ordered = sorted(
        rows,
        key=lambda row: (_utc_datetime(row.captured_at), row.event_id),
    )
    return _csv_bytes(
        TELEMETRY_CSV_FIELDS,
        (
            {
                "event_id": row.event_id,
                "captured_at": row.captured_at,
                "node_id": row.node_id,
                "equipment_id": row.equipment_id,
                "channel_id": row.channel_id,
                "metric": row.metric,
                "value": row.value,
                "unit": row.unit,
                "quality": row.quality,
                "alarm": row.alarm,
                "source": row.source,
                "session_id": row.session_id,
                "stage_id": row.stage_id,
                "binding_id": row.binding_id,
                "config_snapshot_id": row.config_snapshot_id,
            }
            for row in ordered
        ),
    )


def alert_transitions_csv_bytes(
    rows: Iterable[AlertTransitionEvidenceRow],
) -> bytes:
    ordered = sorted(
        rows,
        key=lambda row: (
            _utc_datetime(row.occurred_at),
            row.alert_id,
            row.transition_id,
        ),
    )
    return _csv_bytes(
        ALERT_TRANSITION_CSV_FIELDS,
        (
            {
                "alert_id": row.alert_id,
                "transition_id": row.transition_id,
                "rule_id": row.rule_id,
                "rule_version_id": row.rule_version_id,
                "event_type": row.event_type,
                "previous_state": row.previous_state,
                "next_state": row.next_state,
                "actor_id": row.actor_id,
                "actor_source": row.actor_source,
                "reason": row.reason,
                "occurred_at": row.occurred_at,
                "severity": row.severity,
                "node_id": row.node_id,
                "equipment_id": row.equipment_id,
                "channel_id": row.channel_id,
                "metric": row.metric,
                "session_id": row.session_id,
                "stage_id": row.stage_id,
                "binding_id": row.binding_id,
            }
            for row in ordered
        ),
    )


def report_manifest_bytes(
    *,
    report_id: str,
    organization_id: str,
    session_id: str,
    report_version: int,
    source_sha256: str,
    generated_at: datetime,
    generated_by: str,
    artifacts: Iterable[ArtifactDescriptor],
    generator_version: str = REPORT_GENERATOR_VERSION,
) -> bytes:
    if report_version < 1:
        raise ValueError("report_version must be positive")
    _validate_sha256(source_sha256)
    if not report_id.strip():
        raise ValueError("report_id is required")
    if not organization_id.strip():
        raise ValueError("organization_id is required")
    if not session_id.strip():
        raise ValueError("session_id is required")
    if not generated_by.strip():
        raise ValueError("generated_by is required")
    if not generator_version.strip():
        raise ValueError("generator_version is required")

    ordered_artifacts = sorted(artifacts, key=lambda artifact: artifact.name)
    names = [artifact.name for artifact in ordered_artifacts]
    if len(names) != len(set(names)):
        raise ValueError("artifact names must be unique")

    return canonical_json_bytes(
        {
            "schema": REPORT_MANIFEST_SCHEMA,
            "report": {
                "id": report_id,
                "organization_id": organization_id,
                "session_id": session_id,
                "version": report_version,
                "source_sha256": source_sha256,
                "generated_at": generated_at,
                "generated_by": generated_by,
                "generator_version": generator_version,
            },
            "artifacts": [asdict(artifact) for artifact in ordered_artifacts],
        }
    )


def _csv_bytes(
    fieldnames: tuple[str, ...],
    rows: Iterable[Mapping[str, Any]],
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fieldnames,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        missing = set(fieldnames).difference(row)
        if missing:
            raise ValueError(f"CSV row is missing fields: {sorted(missing)}")
        writer.writerow({name: _csv_cell(row[name]) for name in fieldnames})
    return stream.getvalue().encode("utf-8")


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _isoformat_utc(value)
    if isinstance(value, Enum):
        return _csv_cell(value.value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("CSV floats must be finite")
        if value == 0:
            return "0"
        return format(value, ".15g")
    if isinstance(value, (str, int, UUID)):
        return str(value)
    raise TypeError(f"Unsupported CSV value type: {type(value).__name__}")


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON floats must be finite")
        return value
    if isinstance(value, datetime):
        return _isoformat_utc(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_json(asdict(value))
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            normalized[key] = _normalize_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


def _isoformat_utc(value: datetime) -> str:
    normalized = _utc_datetime(value)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


def _validate_sha256(value: str) -> None:
    if len(value) != 64:
        raise ValueError("sha256 must contain 64 hexadecimal characters")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError("sha256 must contain hexadecimal characters") from error
