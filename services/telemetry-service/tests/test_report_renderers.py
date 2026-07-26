from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from app.reports.domain import (
    AlertTransitionEvidenceRow,
    TelemetryEvidenceRow,
    alert_transitions_csv_bytes,
    canonical_json_bytes,
    sha256_hex,
    telemetry_csv_bytes,
)
from app.reports.presentation_domain import ReportVerificationPayload
from app.reports.renderers import (
    PDF_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    ReportPresentationSource,
    render_pdf,
    render_presentations,
    render_xlsx,
)


REPORT_ID = "10000000-0000-0000-0000-000000000001"
ORGANIZATION_ID = "20000000-0000-0000-0000-000000000001"
SESSION_ID = "30000000-0000-0000-0000-000000000001"
CAPTURED_AT = datetime(2026, 7, 26, 12, 10, tzinfo=UTC)


def presentation_source() -> ReportPresentationSource:
    source_snapshot = {
        "schema": "nexolab.report-source.v1",
        "organization_id": ORGANIZATION_ID,
        "session_id": SESSION_ID,
        "source_started_at": datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
        "source_ended_at": datetime(2026, 7, 26, 14, 0, tzinfo=UTC),
        "metadata": {
            "session": {
                "id": SESSION_ID,
                "session_number": "NX-REPORT-0001",
                "title": "=HYPERLINK(\"https://invalid.local\",\"unsafe\")",
                "test_object": "Refrigerated display K106",
                "model": "NEXOLAB Acceptance",
                "serial_number": "K106-2026",
                "standard": "ISO 23953",
                "method": "Temperature distribution",
                "state": "completed",
            },
            "configuration": {
                "id": "60000000-0000-0000-0000-000000000001",
                "version": 1,
                "content_sha256": "c" * 64,
            },
            "bindings": [],
            "limits": [],
            "stages": [],
            "notes": [],
            "events": [],
            "audit": [],
        },
        "evidence": {},
    }
    telemetry = telemetry_csv_bytes(
        [
            TelemetryEvidenceRow(
                event_id="80000000-0000-0000-0000-000000000001",
                captured_at=CAPTURED_AT,
                node_id="edge-01",
                equipment_id="K106",
                channel_id="106-03",
                metric="temperature.probe",
                value=3.75,
                unit="degC",
                quality="valid",
                alarm=None,
                source="renderer-test",
                session_id=SESSION_ID,
                stage_id="70000000-0000-0000-0000-000000000001",
                binding_id="50000000-0000-0000-0000-000000000001",
                config_snapshot_id="60000000-0000-0000-0000-000000000001",
            ),
            TelemetryEvidenceRow(
                event_id="80000000-0000-0000-0000-000000000002",
                captured_at=CAPTURED_AT + timedelta(minutes=1),
                node_id="edge-01",
                equipment_id="K106",
                channel_id="106-03",
                metric="temperature.probe",
                value=4.25,
                unit="degC",
                quality="valid",
                alarm="warning",
                source="renderer-test",
                session_id=SESSION_ID,
                stage_id="70000000-0000-0000-0000-000000000001",
                binding_id="50000000-0000-0000-0000-000000000001",
                config_snapshot_id="60000000-0000-0000-0000-000000000001",
            ),
        ]
    )
    alerts = alert_transitions_csv_bytes(
        [
            AlertTransitionEvidenceRow(
                alert_id="92000000-0000-0000-0000-000000000001",
                transition_id="93000000-0000-0000-0000-000000000001",
                rule_id="90000000-0000-0000-0000-000000000001",
                rule_version_id="91000000-0000-0000-0000-000000000001",
                event_type="alert_acknowledged",
                previous_state="active",
                next_state="acknowledged",
                actor_id="laboratory-manager-1",
                actor_source="oidc",
                reason="Reviewed temperature deviation",
                occurred_at=CAPTURED_AT + timedelta(minutes=2),
                severity="warning",
                node_id="edge-01",
                equipment_id="K106",
                channel_id="106-03",
                metric="temperature.probe",
                session_id=SESSION_ID,
                stage_id="70000000-0000-0000-0000-000000000001",
                binding_id="50000000-0000-0000-0000-000000000001",
            )
        ]
    )
    manifest = canonical_json_bytes(
        {
            "schema": "nexolab.report-manifest.v1",
            "report": {"id": REPORT_ID, "version": 1},
            "artifacts": [],
        }
    )
    verification = ReportVerificationPayload(
        report_id=REPORT_ID,
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        report_version=1,
        source_sha256=sha256_hex(canonical_json_bytes(source_snapshot)),
        manifest_sha256=sha256_hex(manifest),
    )
    return ReportPresentationSource(
        verification=verification,
        source_snapshot=source_snapshot,
        manifest_content=manifest,
        telemetry_csv=telemetry,
        alert_transitions_csv=alerts,
    )


def test_xlsx_render_is_deterministic_valid_and_formula_safe() -> None:
    source = presentation_source()
    first = render_xlsx(source)
    second = render_xlsx(source)

    assert first.content == second.content
    assert first.name == "report.xlsx"
    assert first.media_type == XLSX_MEDIA_TYPE
    assert first.descriptor.sha256 == sha256_hex(first.content)
    assert first.content.startswith(b"PK")

    with ZipFile(io.BytesIO(first.content)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist())
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        assert 'name="Summary"' in workbook_xml
        assert 'name="Telemetry"' in workbook_xml
        assert 'name="Alerts"' in workbook_xml
        assert 'name="Verification"' in workbook_xml
        shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
        assert "HYPERLINK" in shared_strings
        worksheet_xml = b"".join(
            archive.read(name)
            for name in names
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        ).decode("utf-8")
        assert "https://invalid.local" not in worksheet_xml
        assert source.verification.source_sha256 in shared_strings
        assert source.verification.manifest_sha256 in shared_strings


def test_pdf_render_is_deterministic_searchable_and_verifiable() -> None:
    source = presentation_source()
    first = render_pdf(source)
    second = render_pdf(source)

    assert first.content == second.content
    assert first.name == "report.pdf"
    assert first.media_type == PDF_MEDIA_TYPE
    assert first.descriptor.sha256 == sha256_hex(first.content)
    assert first.content.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(first.content))
    assert len(reader.pages) == 2
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "NEXOLAB LABORATORY REPORT" in text
    assert REPORT_ID in text
    assert "NX-REPORT-0001" in text
    assert "ISO 23953" in text
    assert "temperature.probe" in text
    assert "alert_acknowledged" in text
    assert "laboratory-manager-1" in text
    assert source.verification.source_sha256 in text
    assert source.verification.manifest_sha256 in text
    assert source.verification.sha256 in text


def test_bundle_returns_xlsx_then_pdf() -> None:
    xlsx, pdf = render_presentations(presentation_source())
    assert xlsx.name == "report.xlsx"
    assert pdf.name == "report.pdf"


def test_renderer_rejects_source_or_manifest_tampering() -> None:
    source = presentation_source()
    with pytest.raises(ValueError, match="source snapshot"):
        ReportPresentationSource(
            verification=source.verification,
            source_snapshot={**source.source_snapshot, "session_id": "changed"},
            manifest_content=source.manifest_content,
            telemetry_csv=source.telemetry_csv,
            alert_transitions_csv=source.alert_transitions_csv,
        )
    with pytest.raises(ValueError, match="manifest bytes"):
        ReportPresentationSource(
            verification=source.verification,
            source_snapshot=source.source_snapshot,
            manifest_content=b"{}\n",
            telemetry_csv=source.telemetry_csv,
            alert_transitions_csv=source.alert_transitions_csv,
        )


def test_renderer_rejects_wrong_csv_contract() -> None:
    source = presentation_source()
    with pytest.raises(ValueError, match="columns"):
        ReportPresentationSource(
            verification=source.verification,
            source_snapshot=source.source_snapshot,
            manifest_content=source.manifest_content,
            telemetry_csv=b"event_id,value\n1,2\n",
            alert_transitions_csv=source.alert_transitions_csv,
        )
