from __future__ import annotations

import io
import json
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.reports.domain import ArtifactDescriptor, canonical_json_bytes, sha256_hex
from app.reports.renderer import (
    ParsedCsv,
    RenderedReportArtifact,
    _csv_rows,
    _json_object,
    _require_artifacts,
    _verify_evidence,
)

PDF_MEDIA_TYPE = "application/pdf"
PDF_RENDERER_VERSION = "nexolab-pdf-protocol-v1"
_DEFAULT_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
_DEFAULT_BOLD_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)
_FONT_NAME = "NEXOLABDejaVuSans"
_FONT_BOLD_NAME = "NEXOLABDejaVuSansBold"


@dataclass(frozen=True, slots=True)
class TelemetryAggregate:
    equipment_id: str
    channel_id: str
    metric: str
    unit: str
    count: int
    numeric_count: int
    minimum: Decimal | None
    maximum: Decimal | None
    average: Decimal | None
    first_captured_at: str
    last_captured_at: str


def render_pdf_protocol(
    artifacts: Mapping[str, bytes],
    *,
    font_path: str | None = None,
    bold_font_path: str | None = None,
) -> RenderedReportArtifact:
    frozen = {name: bytes(content) for name, content in artifacts.items()}
    _require_artifacts(frozen)
    manifest = _json_object(frozen["manifest.json"], "manifest.json")
    source = _json_object(frozen["source-snapshot.json"], "source-snapshot.json")
    descriptors = _verify_evidence(frozen, manifest, source)
    telemetry = _csv_rows(
        frozen["telemetry.csv"],
        "telemetry.csv",
        descriptors["telemetry.csv"].row_count,
    )
    alerts = _csv_rows(
        frozen["alert-transitions.csv"],
        "alert-transitions.csv",
        descriptors["alert-transitions.csv"].row_count,
    )
    regular, bold = _register_fonts(font_path, bold_font_path)
    content = _build_pdf(
        manifest=manifest,
        source=source,
        descriptors=descriptors,
        manifest_content=frozen["manifest.json"],
        telemetry=telemetry,
        alerts=alerts,
        regular_font=regular,
        bold_font=bold,
    )
    descriptor = ArtifactDescriptor.from_bytes(
        name="protocol.pdf",
        media_type=PDF_MEDIA_TYPE,
        content=content,
    )
    return RenderedReportArtifact(descriptor, content, PDF_RENDERER_VERSION)


def _build_pdf(
    *,
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    descriptors: Mapping[str, ArtifactDescriptor],
    manifest_content: bytes,
    telemetry: ParsedCsv,
    alerts: ParsedCsv,
    regular_font: str,
    bold_font: str,
) -> bytes:
    report = _mapping(manifest.get("report"), "manifest.report")
    metadata = _mapping(source.get("metadata"), "source.metadata")
    session = _mapping(metadata.get("session"), "source.metadata.session")
    report_id = _text(report.get("id"))
    verification_payload = {
        "schema": "nexolab.report-verification.v1",
        "report_id": report_id,
        "organization_id": report.get("organization_id"),
        "session_id": report.get("session_id"),
        "report_version": report.get("version"),
        "manifest_sha256": sha256_hex(manifest_content),
        "source_sha256": report.get("source_sha256"),
        "renderer_version": PDF_RENDERER_VERSION,
    }
    verification_bytes = canonical_json_bytes(verification_payload)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title="NEXOLAB test protocol",
        author="NEXOLAB",
        subject="Immutable telemetry test protocol",
        creator=PDF_RENDERER_VERSION,
    )
    styles = _styles(regular_font, bold_font)
    story: list[Any] = [
        Paragraph("NEXOLAB", styles["brand"]),
        Paragraph("Immutable Test Protocol", styles["title"]),
        Spacer(1, 4 * mm),
        _key_value_table(
            [
                ("Report ID", report_id),
                ("Version", report.get("version")),
                ("Session", report.get("session_id")),
                ("Organization", report.get("organization_id")),
                ("Generated at (UTC)", report.get("generated_at")),
                ("Generated by", report.get("generated_by")),
                ("Source interval", _interval(source)),
                ("Protocol renderer", PDF_RENDERER_VERSION),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Test identification", styles["heading"]),
        _key_value_table(
            [
                ("State", session.get("state")),
                ("Title", session.get("title")),
                ("Customer", session.get("customer")),
                ("Test object", session.get("test_object")),
                ("Model", session.get("model")),
                ("Serial number", session.get("serial_number")),
                ("Standard", session.get("standard")),
                ("Method", session.get("method")),
                ("Node", session.get("node_id")),
                ("Operator", session.get("operator_id")),
                ("Responsible engineer", session.get("responsible_engineer_id")),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Telemetry summary", styles["heading"]),
        _telemetry_table(_aggregate_telemetry(telemetry.rows), styles),
        Spacer(1, 5 * mm),
        Paragraph("Alert transition log", styles["heading"]),
        _alerts_table(alerts.rows, styles),
        PageBreak(),
        Paragraph("Immutable evidence", styles["heading"]),
        _evidence_table(descriptors, manifest_content, styles),
        Spacer(1, 5 * mm),
        Paragraph("Verification payload", styles["heading"]),
        Paragraph(
            _wrap_token(verification_bytes.decode("utf-8").strip(), 72),
            styles["code"],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            "Verification payload SHA-256: "
            + _wrap_token(sha256_hex(verification_bytes), 16),
            styles["small"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Frozen source inventory", styles["heading"]),
        _inventory_table(metadata, styles),
        Spacer(1, 8 * mm),
        Paragraph(
            "This protocol was rendered exclusively from immutable report artifacts. "
            "It does not query live telemetry, alerts, configuration, or operator data.",
            styles["notice"],
        ),
    ]

    footer = partial(
        _draw_footer,
        report_id=report_id,
        regular_font=regular_font,
    )
    document.build(
        story,
        canvasmaker=_ProtocolCanvas,
        onFirstPage=footer,
        onLaterPages=footer,
    )
    return buffer.getvalue()


class _ProtocolCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 1
        super().__init__(*args, **kwargs)
        self.setAuthor("NEXOLAB")
        self.setCreator(PDF_RENDERER_VERSION)
        self.setTitle("NEXOLAB immutable test protocol")
        self.setSubject("Frozen telemetry and alert evidence")
        self.setKeywords("NEXOLAB report telemetry evidence verification")


def _draw_footer(
    pdf: canvas.Canvas,
    document: SimpleDocTemplate,
    *,
    report_id: str,
    regular_font: str,
) -> None:
    del document
    pdf.saveState()
    pdf.setFont(regular_font, 7)
    pdf.setFillColor(colors.HexColor("#5A6270"))
    pdf.drawString(16 * mm, 9 * mm, f"Report {report_id}")
    pdf.drawRightString(
        A4[0] - 16 * mm,
        9 * mm,
        f"Page {pdf.getPageNumber()} | {PDF_RENDERER_VERSION}",
    )
    pdf.restoreState()


def _styles(regular_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "brand",
            parent=base["Normal"],
            fontName=bold_font,
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#4955FF"),
            alignment=TA_LEFT,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=bold_font,
            fontSize=21,
            leading=25,
            textColor=colors.HexColor("#10131A"),
            alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "heading": ParagraphStyle(
            "heading",
            parent=base["Heading2"],
            fontName=bold_font,
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#10131A"),
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=regular_font,
            fontSize=8.2,
            leading=10.5,
            textColor=colors.HexColor("#252A34"),
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=regular_font,
            fontSize=7.2,
            leading=9,
            textColor=colors.HexColor("#353B47"),
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName=regular_font,
            fontSize=6.6,
            leading=8.4,
            textColor=colors.HexColor("#1F2630"),
            backColor=colors.HexColor("#F2F4F8"),
            borderPadding=6,
            wordWrap="CJK",
        ),
        "notice": ParagraphStyle(
            "notice",
            parent=base["BodyText"],
            fontName=regular_font,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#353B47"),
            backColor=colors.HexColor("#F2F4F8"),
            borderPadding=8,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            parent=base["Normal"],
            fontName=bold_font,
            fontSize=7,
            leading=8.5,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            parent=base["Normal"],
            fontName=regular_font,
            fontSize=6.8,
            leading=8.2,
            textColor=colors.HexColor("#252A34"),
            alignment=TA_LEFT,
        ),
    }


def _key_value_table(
    rows: list[tuple[str, Any]],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    body = [
        [
            Paragraph(escape(label), styles["table_cell"]),
            Paragraph(escape(_text(value)), styles["body"]),
        ]
        for label, value in rows
        if _text(value)
    ]
    table = Table(body, colWidths=(46 * mm, 132 * mm), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F4F8")),
                ("FONTNAME", (0, 0), (0, -1), styles["table_cell"].fontName),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7DCE5")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _telemetry_table(
    rows: list[TelemetryAggregate],
    styles: Mapping[str, ParagraphStyle],
) -> Any:
    headers = (
        "Equipment",
        "Channel",
        "Metric",
        "Count",
        "Min",
        "Max",
        "Average",
        "Interval (UTC)",
    )
    if not rows:
        return Paragraph("No telemetry evidence rows.", styles["body"])
    data: list[list[Any]] = [[Paragraph(value, styles["table_header"]) for value in headers]]
    for row in rows:
        data.append(
            [
                _p(row.equipment_id, styles),
                _p(row.channel_id, styles),
                _p(f"{row.metric} [{row.unit}]", styles),
                _p(str(row.count), styles),
                _p(_decimal(row.minimum), styles),
                _p(_decimal(row.maximum), styles),
                _p(_decimal(row.average), styles),
                _p(f"{row.first_captured_at} - {row.last_captured_at}", styles),
            ]
        )
    return _styled_table(
        data,
        (20, 20, 35, 13, 15, 15, 17, 43),
        repeat_rows=1,
    )


def _alerts_table(
    rows: list[dict[str, str]],
    styles: Mapping[str, ParagraphStyle],
) -> Any:
    headers = (
        "Occurred (UTC)",
        "Severity",
        "Equipment / channel",
        "Event / state",
        "Actor",
        "Reason",
    )
    if not rows:
        return Paragraph("No alert transitions were recorded.", styles["body"])
    data: list[list[Any]] = [[Paragraph(value, styles["table_header"]) for value in headers]]
    for row in rows:
        data.append(
            [
                _p(row.get("occurred_at", ""), styles),
                _p(row.get("severity", ""), styles),
                _p(
                    f"{row.get('equipment_id', '')} / {row.get('channel_id', '')}",
                    styles,
                ),
                _p(
                    f"{row.get('event_type', '')}: {row.get('previous_state', '')} -> "
                    f"{row.get('next_state', '')}",
                    styles,
                ),
                _p(
                    f"{row.get('actor_id', '')} ({row.get('actor_source', '')})",
                    styles,
                ),
                _p(row.get("reason", ""), styles),
            ]
        )
    return _styled_table(data, (31, 18, 31, 42, 31, 25), repeat_rows=1)


def _evidence_table(
    descriptors: Mapping[str, ArtifactDescriptor],
    manifest_content: bytes,
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    headers = ("Artifact", "Media type", "SHA-256", "Bytes", "Rows")
    data: list[list[Any]] = [[Paragraph(value, styles["table_header"]) for value in headers]]
    evidence = list(sorted(descriptors.values(), key=lambda item: item.name))
    evidence.append(
        ArtifactDescriptor.from_bytes(
            name="manifest.json",
            media_type="application/json",
            content=manifest_content,
        )
    )
    for item in evidence:
        data.append(
            [
                _p(item.name, styles),
                _p(item.media_type, styles),
                _p(_wrap_token(item.sha256, 16), styles),
                _p(str(item.size_bytes), styles),
                _p("" if item.row_count is None else str(item.row_count), styles),
            ]
        )
    return _styled_table(data, (29, 45, 67, 20, 17), repeat_rows=1)


def _inventory_table(
    metadata: Mapping[str, Any],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    keys = (
        "bindings",
        "limits",
        "stages",
        "notes",
        "events",
        "audit",
    )
    rows = [[Paragraph("Collection", styles["table_header"]), Paragraph("Count", styles["table_header"])]]
    for key in keys:
        value = metadata.get(key)
        count = len(value) if isinstance(value, list) else 0
        rows.append([_p(key, styles), _p(str(count), styles)])
    return _styled_table(rows, (70, 25), repeat_rows=1)


def _styled_table(
    data: list[list[Any]],
    widths_mm: tuple[int, ...],
    *,
    repeat_rows: int,
) -> Table:
    table = Table(
        data,
        colWidths=tuple(width * mm for width in widths_mm),
        repeatRows=repeat_rows,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4955FF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7DCE5")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FB")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _aggregate_telemetry(rows: list[dict[str, str]]) -> list[TelemetryAggregate]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("equipment_id", ""),
            row.get("channel_id", ""),
            row.get("metric", ""),
            row.get("unit", ""),
        )
        grouped[key].append(row)
    result: list[TelemetryAggregate] = []
    for key in sorted(grouped):
        group = grouped[key]
        values: list[Decimal] = []
        for row in group:
            raw = row.get("value", "")
            if not raw:
                continue
            try:
                values.append(Decimal(raw))
            except InvalidOperation as error:
                raise ValueError(f"invalid numeric telemetry value: {raw}") from error
        timestamps = [row.get("captured_at", "") for row in group]
        average = sum(values, Decimal(0)) / len(values) if values else None
        result.append(
            TelemetryAggregate(
                equipment_id=key[0],
                channel_id=key[1],
                metric=key[2],
                unit=key[3],
                count=len(group),
                numeric_count=len(values),
                minimum=min(values) if values else None,
                maximum=max(values) if values else None,
                average=average,
                first_captured_at=min(timestamps) if timestamps else "",
                last_captured_at=max(timestamps) if timestamps else "",
            )
        )
    return result


def _register_fonts(
    font_path: str | None,
    bold_font_path: str | None,
) -> tuple[str, str]:
    regular_path = _font_path(
        font_path or os.getenv("NEXOLAB_PDF_FONT_PATH"),
        _DEFAULT_FONT_PATHS,
        "regular",
    )
    bold_path = _font_path(
        bold_font_path or os.getenv("NEXOLAB_PDF_BOLD_FONT_PATH"),
        _DEFAULT_BOLD_FONT_PATHS,
        "bold",
    )
    registered = set(pdfmetrics.getRegisteredFontNames())
    if _FONT_NAME not in registered:
        pdfmetrics.registerFont(TTFont(_FONT_NAME, regular_path))
    if _FONT_BOLD_NAME not in registered:
        pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, bold_path))
    return _FONT_NAME, _FONT_BOLD_NAME


def _font_path(
    explicit: str | None,
    candidates: tuple[str, ...],
    variant: str,
) -> str:
    options = ((explicit,) if explicit else ()) + candidates
    for option in options:
        if option and Path(option).is_file():
            return option
    raise ValueError(
        f"DejaVu Sans {variant} font is required for deterministic Unicode PDF rendering"
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _p(value: Any, styles: Mapping[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(escape(_text(value)), styles["table_cell"])


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float, Decimal)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    normalized = value.normalize()
    return format(normalized, "f")


def _interval(source: Mapping[str, Any]) -> str:
    return f"{_text(source.get('source_started_at'))} - {_text(source.get('source_ended_at'))}"


def _wrap_token(value: str, width: int) -> str:
    return " ".join(value[index : index + width] for index in range(0, len(value), width))
