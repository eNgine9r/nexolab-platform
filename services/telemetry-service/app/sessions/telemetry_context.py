from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


@dataclass(frozen=True, slots=True)
class TelemetryAttribution:
    session_id: str
    binding_id: str
    stage_id: str | None
    config_snapshot_id: str
    session_state: str
    captured_at: datetime
    attributed_at: datetime

    def payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "binding_id": self.binding_id,
            "stage_id": self.stage_id,
            "config_snapshot_id": self.config_snapshot_id,
            "session_state": self.session_state,
        }


class TelemetrySessionContext(Base):
    __tablename__ = "telemetry_session_contexts"
    __table_args__ = (
        CheckConstraint(
            "session_state IN ('running', 'paused')",
            name="ck_telemetry_session_context_state",
        ),
        Index(
            "ix_telemetry_context_session_captured",
            "session_id",
            "captured_at",
            "event_id",
        ),
        Index(
            "ix_telemetry_context_stage_captured",
            "stage_id",
            "captured_at",
            "event_id",
        ),
        Index(
            "ix_telemetry_context_binding_captured",
            "binding_id",
            "captured_at",
            "event_id",
        ),
        Index(
            "ix_telemetry_context_snapshot_captured",
            "config_snapshot_id",
            "captured_at",
        ),
    )

    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "telemetry_samples.event_id",
            name="fk_telemetry_context_event_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_telemetry_context_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    binding_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_channel_bindings.id",
            name="fk_telemetry_context_binding_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    stage_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_telemetry_context_stage_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    config_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_config_snapshots.id",
            name="fk_telemetry_context_config_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    session_state: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
