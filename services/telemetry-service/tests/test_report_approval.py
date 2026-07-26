from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.reports.approval import (
    ApprovalCommand,
    ApprovalSnapshot,
    ReportApprovalDecision,
    ReportApprovalError,
    ReportApprovalState,
    approve_report,
    supersede_report,
)


MANIFEST_SHA = "a" * 64


def command(**overrides: object) -> ApprovalCommand:
    values: dict[str, object] = {
        "idempotency_key": "approve-report-v1",
        "actor_subject": "manager@example.test",
        "reason": "Reviewed evidence and approved protocol",
        "expected_manifest_sha256": MANIFEST_SHA,
        "occurred_at": datetime(2026, 7, 26, 18, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return ApprovalCommand(**values)  # type: ignore[arg-type]


def test_generated_report_is_approved_with_verified_attribution() -> None:
    result = approve_report(
        ApprovalSnapshot(manifest_sha256=MANIFEST_SHA),
        command(),
    )

    assert result.decision is ReportApprovalDecision.APPROVE
    assert result.snapshot.state is ReportApprovalState.APPROVED
    assert result.snapshot.approved_by == "manager@example.test"
    assert result.snapshot.approval_reason == "Reviewed evidence and approved protocol"
    assert result.snapshot.approval_command_sha256 == command().command_sha256


def test_identical_approval_command_replays_without_mutation() -> None:
    first = approve_report(ApprovalSnapshot(manifest_sha256=MANIFEST_SHA), command())
    replay = approve_report(first.snapshot, command())

    assert replay.decision is ReportApprovalDecision.REPLAY
    assert replay.snapshot is first.snapshot


def test_idempotency_key_cannot_be_reused_with_different_reason() -> None:
    first = approve_report(ApprovalSnapshot(manifest_sha256=MANIFEST_SHA), command())

    with pytest.raises(ReportApprovalError) as captured:
        approve_report(first.snapshot, command(reason="Different approval reasoning"))

    assert captured.value.code == "approval_idempotency_conflict"


def test_manifest_precondition_fails_closed() -> None:
    with pytest.raises(ReportApprovalError) as captured:
        approve_report(
            ApprovalSnapshot(manifest_sha256=MANIFEST_SHA),
            command(expected_manifest_sha256="b" * 64),
        )

    assert captured.value.code == "report_manifest_precondition_failed"


def test_second_approval_command_is_rejected() -> None:
    first = approve_report(ApprovalSnapshot(manifest_sha256=MANIFEST_SHA), command())

    with pytest.raises(ReportApprovalError) as captured:
        approve_report(first.snapshot, command(idempotency_key="approve-report-again"))

    assert captured.value.code == "report_already_approved"


def test_approved_report_can_be_superseded_without_losing_approval() -> None:
    approved = approve_report(ApprovalSnapshot(manifest_sha256=MANIFEST_SHA), command())
    occurred_at = command().occurred_at + timedelta(hours=1)
    result = supersede_report(
        approved.snapshot,
        replacement_report_id="report-version-2",
        occurred_at=occurred_at,
    )

    assert result.decision is ReportApprovalDecision.SUPERSEDE
    assert result.snapshot.state is ReportApprovalState.SUPERSEDED
    assert result.snapshot.approved_by == "manager@example.test"
    assert result.snapshot.superseded_by_report_id == "report-version-2"
    assert result.snapshot.superseded_at == occurred_at


def test_generated_report_cannot_be_superseded() -> None:
    with pytest.raises(ReportApprovalError) as captured:
        supersede_report(
            ApprovalSnapshot(manifest_sha256=MANIFEST_SHA),
            replacement_report_id="report-version-2",
            occurred_at=command().occurred_at,
        )

    assert captured.value.code == "report_not_approved"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("idempotency_key", "", "approval_idempotency_key_required"),
        ("actor_subject", "", "approval_actor_required"),
        ("reason", "", "approval_reason_required"),
        ("expected_manifest_sha256", "invalid", "invalid_sha256"),
        ("occurred_at", datetime(2026, 7, 26, 18, 0), "timezone_required"),
    ],
)
def test_invalid_approval_commands_are_rejected(field: str, value: object, code: str) -> None:
    with pytest.raises(ReportApprovalError) as captured:
        command(**{field: value})

    assert captured.value.code == code
