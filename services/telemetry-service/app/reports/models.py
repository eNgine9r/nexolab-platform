from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

REPORTABLE_SESSION_STATES = ("completed", "archived")
_REPORTABLE_SESSION_STATE_SQL = ", ".join(
    f"'{state}'" for state in REPORTABLE_SESSION_STATES
)


class TestReportVersion(Base):
    __tablename__ = "test_report_versions"
    __table_args__ = (
        CheckConstraint(
            "version >= 1",
            name="ck_test_report_versions_version_positive",
        ),
        CheckConstraint(
            f"session_state IN ({_REPORTABLE_SESSION_STATE_SQL})",
            name="ck_test_report_versions_session_state",
        ),
        CheckConstraint(
            "source_ended_at >= source_started_at",
            name="ck_test_report_versions_source_window",
        ),
        UniqueConstraint(
            "session_id",
            "version",
            name="uq_test_report_versions_session_version",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_test_report_versions_organization_idempotency",
        ),
        Index(
            "ix_test_report_versions_organization_generated",
            "organization_id",
            "generated_at",
        ),
        Index(
            "ix_test_report_versions_session_version",
            "session_id",
            "version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_test_report_versions_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_test_report_versions_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    config_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_config_snapshots.id",
            name="fk_test_report_versions_config_snapshot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    session_state: Mapped[str] = mapped_column(String(32), nullable=False)
    source_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TestReportArtifact(Base):
    __tablename__ = "test_report_artifacts"
    __table_args__ = (
        CheckConstraint(
            "size_bytes >= 0",
            name="ck_test_report_artifacts_size_nonnegative",
        ),
        CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_test_report_artifacts_rows_nonnegative",
        ),
        UniqueConstraint(
            "report_id",
            "name",
            name="uq_test_report_artifacts_report_name",
        ),
        Index("ix_test_report_artifacts_report", "report_id", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_report_versions.id",
            name="fk_test_report_artifacts_report",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
