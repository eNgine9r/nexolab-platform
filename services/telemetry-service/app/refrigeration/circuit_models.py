from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


CIRCUIT_LIFECYCLE_STATES = ("active", "inactive", "retired")
CIRCUIT_PROCESS_ROLES = (
    "suction_pressure",
    "condensing_pressure",
    "suction_line_temperature",
    "liquid_line_temperature",
    "atmospheric_pressure",
    "relative_humidity",
)
_LIFECYCLE_SQL = ", ".join(f"'{item}'" for item in CIRCUIT_LIFECYCLE_STATES)
_ROLE_SQL = ", ".join(f"'{item}'" for item in CIRCUIT_PROCESS_ROLES)


class RefrigerationCircuit(Base):
    __tablename__ = "refrigeration_circuits"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "id", name="uq_refrigeration_circuits_organization_id"
        ),
        UniqueConstraint(
            "organization_id",
            "business_key",
            name="uq_refrigeration_circuits_organization_business_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_refrigeration_circuits_equipment",
            ondelete="RESTRICT",
        ),
        CheckConstraint("trim(business_key) <> ''", name="ck_refrigeration_circuits_business_key"),
        CheckConstraint("trim(display_name) <> ''", name="ck_refrigeration_circuits_display_name"),
        Index(
            "ix_refrigeration_circuits_equipment",
            "organization_id",
            "equipment_id",
            "business_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_refrigeration_circuits_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    equipment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefrigerationCircuitLifecycleRecord(Base):
    __tablename__ = "refrigeration_circuit_lifecycle_history"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "circuit_id",
            "revision",
            name="uq_refrigeration_circuit_lifecycle_revision",
        ),
        ForeignKeyConstraint(
            ["organization_id", "circuit_id"],
            ["refrigeration_circuits.organization_id", "refrigeration_circuits.id"],
            name="fk_refrigeration_circuit_lifecycle_circuit",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"state IN ({_LIFECYCLE_SQL})", name="ck_refrigeration_circuit_lifecycle_state"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_refrigeration_circuit_lifecycle_interval",
        ),
        CheckConstraint("revision >= 1", name="ck_refrigeration_circuit_lifecycle_revision"),
        Index(
            "ix_refrigeration_circuit_lifecycle_as_of",
            "organization_id",
            "circuit_id",
            "valid_from",
            "valid_to",
            "revision",
        ),
        Index(
            "uq_refrigeration_circuit_lifecycle_open",
            "organization_id",
            "circuit_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    circuit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefrigerationCircuitConfigurationRecord(Base):
    __tablename__ = "refrigeration_circuit_configuration_history"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "circuit_id",
            "revision",
            name="uq_refrigeration_circuit_configuration_revision",
        ),
        ForeignKeyConstraint(
            ["organization_id", "circuit_id"],
            ["refrigeration_circuits.organization_id", "refrigeration_circuits.id"],
            name="fk_refrigeration_circuit_configuration_circuit",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "schema_version = 'refrigeration-circuit-configuration/v1'",
            name="ck_refrigeration_circuit_configuration_schema",
        ),
        CheckConstraint("trim(refrigerant_code) <> ''", name="ck_refrigeration_circuit_refrigerant"),
        CheckConstraint(
            "trim(calculation_policy_version) <> ''",
            name="ck_refrigeration_circuit_calculation_policy",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_refrigeration_circuit_configuration_interval",
        ),
        CheckConstraint("revision >= 1", name="ck_refrigeration_circuit_configuration_revision"),
        Index(
            "ix_refrigeration_circuit_configuration_as_of",
            "organization_id",
            "circuit_id",
            "valid_from",
            "valid_to",
            "revision",
        ),
        Index(
            "uq_refrigeration_circuit_configuration_open",
            "organization_id",
            "circuit_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    circuit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    refrigerant_code: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    property_provider_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefrigerationCircuitSignalBinding(Base):
    __tablename__ = "refrigeration_circuit_signal_bindings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "circuit_id",
            "role",
            "revision",
            name="uq_refrigeration_circuit_signal_binding_revision",
        ),
        ForeignKeyConstraint(
            ["organization_id", "circuit_id"],
            ["refrigeration_circuits.organization_id", "refrigeration_circuits.id"],
            name="fk_refrigeration_circuit_signal_binding_circuit",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "signal_id"],
            ["instrument_signals.organization_id", "instrument_signals.id"],
            name="fk_refrigeration_circuit_signal_binding_signal",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"role IN ({_ROLE_SQL})", name="ck_refrigeration_circuit_signal_binding_role"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_refrigeration_circuit_signal_binding_interval",
        ),
        CheckConstraint("revision >= 1", name="ck_refrigeration_circuit_signal_binding_revision"),
        Index(
            "ix_refrigeration_circuit_signal_binding_as_of",
            "organization_id",
            "circuit_id",
            "role",
            "valid_from",
            "valid_to",
            "revision",
        ),
        Index(
            "uq_refrigeration_circuit_signal_binding_open",
            "organization_id",
            "circuit_id",
            "role",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    circuit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    signal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
