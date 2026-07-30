from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
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


_CATALOG_STATUSES = "'active', 'inactive'"
_DEVICE_TYPES = "'temperature_controller', 'energy_meter'"
_CONNECTION_STATUSES = "'unknown', 'connected', 'disconnected'"
_CALIBRATION_STATUSES = "'untracked', 'current', 'due', 'expired'"
_SENSOR_POSITIONS = "'A', 'B'"


class ClimateChamber(Base):
    __tablename__ = "climate_chambers"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_climate_chambers_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_climate_chambers_organization_code",
        ),
        UniqueConstraint(
            "organization_id",
            "node_id",
            name="uq_climate_chambers_organization_node",
        ),
        ForeignKeyConstraint(
            ["organization_id", "node_id"],
            ["central_nodes.organization_id", "central_nodes.node_id"],
            name="fk_climate_chambers_central_node",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"status IN ({_CATALOG_STATUSES})",
            name="ck_climate_chambers_status",
        ),
        CheckConstraint(
            "display_order >= 1",
            name="ck_climate_chambers_display_order_positive",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_climate_chambers_version_positive",
        ),
        Index(
            "ix_climate_chambers_organization_order",
            "organization_id",
            "status",
            "display_order",
            "code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_climate_chambers_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MeasurementDevice(Base):
    __tablename__ = "measurement_devices"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_measurement_devices_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "business_key",
            name="uq_measurement_devices_organization_key",
        ),
        UniqueConstraint(
            "climate_chamber_id",
            "device_type",
            "unit_id",
            name="uq_measurement_devices_chamber_type_unit",
        ),
        ForeignKeyConstraint(
            ["organization_id", "climate_chamber_id"],
            ["climate_chambers.organization_id", "climate_chambers.id"],
            name="fk_measurement_devices_chamber",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"device_type IN ({_DEVICE_TYPES})",
            name="ck_measurement_devices_type",
        ),
        CheckConstraint(
            f"connection_status IN ({_CONNECTION_STATUSES})",
            name="ck_measurement_devices_connection_status",
        ),
        CheckConstraint(
            f"status IN ({_CATALOG_STATUSES})",
            name="ck_measurement_devices_status",
        ),
        CheckConstraint(
            "unit_id >= 1",
            name="ck_measurement_devices_unit_id_positive",
        ),
        Index(
            "ix_measurement_devices_chamber_type_unit",
            "organization_id",
            "climate_chamber_id",
            "device_type",
            "unit_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_measurement_devices_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    climate_chamber_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_key: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    connection_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    measured_parameters: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MeasurementChannel(Base):
    __tablename__ = "measurement_channels"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_measurement_channels_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "channel_id",
            name="uq_measurement_channels_organization_channel",
        ),
        UniqueConstraint(
            "organization_id",
            "logical_sensor_number",
            name="uq_measurement_channels_organization_sensor_number",
        ),
        UniqueConstraint(
            "device_id",
            "channel_number",
            name="uq_measurement_channels_device_channel",
        ),
        ForeignKeyConstraint(
            ["organization_id", "climate_chamber_id"],
            ["climate_chambers.organization_id", "climate_chambers.id"],
            name="fk_measurement_channels_chamber",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["measurement_devices.organization_id", "measurement_devices.id"],
            name="fk_measurement_channels_device",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "channel_number BETWEEN 1 AND 6",
            name="ck_measurement_channels_channel_number",
        ),
        CheckConstraint(
            "logical_sensor_number >= 1",
            name="ck_measurement_channels_sensor_number_positive",
        ),
        CheckConstraint(
            "physical_sensor_count BETWEEN 1 AND 2",
            name="ck_measurement_channels_physical_sensor_count",
        ),
        CheckConstraint(
            f"status IN ({_CATALOG_STATUSES})",
            name="ck_measurement_channels_status",
        ),
        Index(
            "ix_measurement_channels_chamber_sort",
            "organization_id",
            "climate_chamber_id",
            "device_id",
            "channel_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_measurement_channels_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    climate_chamber_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_number: Mapped[int] = mapped_column(Integer, nullable=False)
    logical_sensor_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    physical_sensor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PhysicalSensor(Base):
    __tablename__ = "physical_sensors"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "inventory_number",
            name="uq_physical_sensors_organization_inventory",
        ),
        UniqueConstraint(
            "channel_id",
            "sensor_position",
            name="uq_physical_sensors_channel_position",
        ),
        ForeignKeyConstraint(
            ["organization_id", "climate_chamber_id"],
            ["climate_chambers.organization_id", "climate_chambers.id"],
            name="fk_physical_sensors_chamber",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "channel_id"],
            ["measurement_channels.organization_id", "measurement_channels.id"],
            name="fk_physical_sensors_channel",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"sensor_position IN ({_SENSOR_POSITIONS})",
            name="ck_physical_sensors_position",
        ),
        CheckConstraint(
            f"calibration_status IN ({_CALIBRATION_STATUSES})",
            name="ck_physical_sensors_calibration_status",
        ),
        CheckConstraint(
            f"status IN ({_CATALOG_STATUSES})",
            name="ck_physical_sensors_status",
        ),
        Index(
            "ix_physical_sensors_chamber_channel",
            "organization_id",
            "climate_chamber_id",
            "channel_id",
            "sensor_position",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_physical_sensors_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    climate_chamber_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sensor_position: Mapped[str] = mapped_column(String(1), nullable=False)
    inventory_number: Mapped[str] = mapped_column(String(32), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    calibration_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="untracked",
        server_default="untracked",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
