from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape

import qrcode
import reportlab
import xlsxwriter
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.reports.domain import (
    ALERT_TRANSITION_CSV_FIELDS,
    TELEMETRY_CSV_FIELDS,
    ArtifactDescriptor,
    canonical_json_bytes,
    sha256_hex,
)
from app.reports.presentation_domain import (
    REPORT_RENDERER_VERSION,
    ReportVerificationPayload,
    normalize_zip_archive,
)


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"
_MAX_WORKSHEET_ROWS = 1_048_576
_MAX_RENDER_ROWS = _MAX_WORKSHEET_ROWS - 1
_MAX_PDF_ALERT_ROWS = 40
_MAX_CHART_ROWS = 500
_FIXED_DOCUMENT_CREATED = datetime(1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class ReportPresentationSource:
    verification: ReportVerificationPayload
    source_snapshot: Mapping[str, Any]
    manifest_content: bytes
    telemetry_csv: bytes
    alert_transitions_csv: bytes

    def __post_init__(self) -> None:
        source_content = canonical_json_bytes(self.source_snapshot)
        if sha256_hex(source_content) != self.verification.source_sha256:
            raise ValueError("source snapshot does not match verification digest")
        if sha256_hex(self.manifest_content) != self.verification.manifest_sha256:
            raise ValueError("manifest bytes do not match verification digest")
        _csv_rows(self.telemetry_csv, TELEMETRY_CSV_FIELDS, "telemetry.csv")
        _csv_rows(
            self.alert_transitions_csv,
            ALERT_TRANSITION_CSV_FIELDS,
            "alert-transitions.csv",
        )


@dataclass(frozen=True, slots=True)
class RenderedReportArtifact:
    name: str
    media_type: str
    content: bytes
    renderer_version: str = REPORT_RENDERER_VERSION

    @property
    def descriptor(self) -> ArtifactDescriptor:
        return ArtifactDescriptor.from_bytes(
            name=self.name,
            media_type=self.media_type,
            content=self.content,
        )


def render_xlsx(source: ReportPresentationSource) -> RenderedReportArtifact:
    telemetry_rows = _csv_rows(
        source.telemetry_csv,
        TELEMETRY_CSV_FIELDS,
        "telemetry.csv",
    )
    alert_rows = _csv_rows(
        source.alert_transitions_csv,
        ALERT_TRANSITION_CSV_FIELDS,
        "alert-transitions.csv",
    )
    if len(telemetry_rows) > _MAX_RENDER_ROWS:
        raise ValueError("telemetry evidence exceeds XLSX row limit")
    if len(alert_rows) > _MAX_RENDER_ROWS:
        raise ValueError("alert evidence exceeds XLSX row limit")

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {
            "in_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
            "default_date_format": "yyyy-mm-dd hh:mm:ss",
            "nan_inf_to_errors": False,
        },
    )
    workbook.set_properties(
        {
            "title": (
                f"NEXOLAB report {source.verification.report_id} "
                f"version {source.verification.report_version}"
            ),
            "subject": "Immutable laboratory evidence export",
            "author": "NEXOLAB",
            "manager": "NEXOLAB",
            "company": "NEXOLAB",
            "category": "Laboratory report",
            "keywords": "NEXOLAB, laboratory, telemetry, evidence",
            "comments": source.verification.sha256,
            "created": _FIXED_DOCUMENT_CREATED,
        }
    )
    workbook.set_custom_property("NEXOLAB_Report_ID", source.verification.report_id)
    workbook.set_custom_property(
        "NEXOLAB_Report_Version",
        source.verification.report_version,
        "number",
    )
    workbook.set_custom_property(
        "NEXOLAB_Source_SHA256",
        source.verification.source_sha256,
    )
    workbook.set_custom_property(
        "NEXOLAB_Manifest_SHA256",
        source.verification.manifest_sha256,
    )
    workbook.set_custom_property(
        "NEXOLAB_Renderer_Version",
        source.verification.renderer_version,
    )
    workbook.set_custom_property(
        "NEXOLAB_Verification_SHA256",
        source.verification.sha256,
    )

    formats = _xlsx_formats(workbook)
    _write_summary_sheet(workbook, formats, source, telemetry_rows, alert_rows)
    _write_evidence_sheet(
        workbook,
        formats,
        name="Telemetry",
        fields=TELEMETRY_CSV_FIELDS,
        rows=telemetry_rows,
        numeric_fields={"value"},
    )
    _write_evidence_sheet(
        workbook,
        formats,
        name="Alerts",
        fields=ALERT_TRANSITION_CSV_FIELDS,
        rows=alert_rows,
        numeric_fields=set(),
    )
    _write_verification_sheet(workbook, formats, source)
    _write_chart_data_sheet(workbook, formats, telemetry_rows)

    workbook.close()
    normalized = normalize_zip_archive(output.getvalue())
    return RenderedReportArtifact(
        name="report.xlsx",
        media_type=XLSX_MEDIA_TYPE,
        content=normalized,
    )


def render_pdf(source: ReportPresentationSource) -> RenderedReportArtifact:
    telemetry_rows = _csv_rows(
        source.telemetry_csv,
        TELEMETRY_CSV_FIELDS,
        "telemetry.csv",
    )
    alert_rows = _csv_rows(
        source.alert_transitions_csv,
        ALERT_TRANSITION_CSV_FIELDS,
        "alert-transitions.csv",
    )
    metadata = _metadata(source.source_snapshot)
    session_metadata = _mapping(metadata.get("session"))
    statistics = _telemetry_statistics(telemetry_rows)

    _register_pdf_fonts()
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=(
            f"NEXOLAB report {source.verification.report_id} "
            f"v{source.verification.report_version}"
        ),
        author="NEXOLAB",
        subject="Immutable laboratory evidence protocol",
    )
    styles = _pdf_styles()
    story: list[Any] = [
        Paragraph("NEXOLAB LABORATORY REPORT", styles["Title"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Report ID: <b>{escape(source.verification.report_id)}</b> - "
            f"Version: <b>{source.verification.report_version}</b>",
            styles["Body"],
        ),
        Spacer(1, 3 * mm),
        _pdf_key_value_table(
            (
                ("Session", session_metadata.get("session_number")),
                ("Title", session_metadata.get("title")),
                ("Test object", session_metadata.get("test_object")),
                ("Model", session_metadata.get("model")),
                ("Serial number", session_metadata.get("serial_number")),
                ("Standard", session_metadata.get("standard")),
                ("Method", session_metadata.get("method")),
                ("State", session_metadata.get("state")),
                ("Source start UTC", source.source_snapshot.get("source_started_at")),
                ("Source end UTC", source.source_snapshot.get("source_ended_at")),
            ),
            styles,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Evidence summary", styles["Heading"]),
        _pdf_key_value_table(
            (
                ("Telemetry rows", len(telemetry_rows)),
                ("Alert transition rows", len(alert_rows)),
                ("Source SHA-256", source.verification.source_sha256),
                ("Manifest SHA-256", source.verification.manifest_sha256),
                ("Renderer version", source.verification.renderer_version),
                ("Verification SHA-256", source.verification.sha256),
            ),
            styles,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Telemetry statistics", styles["Heading"]),
        _pdf_statistics_table(statistics, styles),
        Spacer(1, 5 * mm),
        Paragraph("Verification", styles["Heading"]),
        _pdf_verification_block(source, styles),
    ]

    if alert_rows:
        story.extend(
            [
                PageBreak(),
                Paragraph("Alert journal", styles["Heading"]),
                _pdf_alert_table(alert_rows, styles),
            ]
        )

    story.extend(
        [
            Spacer(1, 8 * mm),
            Paragraph("Conclusions", styles["Heading"]),
            Paragraph(
                "This generated presentation contains no editable conclusion. "
                "Formal conclusions are recorded through the controlled approval workflow.",
                styles["Body"],
            ),
        ]
    )

    document.build(
        story,
        canvasmaker=_InvariantReportCanvas,
        onFirstPage=_draw_page_footer,
        onLaterPages=_draw_page_footer,
    )
    return RenderedReportArtifact(
        name="report.pdf",
        media_type=PDF_MEDIA_TYPE,
        content=output.getvalue(),
    )


def render_presentations(
    source: ReportPresentationSource,
) -> tuple[RenderedReportArtifact, RenderedReportArtifact]:
    return render_xlsx(source), render_pdf(source)


def _xlsx_formats(workbook: xlsxwriter.Workbook) -> dict[str, Any]:
    return {
        "title": workbook.add_format(
            {
                "bold": True,
                "font_size": 20,
                "font_color": "#FFFFFF",
                "bg_color": "#0B1D3A",
                "align": "left",
                "valign": "vcenter",
            }
        ),
        "section": workbook.add_format(
            {
                "bold": True,
                "font_size": 12,
                "font_color": "#FFFFFF",
                "bg_color": "#132E5F",
                "border": 1,
                "border_color": "#223B63",
            }
        ),
        "header": workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#0077FF",
                "border": 1,
                "border_color": "#223B63",
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "label": workbook.add_format(
            {
                "bold": True,
                "font_color": "#132E5F",
                "bg_color": "#E6ECF2",
                "border": 1,
                "border_color": "#B8C5D6",
                "valign": "top",
            }
        ),
        "value": workbook.add_format(
            {
                "border": 1,
                "border_color": "#D8E0EA",
                "valign": "top",
                "text_wrap": True,
            }
        ),
        "body": workbook.add_format(
            {
                "border": 1,
                "border_color": "#D8E0EA",
                "valign": "top",
            }
        ),
        "body_text": workbook.add_format(
            {
                "border": 1,
                "border_color": "#D8E0EA",
                "valign": "top",
                "text_wrap": True,
            }
        ),
        "number": workbook.add_format(
            {
                "border": 1,
                "border_color": "#D8E0EA",
                "num_format": "0.###############",
            }
        ),
        "hash": workbook.add_format(
            {
                "font_name": "Courier New",
                "font_size": 9,
                "border": 1,
                "border_color": "#D8E0EA",
                "text_wrap": True,
            }
        ),
        "warning": workbook.add_format(
            {
                "font_color": "#9A3412",
                "bg_color": "#FFEDD5",
                "border": 1,
                "border_color": "#FDBA74",
            }
        ),
    }


def _write_summary_sheet(
    workbook: xlsxwriter.Workbook,
    formats: Mapping[str, Any],
    source: ReportPresentationSource,
    telemetry_rows: list[dict[str, str]],
    alert_rows: list[dict[str, str]],
) -> None:
    sheet = workbook.add_worksheet("Summary")
    sheet.hide_gridlines(2)
    sheet.set_column("A:A", 25)
    sheet.set_column("B:B", 72)
    sheet.set_column("D:K", 14)
    sheet.set_row(0, 34)
    sheet.merge_range("A1:K1", "NEXOLAB Laboratory Report", formats["title"])

    metadata = _metadata(source.source_snapshot)
    session = _mapping(metadata.get("session"))
    rows = (
        ("Report ID", source.verification.report_id),
        ("Report version", source.verification.report_version),
        ("Organization ID", source.verification.organization_id),
        ("Session ID", source.verification.session_id),
        ("Session number", session.get("session_number")),
        ("Title", session.get("title")),
        ("Test object", session.get("test_object")),
        ("Model", session.get("model")),
        ("Serial number", session.get("serial_number")),
        ("Standard", session.get("standard")),
        ("Method", session.get("method")),
        ("Source start UTC", source.source_snapshot.get("source_started_at")),
        ("Source end UTC", source.source_snapshot.get("source_ended_at")),
        ("Telemetry rows", len(telemetry_rows)),
        ("Alert transition rows", len(alert_rows)),
    )
    sheet.write("A3", "Report identity", formats["section"])
    sheet.merge_range("B3:K3", "", formats["section"])
    for index, (label, value) in enumerate(rows, start=3):
        sheet.write(index, 0, label, formats["label"])
        _xlsx_write_value(sheet, index, 1, value, formats["value"])
        sheet.merge_range(index, 1, index, 10, "" if value is None else str(value), formats["value"])

    stats = _telemetry_statistics(telemetry_rows)
    stats_start = len(rows) + 5
    sheet.write(stats_start, 0, "Telemetry statistics", formats["section"])
    sheet.merge_range(stats_start, 1, stats_start, 10, "", formats["section"])
    headers = ("Metric", "Unit", "Count", "Minimum", "Maximum", "Average")
    for column, header in enumerate(headers):
        sheet.write(stats_start + 1, column, header, formats["header"])
    for row_index, item in enumerate(stats, start=stats_start + 2):
        sheet.write_string(row_index, 0, item["metric"], formats["body"])
        sheet.write_string(row_index, 1, item["unit"], formats["body"])
        sheet.write_number(row_index, 2, item["count"], formats["number"])
        sheet.write_number(row_index, 3, item["minimum"], formats["number"])
        sheet.write_number(row_index, 4, item["maximum"], formats["number"])
        sheet.write_number(row_index, 5, item["average"], formats["number"])

    if telemetry_rows:
        chart = workbook.add_chart({"type": "line"})
        chart.add_series(
            {
                "name": "Telemetry values",
                "categories": "=ChartData!$A$2:$A$%d"
                % (min(len(_numeric_telemetry_rows(telemetry_rows)), _MAX_CHART_ROWS) + 1),
                "values": "=ChartData!$B$2:$B$%d"
                % (min(len(_numeric_telemetry_rows(telemetry_rows)), _MAX_CHART_ROWS) + 1),
                "line": {"color": "#00C6E0", "width": 2},
            }
        )
        chart.set_title({"name": "Telemetry sample sequence"})
        chart.set_x_axis({"name": "Captured at UTC"})
        chart.set_y_axis({"name": "Value"})
        chart.set_legend({"none": True})
        chart.set_style(10)
        sheet.insert_chart("H20", chart, {"x_scale": 1.2, "y_scale": 1.0})

    sheet.freeze_panes(2, 0)
    sheet.set_landscape()
    sheet.fit_to_pages(1, 0)


def _write_evidence_sheet(
    workbook: xlsxwriter.Workbook,
    formats: Mapping[str, Any],
    *,
    name: str,
    fields: tuple[str, ...],
    rows: list[dict[str, str]],
    numeric_fields: set[str],
) -> None:
    sheet = workbook.add_worksheet(name)
    sheet.hide_gridlines(2)
    sheet.freeze_panes(1, 0)
    for column, field in enumerate(fields):
        sheet.write_string(0, column, field, formats["header"])
        sheet.set_column(column, column, _column_width(field))
    for row_index, row in enumerate(rows, start=1):
        for column, field in enumerate(fields):
            value = row[field]
            if field in numeric_fields and value:
                try:
                    number = float(value)
                except ValueError:
                    sheet.write_string(row_index, column, value, formats["body_text"])
                else:
                    if not math.isfinite(number):
                        raise ValueError(f"{name} contains a non-finite numeric value")
                    sheet.write_number(row_index, column, number, formats["number"])
            else:
                sheet.write_string(row_index, column, value, formats["body_text"])
    if rows:
        sheet.add_table(
            0,
            0,
            len(rows),
            len(fields) - 1,
            {
                "name": f"NEXOLAB{name.replace(' ', '')}Table",
                "style": "Table Style Medium 2",
                "columns": [{"header": field} for field in fields],
            },
        )
    else:
        sheet.autofilter(0, 0, 0, len(fields) - 1)


def _write_verification_sheet(
    workbook: xlsxwriter.Workbook,
    formats: Mapping[str, Any],
    source: ReportPresentationSource,
) -> None:
    sheet = workbook.add_worksheet("Verification")
    sheet.hide_gridlines(2)
    sheet.set_column("A:A", 28)
    sheet.set_column("B:B", 96)
    sheet.write("A1", "Verification metadata", formats["section"])
    sheet.write("B1", "Value", formats["section"])
    rows = (
        ("Schema", "nexolab.report-presentation.v1"),
        ("Report ID", source.verification.report_id),
        ("Report version", source.verification.report_version),
        ("Organization ID", source.verification.organization_id),
        ("Session ID", source.verification.session_id),
        ("Source SHA-256", source.verification.source_sha256),
        ("Manifest SHA-256", source.verification.manifest_sha256),
        ("Renderer version", source.verification.renderer_version),
        ("Verification SHA-256", source.verification.sha256),
        ("QR payload", source.verification.to_bytes().decode("utf-8").strip()),
    )
    for row_index, (label, value) in enumerate(rows, start=1):
        sheet.write_string(row_index, 0, label, formats["label"])
        cell_format = formats["hash"] if "SHA-256" in label or label == "QR payload" else formats["value"]
        _xlsx_write_value(sheet, row_index, 1, value, cell_format)
    sheet.set_row(len(rows), 70)


def _write_chart_data_sheet(
    workbook: xlsxwriter.Workbook,
    formats: Mapping[str, Any],
    telemetry_rows: list[dict[str, str]],
) -> None:
    sheet = workbook.add_worksheet("ChartData")
    sheet.hide()
    sheet.write_row(0, 0, ["captured_at", "value"], formats["header"])
    for row_index, row in enumerate(
        _numeric_telemetry_rows(telemetry_rows)[:_MAX_CHART_ROWS],
        start=1,
    ):
        sheet.write_string(row_index, 0, row["captured_at"])
        sheet.write_number(row_index, 1, float(row["value"]))


def _xlsx_write_value(
    sheet: xlsxwriter.worksheet.Worksheet,
    row: int,
    column: int,
    value: Any,
    cell_format: Any,
) -> None:
    if value is None:
        sheet.write_blank(row, column, None, cell_format)
    elif isinstance(value, bool):
        sheet.write_boolean(row, column, value, cell_format)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("XLSX values must be finite")
        sheet.write_number(row, column, value, cell_format)
    else:
        sheet.write_string(row, column, str(value), cell_format)


def _pdf_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "NEXOLABTitle",
            parent=sample["Title"],
            fontName="NEXOLAB-Bold",
            fontSize=19,
            leading=23,
            textColor=colors.HexColor("#0B1D3A"),
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "Heading": ParagraphStyle(
            "NEXOLABHeading",
            parent=sample["Heading2"],
            fontName="NEXOLAB-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#132E5F"),
            alignment=TA_LEFT,
            spaceBefore=4,
            spaceAfter=6,
        ),
        "Body": ParagraphStyle(
            "NEXOLABBody",
            parent=sample["BodyText"],
            fontName="NEXOLAB-Regular",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#172033"),
        ),
        "Small": ParagraphStyle(
            "NEXOLABSmall",
            parent=sample["BodyText"],
            fontName="NEXOLAB-Regular",
            fontSize=6.7,
            leading=8.5,
            textColor=colors.HexColor("#334155"),
        ),
        "Hash": ParagraphStyle(
            "NEXOLABHash",
            parent=sample["BodyText"],
            fontName="NEXOLAB-Regular",
            fontSize=6.2,
            leading=8,
            textColor=colors.HexColor("#334155"),
            wordWrap="CJK",
        ),
    }


def _pdf_key_value_table(
    rows: Iterable[tuple[str, Any]],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    data = [
        [
            Paragraph(escape(label), styles["Small"]),
            Paragraph(escape("" if value is None else str(value)), styles["Small"]),
        ]
        for label, value in rows
    ]
    table = Table(data, colWidths=[45 * mm, 113 * mm], repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E6ECF2")),
                ("FONTNAME", (0, 0), (-1, -1), "NEXOLAB-Regular"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C5D6")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _pdf_statistics_table(
    statistics: list[dict[str, Any]],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    headers = ("Metric", "Unit", "Count", "Min", "Max", "Average")
    data: list[list[Any]] = [
        [Paragraph(header, styles["Small"]) for header in headers]
    ]
    for item in statistics or [
        {
            "metric": "No numeric telemetry",
            "unit": "",
            "count": 0,
            "minimum": "",
            "maximum": "",
            "average": "",
        }
    ]:
        data.append(
            [
                Paragraph(escape(str(item[key])), styles["Small"])
                for key in (
                    "metric",
                    "unit",
                    "count",
                    "minimum",
                    "maximum",
                    "average",
                )
            ]
        )
    table = Table(
        data,
        colWidths=[49 * mm, 18 * mm, 18 * mm, 24 * mm, 24 * mm, 25 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0077FF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "NEXOLAB-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "NEXOLAB-Regular"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C5D6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _pdf_verification_block(
    source: ReportPresentationSource,
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    qr_stream = io.BytesIO()
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=4,
        border=2,
    )
    qr.add_data(source.verification.to_bytes())
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    image.save(qr_stream, format="PNG", optimize=False)
    qr_stream.seek(0)
    qr_image = Image(qr_stream, width=32 * mm, height=32 * mm)
    text = Paragraph(
        "<b>Scan payload</b><br/>"
        f"Report: {escape(source.verification.report_id)} v{source.verification.report_version}<br/>"
        f"Source: {escape(source.verification.source_sha256)}<br/>"
        f"Manifest: {escape(source.verification.manifest_sha256)}<br/>"
        f"Verification: {escape(source.verification.sha256)}",
        styles["Hash"],
    )
    table = Table([[qr_image, text]], colWidths=[38 * mm, 120 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#223B63")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _pdf_alert_table(
    rows: list[dict[str, str]],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    headers = ("Occurred UTC", "Event", "State", "Actor", "Metric", "Reason")
    data: list[list[Any]] = [
        [Paragraph(header, styles["Small"]) for header in headers]
    ]
    for row in rows[:_MAX_PDF_ALERT_ROWS]:
        data.append(
            [
                Paragraph(escape(row["occurred_at"]), styles["Small"]),
                Paragraph(escape(row["event_type"]), styles["Small"]),
                Paragraph(escape(row["next_state"]), styles["Small"]),
                Paragraph(escape(row["actor_id"]), styles["Small"]),
                Paragraph(escape(row["metric"]), styles["Small"]),
                Paragraph(escape(row["reason"]), styles["Small"]),
            ]
        )
    if len(rows) > _MAX_PDF_ALERT_ROWS:
        data.append(
            [
                Paragraph(
                    f"{len(rows) - _MAX_PDF_ALERT_ROWS} additional rows are retained in alert-transitions.csv",
                    styles["Small"],
                ),
                "",
                "",
                "",
                "",
                "",
            ]
        )
    table = Table(
        data,
        colWidths=[29 * mm, 27 * mm, 21 * mm, 31 * mm, 25 * mm, 35 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#132E5F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "NEXOLAB-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "NEXOLAB-Regular"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C5D6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _telemetry_statistics(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        raw = row.get("value", "")
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if not math.isfinite(value):
            raise ValueError("telemetry evidence contains a non-finite value")
        grouped[(row.get("metric", ""), row.get("unit", ""))].append(value)
    result: list[dict[str, Any]] = []
    for (metric, unit), values in sorted(grouped.items()):
        result.append(
            {
                "metric": metric,
                "unit": unit,
                "count": len(values),
                "minimum": min(values),
                "maximum": max(values),
                "average": sum(values) / len(values),
            }
        )
    return result


def _numeric_telemetry_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        try:
            value = float(row.get("value", ""))
        except ValueError:
            continue
        if math.isfinite(value):
            result.append(row)
    return result


def _csv_rows(
    content: bytes,
    expected_fields: tuple[str, ...],
    name: str,
) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{name} must use UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != expected_fields:
        raise ValueError(f"{name} columns do not match the evidence contract")
    rows: list[dict[str, str]] = []
    for row in reader:
        if None in row:
            raise ValueError(f"{name} contains extra columns")
        normalized = {field: row.get(field, "") for field in expected_fields}
        if any(value is None for value in normalized.values()):
            raise ValueError(f"{name} contains missing columns")
        rows.append({field: str(value) for field, value in normalized.items()})
    return rows


def _metadata(source_snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(source_snapshot.get("metadata"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _column_width(field: str) -> int:
    if field in {"event_id", "alert_id", "transition_id", "rule_id", "rule_version_id"}:
        return 38
    if field in {"captured_at", "occurred_at"}:
        return 27
    if field in {"reason", "source"}:
        return 34
    if field in {"session_id", "stage_id", "binding_id", "config_snapshot_id"}:
        return 38
    return max(12, min(28, len(field) + 3))


def _register_pdf_fonts() -> None:
    if "NEXOLAB-Regular" in pdfmetrics.getRegisteredFontNames():
        return
    font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    regular = font_dir / "Vera.ttf"
    bold = font_dir / "VeraBd.ttf"
    if not regular.is_file() or not bold.is_file():
        raise RuntimeError("ReportLab bundled Vera fonts are unavailable")
    pdfmetrics.registerFont(TTFont("NEXOLAB-Regular", str(regular)))
    pdfmetrics.registerFont(TTFont("NEXOLAB-Bold", str(bold)))


class _InvariantReportCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 0
        super().__init__(*args, **kwargs)
        self.setAuthor("NEXOLAB")
        self.setCreator(f"NEXOLAB {REPORT_RENDERER_VERSION}")
        self.setSubject("Immutable laboratory evidence protocol")


def _draw_page_footer(pdf: canvas.Canvas, document: SimpleDocTemplate) -> None:
    pdf.saveState()
    pdf.setStrokeColor(colors.HexColor("#D8E0EA"))
    pdf.setLineWidth(0.4)
    pdf.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
    pdf.setFont("NEXOLAB-Regular", 6.5)
    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.drawString(18 * mm, 8 * mm, "NEXOLAB immutable report presentation")
    pdf.drawRightString(A4[0] - 18 * mm, 8 * mm, f"Page {document.page}")
    pdf.restoreState()
