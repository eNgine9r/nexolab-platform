from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Sha256 = Field(
    min_length=64,
    max_length=64,
    pattern=r"^[0-9a-fA-F]{64}$",
)


class ReportRenderRequest(BaseModel):
    expected_manifest_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    reason: str | None = Field(default=None, max_length=2000)


class ReportRenderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    organization_id: str
    format: Literal["xlsx", "pdf"]
    artifact_name: str
    media_type: str
    renderer_version: str
    manifest_sha256: str
    sha256: str
    size_bytes: int
    rendered_by: str
    rendered_at: datetime
    created_at: datetime


class ReportRenderResponse(ReportRenderRead):
    replayed: bool


class ReportApprovalStateRead(BaseModel):
    state: Literal["generated", "approved", "superseded"]
    manifest_sha256: str
    approved_by: str | None
    approved_at: datetime | None
    approval_reason: str | None
    approval_idempotency_key: str | None
    approval_command_sha256: str | None
    superseded_by_report_id: str | None
    superseded_at: datetime | None


class ReportOutputStateRead(BaseModel):
    report_id: str
    approval: ReportApprovalStateRead
    renders: list[ReportRenderRead]


class ReportApproveRequest(BaseModel):
    expected_manifest_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    reason: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime


class ReportSupersedeRequest(ReportApproveRequest):
    replacement_report_id: str = Field(min_length=1, max_length=36)


class ReportApprovalActionResponse(BaseModel):
    event_id: str
    decision: Literal["approve", "replay", "supersede"]
    approval: ReportApprovalStateRead
