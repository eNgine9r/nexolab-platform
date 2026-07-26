from __future__ import annotations

import io
import posixpath
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from app.reports.domain import canonical_json_bytes, sha256_hex

REPORT_PRESENTATION_SCHEMA = "nexolab.report-presentation.v1"
REPORT_RENDERER_VERSION = "reports-renderer-v1"
_NORMALIZED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ReportPresentationError(RuntimeError):
    code = "report_presentation_error"


class ReportApprovalConflictError(ReportPresentationError):
    code = "report_approval_conflict"


class ReportApprovalStateError(ReportPresentationError):
    code = "report_approval_state_invalid"


class ReportApprovalState(StrEnum):
    GENERATED = "generated"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class ReportPresentationFormat(StrEnum):
    XLSX = "xlsx"
    PDF = "pdf"


@dataclass(frozen=True, slots=True)
class ReportVerificationPayload:
    report_id: str
    organization_id: str
    session_id: str
    report_version: int
    source_sha256: str
    manifest_sha256: str
    renderer_version: str = REPORT_RENDERER_VERSION

    def __post_init__(self) -> None:
        _required_text(self.report_id, "report_id", 36)
        _required_text(self.organization_id, "organization_id", 36)
        _required_text(self.session_id, "session_id", 36)
        if self.report_version < 1:
            raise ValueError("report_version must be positive")
        _validate_sha256(self.source_sha256, "source_sha256")
        _validate_sha256(self.manifest_sha256, "manifest_sha256")
        _required_text(self.renderer_version, "renderer_version", 64)

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema": REPORT_PRESENTATION_SCHEMA,
                "report": {
                    "id": self.report_id,
                    "organization_id": self.organization_id,
                    "session_id": self.session_id,
                    "version": self.report_version,
                    "source_sha256": self.source_sha256,
                    "manifest_sha256": self.manifest_sha256,
                },
                "renderer_version": self.renderer_version,
            }
        )

    @property
    def sha256(self) -> str:
        return sha256_hex(self.to_bytes())


@dataclass(frozen=True, slots=True)
class ReportApprovalSnapshot:
    report_id: str
    report_version: int
    source_sha256: str
    manifest_sha256: str
    state: ReportApprovalState = ReportApprovalState.GENERATED
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_reason: str | None = None
    approval_idempotency_key: str | None = None
    approval_command_sha256: str | None = None
    superseded_by_report_id: str | None = None
    superseded_at: datetime | None = None

    def __post_init__(self) -> None:
        _required_text(self.report_id, "report_id", 36)
        if self.report_version < 1:
            raise ValueError("report_version must be positive")
        _validate_sha256(self.source_sha256, "source_sha256")
        _validate_sha256(self.manifest_sha256, "manifest_sha256")
        if self.approved_at is not None:
            _utc(self.approved_at)
        if self.superseded_at is not None:
            _utc(self.superseded_at)
        if self.state is ReportApprovalState.GENERATED:
            if any(
                value is not None
                for value in (
                    self.approved_by,
                    self.approved_at,
                    self.approval_reason,
                    self.approval_idempotency_key,
                    self.approval_command_sha256,
                    self.superseded_by_report_id,
                    self.superseded_at,
                )
            ):
                raise ValueError("generated report cannot contain approval metadata")
        if self.state in {
            ReportApprovalState.APPROVED,
            ReportApprovalState.SUPERSEDED,
        }:
            _required_text(self.approved_by or "", "approved_by", 255)
            _required_text(self.approval_reason or "", "approval_reason", 1024)
            _required_text(
                self.approval_idempotency_key or "",
                "approval_idempotency_key",
                128,
            )
            _validate_sha256(
                self.approval_command_sha256 or "",
                "approval_command_sha256",
            )
            if self.approved_at is None:
                raise ValueError("approved report requires approved_at")
        if self.state is ReportApprovalState.SUPERSEDED:
            _required_text(
                self.superseded_by_report_id or "",
                "superseded_by_report_id",
                36,
            )
            if self.superseded_at is None:
                raise ValueError("superseded report requires superseded_at")


@dataclass(frozen=True, slots=True)
class ApproveReportCommand:
    idempotency_key: str
    actor_subject: str
    reason: str
    occurred_at: datetime
    expected_source_sha256: str
    expected_manifest_sha256: str

    def __post_init__(self) -> None:
        _required_text(self.idempotency_key, "idempotency_key", 128)
        _required_text(self.actor_subject, "actor_subject", 255)
        _required_text(self.reason, "reason", 1024)
        _utc(self.occurred_at)
        _validate_sha256(self.expected_source_sha256, "expected_source_sha256")
        _validate_sha256(
            self.expected_manifest_sha256,
            "expected_manifest_sha256",
        )

    @property
    def command_sha256(self) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {
                    "idempotency_key": self.idempotency_key,
                    "actor_subject": self.actor_subject,
                    "reason": self.reason,
                    "occurred_at": self.occurred_at,
                    "expected_source_sha256": self.expected_source_sha256,
                    "expected_manifest_sha256": self.expected_manifest_sha256,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    snapshot: ReportApprovalSnapshot
    replayed: bool


def approve_report(
    snapshot: ReportApprovalSnapshot,
    command: ApproveReportCommand,
) -> ApprovalResult:
    if command.expected_source_sha256 != snapshot.source_sha256:
        raise ReportApprovalConflictError(
            "report source digest does not match approval precondition"
        )
    if command.expected_manifest_sha256 != snapshot.manifest_sha256:
        raise ReportApprovalConflictError(
            "report manifest digest does not match approval precondition"
        )

    if snapshot.state is ReportApprovalState.APPROVED:
        if snapshot.approval_idempotency_key != command.idempotency_key:
            raise ReportApprovalStateError("report is already approved")
        if snapshot.approval_command_sha256 != command.command_sha256:
            raise ReportApprovalConflictError(
                "approval idempotency key was reused with a different command"
            )
        return ApprovalResult(snapshot=snapshot, replayed=True)

    if snapshot.state is not ReportApprovalState.GENERATED:
        raise ReportApprovalStateError(
            f"cannot approve report in state {snapshot.state.value!r}"
        )

    approved = replace(
        snapshot,
        state=ReportApprovalState.APPROVED,
        approved_by=command.actor_subject.strip(),
        approved_at=_utc(command.occurred_at),
        approval_reason=command.reason.strip(),
        approval_idempotency_key=command.idempotency_key.strip(),
        approval_command_sha256=command.command_sha256,
    )
    return ApprovalResult(snapshot=approved, replayed=False)


def supersede_report(
    snapshot: ReportApprovalSnapshot,
    *,
    superseded_by_report_id: str,
    occurred_at: datetime,
) -> ReportApprovalSnapshot:
    if snapshot.state is ReportApprovalState.SUPERSEDED:
        if snapshot.superseded_by_report_id == superseded_by_report_id:
            return snapshot
        raise ReportApprovalConflictError(
            "report was already superseded by another version"
        )
    if snapshot.state is not ReportApprovalState.APPROVED:
        raise ReportApprovalStateError("only an approved report can be superseded")
    successor_id = _required_text(
        superseded_by_report_id,
        "superseded_by_report_id",
        36,
    )
    if successor_id == snapshot.report_id:
        raise ValueError("report cannot supersede itself")
    return replace(
        snapshot,
        state=ReportApprovalState.SUPERSEDED,
        superseded_by_report_id=successor_id,
        superseded_at=_utc(occurred_at),
    )


def normalize_zip_archive(content: bytes) -> bytes:
    """Return stable ZIP bytes independent of entry order and timestamps.

    XLSX is a ZIP container. Renderer libraries usually embed current file
    timestamps, which makes byte-level hashes unstable. This normalization
    preserves exact entry bytes while sorting names and fixing metadata.
    """

    try:
        source = ZipFile(io.BytesIO(content), mode="r")
    except BadZipFile as error:
        raise ValueError("content is not a valid ZIP archive") from error

    with source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError("ZIP archive contains duplicate entry names")
        ordered = sorted(names)
        for name in ordered:
            _validate_zip_name(name)

        output = io.BytesIO()
        with ZipFile(
            output,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as target:
            target.comment = b""
            for name in ordered:
                source_info = source.getinfo(name)
                data = source.read(name)
                info = ZipInfo(filename=name, date_time=_NORMALIZED_ZIP_TIMESTAMP)
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (
                    (0o40755 if source_info.is_dir() else 0o100644) << 16
                )
                info.flag_bits = 0x800
                info.extra = b""
                info.comment = b""
                target.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
        return output.getvalue()


def _validate_zip_name(name: str) -> None:
    if not name or "\\" in name:
        raise ValueError("ZIP entry name is invalid")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../") or name.startswith("/"):
        raise ValueError("ZIP archive contains an unsafe entry path")


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _validate_sha256(value: str, field: str) -> None:
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    try:
        int(normalized, 16)
    except ValueError as error:
        raise ValueError(f"{field} must be a SHA-256 hex digest") from error


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)
