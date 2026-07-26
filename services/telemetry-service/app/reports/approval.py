from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from app.reports.domain import sha256_hex


class ReportApprovalState(StrEnum):
    GENERATED = "generated"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class ReportApprovalDecision(StrEnum):
    APPROVE = "approve"
    REPLAY = "replay"
    SUPERSEDE = "supersede"


class ReportApprovalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ApprovalCommand:
    idempotency_key: str
    actor_subject: str
    reason: str
    expected_manifest_sha256: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise ReportApprovalError("approval_idempotency_key_required", "idempotency key is required")
        if not self.actor_subject.strip():
            raise ReportApprovalError("approval_actor_required", "verified actor subject is required")
        if not self.reason.strip():
            raise ReportApprovalError("approval_reason_required", "approval reason is required")
        _validate_sha256(self.expected_manifest_sha256)
        _require_aware(self.occurred_at)

    @property
    def command_sha256(self) -> str:
        payload = "\n".join(
            (
                self.idempotency_key,
                self.actor_subject,
                self.reason,
                self.expected_manifest_sha256,
                self.occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
            )
        ).encode("utf-8")
        return sha256_hex(payload)


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    state: ReportApprovalState = ReportApprovalState.GENERATED
    manifest_sha256: str = ""
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_reason: str | None = None
    approval_idempotency_key: str | None = None
    approval_command_sha256: str | None = None
    superseded_by_report_id: str | None = None
    superseded_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_sha256(self.manifest_sha256)
        if self.state is ReportApprovalState.APPROVED:
            if not all(
                (
                    self.approved_by,
                    self.approved_at,
                    self.approval_reason,
                    self.approval_idempotency_key,
                    self.approval_command_sha256,
                )
            ):
                raise ReportApprovalError(
                    "approved_report_incomplete",
                    "approved report requires immutable approval attribution",
                )
            _require_aware(self.approved_at)
            _validate_sha256(self.approval_command_sha256 or "")
        if self.state is ReportApprovalState.SUPERSEDED:
            if not self.superseded_by_report_id or self.superseded_at is None:
                raise ReportApprovalError(
                    "superseded_report_incomplete",
                    "superseded report requires replacement identity and timestamp",
                )
            _require_aware(self.superseded_at)


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    decision: ReportApprovalDecision
    snapshot: ApprovalSnapshot


def approve_report(snapshot: ApprovalSnapshot, command: ApprovalCommand) -> ApprovalResult:
    if command.expected_manifest_sha256 != snapshot.manifest_sha256:
        raise ReportApprovalError(
            "report_manifest_precondition_failed",
            "report manifest changed or does not match the approval request",
        )

    if snapshot.state is ReportApprovalState.SUPERSEDED:
        raise ReportApprovalError(
            "report_already_superseded",
            "superseded reports cannot be approved",
        )

    if snapshot.state is ReportApprovalState.APPROVED:
        if snapshot.approval_idempotency_key != command.idempotency_key:
            raise ReportApprovalError(
                "report_already_approved",
                "report was already approved by an immutable command",
            )
        if snapshot.approval_command_sha256 != command.command_sha256:
            raise ReportApprovalError(
                "approval_idempotency_conflict",
                "idempotency key was reused with a different approval command",
            )
        return ApprovalResult(ReportApprovalDecision.REPLAY, snapshot)

    approved = replace(
        snapshot,
        state=ReportApprovalState.APPROVED,
        approved_by=command.actor_subject,
        approved_at=command.occurred_at.astimezone(UTC),
        approval_reason=command.reason,
        approval_idempotency_key=command.idempotency_key,
        approval_command_sha256=command.command_sha256,
    )
    return ApprovalResult(ReportApprovalDecision.APPROVE, approved)


def supersede_report(
    snapshot: ApprovalSnapshot,
    *,
    replacement_report_id: str,
    occurred_at: datetime,
) -> ApprovalResult:
    if snapshot.state is not ReportApprovalState.APPROVED:
        raise ReportApprovalError(
            "report_not_approved",
            "only an approved report may be superseded",
        )
    if not replacement_report_id.strip():
        raise ReportApprovalError(
            "replacement_report_required",
            "replacement report identity is required",
        )
    _require_aware(occurred_at)
    superseded = replace(
        snapshot,
        state=ReportApprovalState.SUPERSEDED,
        superseded_by_report_id=replacement_report_id,
        superseded_at=occurred_at.astimezone(UTC),
    )
    return ApprovalResult(ReportApprovalDecision.SUPERSEDE, superseded)


def _validate_sha256(value: str) -> None:
    if len(value) != 64:
        raise ReportApprovalError("invalid_sha256", "sha256 must contain 64 hexadecimal characters")
    try:
        int(value, 16)
    except ValueError as error:
        raise ReportApprovalError("invalid_sha256", "sha256 must contain hexadecimal characters") from error


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReportApprovalError("timezone_required", "timestamps must be timezone-aware")
