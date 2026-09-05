from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


ACCEPTANCE_SCHEMA_VERSION = "acceptance-state/v1"
CALIBRATION_SCHEMA_VERSION = "calibration-state/v1"
CALIBRATION_STATES = ("valid", "due", "expired", "revoked", "unknown")
REGISTRY_LIFECYCLE_STATES = ("active", "inactive", "retired")

_CALIBRATION_STATE_SQL = ", ".join(f"'{state}'" for state in CALIBRATION_STATES)
_REGISTRY_LIFECYCLE_SQL = ", ".join(
    f"'{state}'" for state in REGISTRY_LIFECYCLE_STATES
)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_instruments_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "inventory_key",
            name="uq_instruments_organization_inventory_key",
        ),
        CheckConstraint(
            f"lifecycle_state IN ({_REGISTRY_LIFECYCLE_SQL})",
            name="ck_instruments_lifecycle_state",
        ),
        CheckConstraint("version >= 1", name="ck_instruments_version_positive"),
        Index(
            "ix_instruments_organization_lifecycle_name",
            "organization_id",
            "lifecycle_state",
            "display_name",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_instruments_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    inventory_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    instrument_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Signal(Base):
    __tablename__ = "instrument_signals"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_instrument_signals_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "business_key",
            name="uq_instrument_signals_organization_business_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "instrument_id"],
            ["instruments.organization_id", "instruments.id"],
            name="fk_instrument_signals_instrument",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"lifecycle_state IN ({_REGISTRY_LIFECYCLE_SQL})",
            name="ck_instrument_signals_lifecycle_state",
        ),
        CheckConstraint(
            "version >= 1", name="ck_instrument_signals_version_positive"
        ),
        Index(
            "ix_instrument_signals_instrument_lifecycle",
            "organization_id",
            "instrument_id",
            "lifecycle_state",
            "display_name",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_instrument_signals_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    physical_quantity: Mapped[str] = mapped_column(String(64), nullable=False)
    engineering_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InstrumentAcceptanceRecord(Base):
    __tablename__ = "instrument_acceptance_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "instrument_id"],
            ["instruments.organization_id", "instruments.id"],
            name="fk_instrument_acceptance_instrument",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "instrument_id",
            "revision",
            name="uq_instrument_acceptance_revision",
        ),
        CheckConstraint(
            f"schema_version = '{ACCEPTANCE_SCHEMA_VERSION}'",
            name="ck_instrument_acceptance_schema_version",
        ),
        CheckConstraint(
            "revision >= 1", name="ck_instrument_acceptance_revision_positive"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_instrument_acceptance_interval",
        ),
        Index(
            "ix_instrument_acceptance_as_of",
            "organization_id",
            "instrument_id",
            "effective_from",
            "effective_to",
            "revision",
        ),
        Index(
            "uq_instrument_acceptance_open",
            "organization_id",
            "instrument_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_instrument_acceptance_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ACCEPTANCE_SCHEMA_VERSION
    )
    accepted_for_calculation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InstrumentCalibrationRecord(Base):
    __tablename__ = "instrument_calibration_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "instrument_id"],
            ["instruments.organization_id", "instruments.id"],
            name="fk_instrument_calibration_instrument",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "instrument_id",
            "calibration_scope",
            "revision",
            name="uq_instrument_calibration_revision",
        ),
        CheckConstraint(
            f"schema_version = '{CALIBRATION_SCHEMA_VERSION}'",
            name="ck_instrument_calibration_schema_version",
        ),
        CheckConstraint(
            f"state IN ({_CALIBRATION_STATE_SQL})",
            name="ck_instrument_calibration_state",
        ),
        CheckConstraint(
            "revision >= 1", name="ck_instrument_calibration_revision_positive"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_instrument_calibration_interval",
        ),
        Index(
            "ix_instrument_calibration_as_of",
            "organization_id",
            "instrument_id",
            "calibration_scope",
            "valid_from",
            "valid_to",
            "revision",
        ),
        Index(
            "uq_instrument_calibration_open",
            "organization_id",
            "instrument_id",
            "calibration_scope",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_instrument_calibration_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(String(36), nullable=False)
    calibration_scope: Mapped[str] = mapped_column(
        String(64), nullable=False, default="instrument", server_default="instrument"
    )
    schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CALIBRATION_SCHEMA_VERSION
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    certificate_reference: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
