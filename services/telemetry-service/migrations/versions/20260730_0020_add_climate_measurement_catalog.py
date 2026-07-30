"""add climate chamber measurement catalog

Revision ID: 20260730_0020
Revises: 20260729_0019
Create Date: 2026-07-30 11:15:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260730_0020"
down_revision = "20260729_0019"
branch_labels = None
depends_on = None

CATALOG_STATUSES = "'active', 'inactive'"
DEVICE_TYPES = "'temperature_controller', 'energy_meter'"
CONNECTION_STATUSES = "'unknown', 'connected', 'disconnected'"
CALIBRATION_STATUSES = "'untracked', 'current', 'due', 'expired'"
SENSOR_POSITIONS = "'A', 'B'"


def upgrade() -> None:
    op.create_table(
        "climate_chambers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({CATALOG_STATUSES})",
            name="ck_climate_chambers_status",
        ),
        sa.CheckConstraint(
            "display_order >= 1",
            name="ck_climate_chambers_display_order_positive",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_climate_chambers_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_climate_chambers_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "node_id"],
            ["central_nodes.organization_id", "central_nodes.node_id"],
            name="fk_climate_chambers_central_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_climate_chambers_organization_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_climate_chambers_organization_code",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "node_id",
            name="uq_climate_chambers_organization_node",
        ),
    )
    op.create_index(
        "ix_climate_chambers_organization_order",
        "climate_chambers",
        ["organization_id", "status", "display_order", "code"],
    )

    op.create_table(
        "measurement_devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("climate_chamber_id", sa.String(length=36), nullable=False),
        sa.Column("business_key", sa.String(length=128), nullable=False),
        sa.Column("device_type", sa.String(length=32), nullable=False),
        sa.Column("manufacturer", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("designation", sa.String(length=32), nullable=True),
        sa.Column(
            "connection_status",
            sa.String(length=16),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("measured_parameters", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"device_type IN ({DEVICE_TYPES})",
            name="ck_measurement_devices_type",
        ),
        sa.CheckConstraint(
            f"connection_status IN ({CONNECTION_STATUSES})",
            name="ck_measurement_devices_connection_status",
        ),
        sa.CheckConstraint(
            f"status IN ({CATALOG_STATUSES})",
            name="ck_measurement_devices_status",
        ),
        sa.CheckConstraint(
            "unit_id >= 1",
            name="ck_measurement_devices_unit_id_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_measurement_devices_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "climate_chamber_id"],
            ["climate_chambers.organization_id", "climate_chambers.id"],
            name="fk_measurement_devices_chamber",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_measurement_devices_organization_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "business_key",
            name="uq_measurement_devices_organization_key",
        ),
        sa.UniqueConstraint(
            "climate_chamber_id",
            "device_type",
            "unit_id",
            name="uq_measurement_devices_chamber_type_unit",
        ),
    )
    op.create_index(
        "ix_measurement_devices_chamber_type_unit",
        "measurement_devices",
        ["organization_id", "climate_chamber_id", "device_type", "unit_id"],
    )

    op.create_table(
        "measurement_channels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("climate_chamber_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("channel_number", sa.Integer(), nullable=False),
        sa.Column("logical_sensor_number", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("physical_sensor_count", sa.Integer(), nullable=False),
        sa.Column("metric_type", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel_number BETWEEN 1 AND 6",
            name="ck_measurement_channels_channel_number",
        ),
        sa.CheckConstraint(
            "logical_sensor_number >= 1",
            name="ck_measurement_channels_sensor_number_positive",
        ),
        sa.CheckConstraint(
            "physical_sensor_count BETWEEN 1 AND 2",
            name="ck_measurement_channels_physical_sensor_count",
        ),
        sa.CheckConstraint(
            f"status IN ({CATALOG_STATUSES})",
            name="ck_measurement_channels_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_measurement_channels_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "climate_chamber_id"],
            ["climate_chambers.organization_id", "climate_chambers.id"],
            name="fk_measurement_channels_chamber",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["measurement_devices.organization_id", "measurement_devices.id"],
            name="fk_measurement_channels_device",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_measurement_channels_organization_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "channel_id",
            name="uq_measurement_channels_organization_channel",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "logical_sensor_number",
            name="uq_measurement_channels_organization_sensor_number",
        ),
        sa.UniqueConstraint(
            "device_id",
            "channel_number",
            name="uq_measurement_channels_device_channel",
        ),
    )
    op.create_index(
        "ix_measurement_channels_chamber_sort",
        "measurement_channels",
        ["organization_id", "climate_chamber_id", "device_id", "channel_number"],
    )

    op.create_table(
        "physical_sensors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("climate_chamber_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("sensor_position", sa.String(length=1), nullable=False),
        sa.Column("inventory_number", sa.String(length=32), nullable=False),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column(
            "calibration_status",
            sa.String(length=16),
            server_default=sa.text("'untracked'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"sensor_position IN ({SENSOR_POSITIONS})",
            name="ck_physical_sensors_position",
        ),
        sa.CheckConstraint(
            f"calibration_status IN ({CALIBRATION_STATUSES})",
            name="ck_physical_sensors_calibration_status",
        ),
        sa.CheckConstraint(
            f"status IN ({CATALOG_STATUSES})",
            name="ck_physical_sensors_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_physical_sensors_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "climate_chamber_id"],
            ["climate_chambers.organization_id", "climate_chambers.id"],
            name="fk_physical_sensors_chamber",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "channel_id"],
            ["measurement_channels.organization_id", "measurement_channels.id"],
            name="fk_physical_sensors_channel",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "inventory_number",
            name="uq_physical_sensors_organization_inventory",
        ),
        sa.UniqueConstraint(
            "channel_id",
            "sensor_position",
            name="uq_physical_sensors_channel_position",
        ),
    )
    op.create_index(
        "ix_physical_sensors_chamber_channel",
        "physical_sensors",
        ["organization_id", "climate_chamber_id", "channel_id", "sensor_position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_physical_sensors_chamber_channel",
        table_name="physical_sensors",
    )
    op.drop_table("physical_sensors")
    op.drop_index(
        "ix_measurement_channels_chamber_sort",
        table_name="measurement_channels",
    )
    op.drop_table("measurement_channels")
    op.drop_index(
        "ix_measurement_devices_chamber_type_unit",
        table_name="measurement_devices",
    )
    op.drop_table("measurement_devices")
    op.drop_index(
        "ix_climate_chambers_organization_order",
        table_name="climate_chambers",
    )
    op.drop_table("climate_chambers")
