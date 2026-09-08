from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
    Numeric,
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
ANALOG_SCALING_SCHEMA_VERSION = "analog-scaling/v1"
ANALOG_ELECTRICAL_INPUT_CLASSES = ("current_loop_4_20ma",)
ANALOG_SCALING_POLICIES = ("linear_two_point",)
ANALOG_RANGE_POLICIES = ("unavailable",)
ANALOG_EVIDENCE_STATUSES = ("software_verified", "hardware_unverified", "hardware_verified")
ACQUISITION_SOURCE_SCHEMA_VERSION = "acquisition-source/v1"

_CALIBRATION_STATE_SQL = ", ".join(f"'{state}'" for state in CALIBRATION_STATES)
_REGISTRY_LIFECYCLE_SQL = ", ".join(
    f"'{state}'" for state in REGISTRY_LIFECYCLE_STATES
)
_PRESSURE_REFERENCE_SQL = "'absolute', 'gauge'"
_ANALOG_INPUT_CLASS_SQL = ", ".join(f"'{value}'" for value in ANALOG_ELECTRICAL_INPUT_CLASSES)
_ANALOG_SCALING_POLICY_SQL = ", ".join(f"'{value}'" for value in ANALOG_SCALING_POLICIES)
_ANALOG_RANGE_POLICY_SQL = ", ".join(f"'{value}'" for value in ANALOG_RANGE_POLICIES)
_ANALOG_EVIDENCE_STATUS_SQL = ", ".join(f"'{value}'" for value in ANALOG_EVIDENCE_STATUSES)


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
        CheckConstraint(
            f"pressure_reference IS NULL OR pressure_reference IN ({_PRESSURE_REFERENCE_SQL})",
            name="ck_instruments_pressure_reference",
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
    pressure_reference: Mapped[str | None] = mapped_column(String(16), nullable=True)
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


class AnalogScalingProfileRecord(Base):
    __tablename__ = "instrument_analog_scaling_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "signal_id"],
            ["instrument_signals.organization_id", "instrument_signals.id"],
            name="fk_instrument_analog_scaling_signal",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "signal_id", "acquisition_source_id"],
            [
                "instrument_signal_acquisition_history.organization_id",
                "instrument_signal_acquisition_history.signal_id",
                "instrument_signal_acquisition_history.id",
            ],
            name="fk_instrument_analog_scaling_acquisition_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "signal_id",
            "revision",
            name="uq_instrument_analog_scaling_revision",
        ),
        UniqueConstraint(
            "organization_id",
            "signal_id",
            "id",
            name="uq_instrument_analog_scaling_identity",
        ),
        CheckConstraint(
            f"schema_version = '{ANALOG_SCALING_SCHEMA_VERSION}'",
            name="ck_instrument_analog_scaling_schema_version",
        ),
        CheckConstraint(
            f"electrical_input_class IN ({_ANALOG_INPUT_CLASS_SQL})",
            name="ck_instrument_analog_scaling_input_class",
        ),
        CheckConstraint(
            f"scaling_policy IN ({_ANALOG_SCALING_POLICY_SQL})",
            name="ck_instrument_analog_scaling_policy",
        ),
        CheckConstraint(
            f"under_range_policy IN ({_ANALOG_RANGE_POLICY_SQL})",
            name="ck_instrument_analog_scaling_under_range",
        ),
        CheckConstraint(
            f"over_range_policy IN ({_ANALOG_RANGE_POLICY_SQL})",
            name="ck_instrument_analog_scaling_over_range",
        ),
        CheckConstraint(
            f"evidence_status IN ({_ANALOG_EVIDENCE_STATUS_SQL})",
            name="ck_instrument_analog_scaling_evidence_status",
        ),
        CheckConstraint(
            "raw_min < raw_max",
            name="ck_instrument_analog_scaling_raw_domain",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_instrument_analog_scaling_revision_positive",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_instrument_analog_scaling_interval",
        ),
        CheckConstraint(
            "evidence_status <> 'hardware_verified' OR "
            "(acquisition_device_family IS NOT NULL AND acquisition_profile_id IS NOT NULL "
            "AND acquisition_profile_version IS NOT NULL AND acquisition_channel_reference IS NOT NULL "
            "AND evidence_reference IS NOT NULL)",
            name="ck_instrument_analog_scaling_hardware_provenance",
        ),
        Index(
            "ix_instrument_analog_scaling_as_of",
            "organization_id",
            "signal_id",
            "effective_from",
            "effective_to",
            "revision",
        ),
        Index(
            "uq_instrument_analog_scaling_open",
            "organization_id",
            "signal_id",
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
            name="fk_instrument_analog_scaling_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    signal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    electrical_input_class: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_min: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    raw_max: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    engineering_min: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    engineering_max: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    engineering_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    scaling_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    under_range_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    over_range_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    acquisition_device_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acquisition_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquisition_profile_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquisition_channel_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acquisition_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    calibration_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SignalAcquisitionSourceRecord(Base):
    __tablename__ = "instrument_signal_acquisition_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "signal_id"],
            ["instrument_signals.organization_id", "instrument_signals.id"],
            name="fk_instrument_signal_acquisition_signal",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "signal_id",
            "revision",
            name="uq_instrument_signal_acquisition_revision",
        ),
        UniqueConstraint(
            "organization_id",
            "signal_id",
            "id",
            name="uq_instrument_signal_acquisition_identity",
        ),
        CheckConstraint(
            f"schema_version = '{ACQUISITION_SOURCE_SCHEMA_VERSION}'",
            name="ck_instrument_signal_acquisition_schema_version",
        ),
        CheckConstraint(
            f"evidence_status IN ({_ANALOG_EVIDENCE_STATUS_SQL})",
            name="ck_instrument_signal_acquisition_evidence_status",
        ),
        CheckConstraint(
            "evidence_status <> 'hardware_verified' OR "
            "(evidence_reference IS NOT NULL AND trim(evidence_reference) <> '')",
            name="ck_instrument_signal_acquisition_hardware_evidence",
        ),
        CheckConstraint(
            "(acquisition_profile_id IS NULL AND acquisition_profile_version IS NULL) OR "
            "(acquisition_profile_id IS NOT NULL AND trim(acquisition_profile_id) <> '' "
            "AND acquisition_profile_version IS NOT NULL AND trim(acquisition_profile_version) <> '')",
            name="ck_instrument_signal_acquisition_profile_identity",
        ),
        CheckConstraint(
            "calibration_scope IS NULL OR trim(calibration_scope) <> ''",
            name="ck_instrument_signal_acquisition_calibration_scope",
        ),
        CheckConstraint(
            "revision >= 1", name="ck_instrument_signal_acquisition_revision_positive"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_instrument_signal_acquisition_interval",
        ),
        CheckConstraint(
            "trim(node_id) <> '' AND trim(equipment_id) <> '' AND "
            "trim(channel_id) <> '' AND trim(metric) <> '' AND trim(unit) <> ''",
            name="ck_instrument_signal_acquisition_identity_nonempty",
        ),
        Index(
            "ix_instrument_signal_acquisition_as_of",
            "organization_id",
            "signal_id",
            "valid_from",
            "valid_to",
            "revision",
        ),
        Index(
            "uq_instrument_signal_acquisition_open",
            "organization_id",
            "signal_id",
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
            name="fk_instrument_signal_acquisition_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    signal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    acquisition_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquisition_profile_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    calibration_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AcquisitionProfileAcceptanceRecord(Base):
    __tablename__ = "instrument_acquisition_profile_acceptance_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "signal_id", "acquisition_source_id"],
            [
                "instrument_signal_acquisition_history.organization_id",
                "instrument_signal_acquisition_history.signal_id",
                "instrument_signal_acquisition_history.id",
            ],
            name="fk_instrument_acquisition_profile_acceptance_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "signal_id", "scaling_profile_id"],
            [
                "instrument_analog_scaling_history.organization_id",
                "instrument_analog_scaling_history.signal_id",
                "instrument_analog_scaling_history.id",
            ],
            name="fk_instrument_acquisition_profile_acceptance_scaling_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id", "signal_id", "profile_target_key", "revision",
            name="uq_instrument_acquisition_profile_acceptance_revision",
        ),
        CheckConstraint(
            f"schema_version = '{ACCEPTANCE_SCHEMA_VERSION}'",
            name="ck_instrument_acquisition_profile_acceptance_schema_version",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_instrument_acquisition_profile_acceptance_revision_positive",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_instrument_acquisition_profile_acceptance_interval",
        ),
        CheckConstraint(
            "trim(profile_target_key) <> '' AND trim(acquisition_profile_id) <> '' "
            "AND trim(acquisition_profile_version) <> ''",
            name="ck_instrument_acquisition_profile_acceptance_identity",
        ),
        Index(
            "ix_instrument_acquisition_profile_acceptance_as_of",
            "organization_id", "signal_id", "profile_target_key",
            "effective_from", "effective_to", "revision",
        ),
        Index(
            "uq_instrument_acquisition_profile_acceptance_open",
            "organization_id", "signal_id", "profile_target_key",
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
            name="fk_instrument_acquisition_profile_acceptance_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    signal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    acquisition_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scaling_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    profile_target_key: Mapped[str] = mapped_column(String(160), nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ACCEPTANCE_SCHEMA_VERSION
    )
    acquisition_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    acquisition_profile_version: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_for_calculation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
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
