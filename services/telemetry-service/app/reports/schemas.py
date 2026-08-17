from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportGenerateRequest(BaseModel):
    expected_source_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    reason: str | None = Field(default=None, max_length=1024)
    binding_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )


class ReportArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    name: str
    media_type: str
    sha256: str
    size_bytes: int
    row_count: int | None
    created_at: datetime


class ReportRead(BaseModel):
    id: str
    organization_id: str
    session_id: str
    config_snapshot_id: str
    version: int
    session_state: str
    source_started_at: datetime
    source_ended_at: datetime
    source_sha256: str
    manifest_sha256: str
    generator_version: str
    generated_by: str
    generated_at: datetime
    created_at: datetime
    artifacts: list[ReportArtifactRead]


class ReportGenerationResponse(ReportRead):
    replayed: bool


class ReportPageRead(BaseModel):
    items: list[ReportRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None
