from __future__ import annotations

import hashlib
import io
import json

from pypdf import PdfReader

from app.reports.pdf_renderer import (
    PDF_MEDIA_TYPE,
    PDF_RENDERER_VERSION,
    render_pdf_protocol,
)
from test_report_renderer import report_artifacts


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _with_session_title(artifacts: dict[str, bytes], title: str) -> dict[str, bytes]:
    updated = dict(artifacts)
    source = json.loads(updated["source-snapshot.json"])
    source["metadata"]["session"]["title"] = title
    source_content = _canonical(source)
    manifest = json.loads(updated["manifest.json"])
    source_digest = hashlib.sha256(source_content).hexdigest()
    manifest["report"]["source_sha256"] = source_digest
    for descriptor in manifest["artifacts"]:
        if descriptor["name"] == "source-snapshot.json":
            descriptor["sha256"] = source_digest
            descriptor["size_bytes"] = len(source_content)
    updated["source-snapshot.json"] = source_content
    updated["manifest.json"] = _canonical(manifest)
    return updated


def test_pdf_protocol_is_byte_stable_and_contains_verification_data() -> None:
    artifacts = report_artifacts()

    first = render_pdf_protocol(artifacts)
    second = render_pdf_protocol(dict(reversed(list(artifacts.items()))))

    assert first.content == second.content
    assert first.descriptor.media_type == PDF_MEDIA_TYPE
    assert first.descriptor.sha256 == hashlib.sha256(first.content).hexdigest()
    assert first.renderer_version == PDF_RENDERER_VERSION
    reader = PdfReader(io.BytesIO(first.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "NEXOLAB" in text
    assert "Immutable Test Protocol" in text
    assert "report-1" in text
    assert "verified-jwt" in text
    assert "nexolab.report-verification.v1" in text
    assert len(reader.pages) == 2


def test_pdf_protocol_preserves_unicode_metadata() -> None:
    artifacts = _with_session_title(
        report_artifacts(),
        "Протокол холодильної вітрини",
    )

    rendered = render_pdf_protocol(artifacts)
    reader = PdfReader(io.BytesIO(rendered.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Протокол холодильної вітрини" in text
