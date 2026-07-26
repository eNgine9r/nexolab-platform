from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.reports.domain import (
    AlertTransitionEvidenceRow,
    ArtifactDescriptor,
    TelemetryEvidenceRow,
    alert_transitions_csv_bytes,
    canonical_json_bytes,
    report_manifest_bytes,
    sha256_hex,
    telemetry_csv_bytes,
)


def telemetry_row(
    *,
    event_id: str,
    seconds: int,
    value: float | None,
) -> TelemetryEvidenceRow:
    return TelemetryEvidenceRow(
        event_id=event_id,
        captured_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
        + timedelta(seconds=seconds),
        node_id="edge-01",
        equipment_id="K106",
        channel_id="106-03",
        metric="temperature.probe",
        value=value,
        unit="degC",
        quality="valid",
        alarm=None,
        source="reports-test",
        session_id="session-1",
        stage_id="stage-1",
        binding_id="binding-1",
        config_snapshot_id="snapshot-1",
    )


def alert_row(
    *,
    transition_id: str,
    seconds: int,
    actor_id: str,
) -> AlertTransitionEvidenceRow:
    return AlertTransitionEvidenceRow(
        alert_id="alert-1",
        transition_id=transition_id,
        rule_id="rule-1",
        rule_version_id="rule-version-1",
        event_type="alert_acknowledged",
        previous_state="active",
        next_state="acknowledged",
        actor_id=actor_id,
        actor_source="verified-jwt",
        reason="Operator inspected equipment",
        occurred_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
        + timedelta(seconds=seconds),
        severity="critical",
        node_id="edge-01",
        equipment_id="K106",
        channel_id="106-03",
        metric="temperature.probe",
        session_id="session-1",
        stage_id="stage-1",
        binding_id="binding-1",
    )


def test_canonical_json_is_key_order_independent_and_utc_normalized() -> None:
    timestamp = datetime(2026, 7, 26, 15, 0, tzinfo=UTC)
    left = canonical_json_bytes({"b": 2, "a": {"timestamp": timestamp}})
    right = canonical_json_bytes({"a": {"timestamp": timestamp}, "b": 2})

    assert left == right
    assert left.endswith(b"\n")
    assert json.loads(left) == {
        "a": {"timestamp": "2026-07-26T15:00:00.000000Z"},
        "b": 2,
    }


def test_telemetry_csv_is_byte_stable_and_sorted_by_capture_time() -> None:
    later = telemetry_row(event_id="event-2", seconds=2, value=9.4)
    earlier = telemetry_row(event_id="event-1", seconds=1, value=8.7)

    first = telemetry_csv_bytes([later, earlier])
    second = telemetry_csv_bytes([earlier, later])

    assert first == second
    lines = first.decode("utf-8").splitlines()
    assert lines[0].startswith("event_id,captured_at,node_id")
    assert lines[1].startswith("event-1,2026-07-26T12:00:01.000000Z")
    assert lines[2].startswith("event-2,2026-07-26T12:00:02.000000Z")


def test_alert_transition_csv_preserves_verified_actor_and_order() -> None:
    later = alert_row(transition_id="transition-2", seconds=2, actor_id="manager-1")
    earlier = alert_row(transition_id="transition-1", seconds=1, actor_id="engine-1")

    content = alert_transitions_csv_bytes([later, earlier]).decode("utf-8")

    assert "actor_id,actor_source" in content
    assert content.index("engine-1,verified-jwt") < content.index(
        "manager-1,verified-jwt"
    )


def test_artifact_descriptor_hashes_exact_bytes() -> None:
    content = b"event_id,value\nevent-1,3.5\n"
    descriptor = ArtifactDescriptor.from_bytes(
        name="telemetry.csv",
        media_type="text/csv",
        content=content,
        row_count=1,
    )

    assert descriptor.sha256 == sha256_hex(content)
    assert descriptor.size_bytes == len(content)
    assert descriptor.row_count == 1


def test_manifest_is_stable_regardless_of_artifact_input_order() -> None:
    telemetry = ArtifactDescriptor.from_bytes(
        name="telemetry.csv",
        media_type="text/csv",
        content=b"telemetry\n",
        row_count=1,
    )
    alerts = ArtifactDescriptor.from_bytes(
        name="alerts.csv",
        media_type="text/csv",
        content=b"alerts\n",
        row_count=2,
    )
    source_sha256 = sha256_hex(b"source snapshot")
    generated_at = datetime(2026, 7, 26, 16, 0, tzinfo=UTC)

    first = report_manifest_bytes(
        report_id="report-1",
        organization_id="organization-1",
        session_id="session-1",
        report_version=1,
        source_sha256=source_sha256,
        generated_at=generated_at,
        generated_by="engineer-1",
        artifacts=[telemetry, alerts],
    )
    second = report_manifest_bytes(
        report_id="report-1",
        organization_id="organization-1",
        session_id="session-1",
        report_version=1,
        source_sha256=source_sha256,
        generated_at=generated_at,
        generated_by="engineer-1",
        artifacts=[alerts, telemetry],
    )

    assert first == second
    manifest = json.loads(first)
    assert [item["name"] for item in manifest["artifacts"]] == [
        "alerts.csv",
        "telemetry.csv",
    ]


def test_naive_datetimes_and_non_finite_numbers_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json_bytes({"captured_at": datetime(2026, 7, 26, 12, 0)})

    with pytest.raises(ValueError, match="finite"):
        telemetry_csv_bytes(
            [telemetry_row(event_id="event-1", seconds=1, value=float("nan"))]
        )


def test_manifest_rejects_duplicate_artifact_names() -> None:
    artifact = ArtifactDescriptor.from_bytes(
        name="telemetry.csv",
        media_type="text/csv",
        content=b"telemetry\n",
    )

    with pytest.raises(ValueError, match="unique"):
        report_manifest_bytes(
            report_id="report-1",
            organization_id="organization-1",
            session_id="session-1",
            report_version=1,
            source_sha256=sha256_hex(b"source"),
            generated_at=datetime(2026, 7, 26, 16, 0, tzinfo=UTC),
            generated_by="engineer-1",
            artifacts=[artifact, artifact],
        )
