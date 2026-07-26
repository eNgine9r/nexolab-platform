from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from app.reports.presentation_domain import (
    ApproveReportCommand,
    ReportApprovalConflictError,
    ReportApprovalSnapshot,
    ReportApprovalState,
    ReportApprovalStateError,
    ReportVerificationPayload,
    approve_report,
    normalize_zip_archive,
    supersede_report,
)


SOURCE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
APPROVED_AT = datetime(2026, 7, 26, 16, 30, tzinfo=UTC)


def snapshot() -> ReportApprovalSnapshot:
    return ReportApprovalSnapshot(
        report_id="10000000-0000-0000-0000-000000000001",
        report_version=1,
        source_sha256=SOURCE_SHA,
        manifest_sha256=MANIFEST_SHA,
    )


def command(**overrides: object) -> ApproveReportCommand:
    values: dict[str, object] = {
        "idempotency_key": "approve-report-1",
        "actor_subject": "laboratory-manager-1",
        "reason": "Evidence and conclusions reviewed",
        "occurred_at": APPROVED_AT,
        "expected_source_sha256": SOURCE_SHA,
        "expected_manifest_sha256": MANIFEST_SHA,
    }
    values.update(overrides)
    return ApproveReportCommand(**values)  # type: ignore[arg-type]


def build_zip(
    entries: list[tuple[str, bytes, tuple[int, int, int, int, int, int]]],
) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content, timestamp in entries:
            info = ZipInfo(name, timestamp)
            info.compress_type = ZIP_DEFLATED
            info.extra = b"\x01\x00\x04\x00meta"
            info.comment = b"comment"
            archive.writestr(info, content)
    return output.getvalue()


def test_verification_payload_is_canonical_and_hashable() -> None:
    payload = ReportVerificationPayload(
        report_id="10000000-0000-0000-0000-000000000001",
        organization_id="20000000-0000-0000-0000-000000000001",
        session_id="30000000-0000-0000-0000-000000000001",
        report_version=2,
        source_sha256=SOURCE_SHA,
        manifest_sha256=MANIFEST_SHA,
    )

    assert payload.to_bytes() == (
        b'{"renderer_version":"reports-renderer-v1","report":'
        b'{"id":"10000000-0000-0000-0000-000000000001",'
        b'"manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        b'"organization_id":"20000000-0000-0000-0000-000000000001",'
        b'"session_id":"30000000-0000-0000-0000-000000000001",'
        b'"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"version":2},"schema":"nexolab.report-presentation.v1"}\n'
    )
    assert len(payload.sha256) == 64


def test_approval_is_idempotent_and_preserves_verified_preconditions() -> None:
    original = snapshot()
    approved = approve_report(original, command())

    assert approved.replayed is False
    assert approved.snapshot.state is ReportApprovalState.APPROVED
    assert approved.snapshot.approved_by == "laboratory-manager-1"
    assert approved.snapshot.approved_at == APPROVED_AT
    assert approved.snapshot.approval_reason == "Evidence and conclusions reviewed"
    assert original.state is ReportApprovalState.GENERATED

    replay = approve_report(approved.snapshot, command())
    assert replay.replayed is True
    assert replay.snapshot is approved.snapshot


def test_approval_rejects_digest_change_and_conflicting_key_reuse() -> None:
    with pytest.raises(ReportApprovalConflictError, match="source digest"):
        approve_report(snapshot(), command(expected_source_sha256="c" * 64))

    approved = approve_report(snapshot(), command()).snapshot
    with pytest.raises(ReportApprovalConflictError, match="different command"):
        approve_report(
            approved,
            command(reason="Changed reason under the same key"),
        )
    with pytest.raises(ReportApprovalStateError, match="already approved"):
        approve_report(
            approved,
            command(idempotency_key="approve-report-2"),
        )


def test_only_approved_report_can_be_superseded_idempotently() -> None:
    with pytest.raises(ReportApprovalStateError, match="only an approved"):
        supersede_report(
            snapshot(),
            superseded_by_report_id="10000000-0000-0000-0000-000000000002",
            occurred_at=APPROVED_AT + timedelta(minutes=5),
        )

    approved = approve_report(snapshot(), command()).snapshot
    superseded = supersede_report(
        approved,
        superseded_by_report_id="10000000-0000-0000-0000-000000000002",
        occurred_at=APPROVED_AT + timedelta(minutes=5),
    )
    assert superseded.state is ReportApprovalState.SUPERSEDED
    assert superseded.superseded_by_report_id.endswith("0002")
    assert (
        supersede_report(
            superseded,
            superseded_by_report_id="10000000-0000-0000-0000-000000000002",
            occurred_at=APPROVED_AT + timedelta(minutes=10),
        )
        is superseded
    )


def test_zip_normalization_removes_order_timestamp_and_metadata_variance() -> None:
    first = build_zip(
        [
            ("xl/workbook.xml", b"<workbook/>", (2026, 7, 26, 16, 0, 0)),
            ("[Content_Types].xml", b"<types/>", (2026, 7, 26, 16, 0, 2)),
        ]
    )
    second = build_zip(
        [
            ("[Content_Types].xml", b"<types/>", (2025, 1, 1, 1, 2, 4)),
            ("xl/workbook.xml", b"<workbook/>", (2024, 2, 2, 2, 4, 6)),
        ]
    )

    normalized_first = normalize_zip_archive(first)
    normalized_second = normalize_zip_archive(second)
    assert normalized_first == normalized_second

    with ZipFile(io.BytesIO(normalized_first)) as archive:
        assert archive.namelist() == ["[Content_Types].xml", "xl/workbook.xml"]
        assert all(
            item.date_time == (1980, 1, 1, 0, 0, 0)
            for item in archive.infolist()
        )
        assert all(item.extra == b"" and item.comment == b"" for item in archive.infolist())


def test_zip_normalization_rejects_invalid_or_unsafe_archives() -> None:
    with pytest.raises(ValueError, match="valid ZIP"):
        normalize_zip_archive(b"not-a-zip")

    unsafe = build_zip(
        [("../secret.txt", b"secret", (2026, 7, 26, 16, 0, 0))]
    )
    with pytest.raises(ValueError, match="unsafe"):
        normalize_zip_archive(unsafe)


def test_naive_approval_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        command(occurred_at=datetime(2026, 7, 26, 16, 30))
