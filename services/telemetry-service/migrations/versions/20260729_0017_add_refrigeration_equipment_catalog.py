"""add organization-scoped refrigeration equipment catalog

Revision ID: 20260729_0017
Revises: 20260727_0016
Create Date: 2026-07-29 10:20:00
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from alembic import op
import sqlalchemy as sa

revision = "20260729_0017"
down_revision = "20260727_0016"
branch_labels = None
depends_on = None

DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "refrigeration_equipment",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("equipment_type", sa.String(length=128), nullable=False),
        sa.Column("manufacturer", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("serial_number", sa.String(length=128), nullable=False),
        sa.Column("temperature_class", sa.String(length=128), nullable=False),
        sa.Column("installed_at", sa.Date(), nullable=True),
        sa.Column("serviced_at", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="offline", nullable=False),
        sa.Column("average_temperature_c", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("min_temperature_c", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_temperature_c", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("online_sensors", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_sensors", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active_alarms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
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
        sa.Column("deleted_by", sa.String(length=128), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('normal', 'warning', 'alarm', 'offline')",
            name="ck_refrigeration_equipment_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_refrigeration_equipment_version_positive"),
        sa.CheckConstraint(
            "online_sensors >= 0",
            name="ck_refrigeration_equipment_online_non_negative",
        ),
        sa.CheckConstraint(
            "total_sensors >= 0",
            name="ck_refrigeration_equipment_total_non_negative",
        ),
        sa.CheckConstraint(
            "online_sensors <= total_sensors",
            name="ck_refrigeration_equipment_online_within_total",
        ),
        sa.CheckConstraint(
            "active_alarms >= 0",
            name="ck_refrigeration_equipment_alarms_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_refrigeration_equipment_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_refrigeration_equipment_organization_code",
        ),
    )
    op.create_index(
        "ix_refrigeration_equipment_active",
        "refrigeration_equipment",
        ["organization_id", "deleted_at", "status", "name"],
    )
    _seed_default_catalog()


def _seed_default_catalog() -> None:
    table = sa.table(
        "refrigeration_equipment",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("location", sa.String()),
        sa.column("equipment_type", sa.String()),
        sa.column("manufacturer", sa.String()),
        sa.column("model", sa.String()),
        sa.column("serial_number", sa.String()),
        sa.column("temperature_class", sa.String()),
        sa.column("installed_at", sa.Date()),
        sa.column("serviced_at", sa.Date()),
        sa.column("status", sa.String()),
        sa.column("average_temperature_c", sa.Float()),
        sa.column("min_temperature_c", sa.Float()),
        sa.column("max_temperature_c", sa.Float()),
        sa.column("online_sensors", sa.Integer()),
        sa.column("total_sensors", sa.Integer()),
        sa.column("active_alarms", sa.Integer()),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("version", sa.Integer()),
        sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        table,
        [
            {
                "id": "showcase-106-01",
                "organization_id": DEFAULT_ORGANIZATION_ID,
                "code": "CS-P1250-2024-106-01",
                "name": "Вітрина №106-01",
                "location": "Лабораторія 1 · Зона A",
                "equipment_type": "Холодильна вітрина",
                "manufacturer": "ColdStream",
                "model": "Premium 1250",
                "serial_number": "X-PROD-10601",
                "temperature_class": "3M1 (0…+5 °C)",
                "installed_at": date(2025, 5, 15),
                "serviced_at": date(2026, 7, 12),
                "status": "normal",
                "average_temperature_c": 2.2,
                "min_temperature_c": 1.1,
                "max_temperature_c": 6.4,
                "online_sensors": 48,
                "total_sensors": 48,
                "active_alarms": 1,
                "last_seen_at": datetime(2026, 7, 24, 14, 23, 45, tzinfo=UTC),
                "version": 1,
                "created_by": "migration-bootstrap",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "showcase-107-02",
                "organization_id": DEFAULT_ORGANIZATION_ID,
                "code": "CS-P900-2024-107-02",
                "name": "Вітрина №107-02",
                "location": "Лабораторія 1 · Зона B",
                "equipment_type": "Холодильна вітрина",
                "manufacturer": "ColdStream",
                "model": "Compact 900",
                "serial_number": "X-PROD-10702",
                "temperature_class": "3M2 (-1…+7 °C)",
                "installed_at": date(2025, 6, 2),
                "serviced_at": date(2026, 6, 28),
                "status": "warning",
                "average_temperature_c": 4.8,
                "min_temperature_c": 2.4,
                "max_temperature_c": 8.1,
                "online_sensors": 22,
                "total_sensors": 24,
                "active_alarms": 2,
                "last_seen_at": datetime(2026, 7, 24, 14, 21, 19, tzinfo=UTC),
                "version": 1,
                "created_by": "migration-bootstrap",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "cold-room-201",
                "organization_id": DEFAULT_ORGANIZATION_ID,
                "code": "CR-2024-201",
                "name": "Холодильна камера №201",
                "location": "Лабораторія 2 · Північна стіна",
                "equipment_type": "Холодильна камера",
                "manufacturer": "NEXOTHERM",
                "model": "CR-12",
                "serial_number": "NX-CR-00201",
                "temperature_class": "2L1 (-18…-15 °C)",
                "installed_at": date(2025, 8, 9),
                "serviced_at": date(2026, 7, 3),
                "status": "normal",
                "average_temperature_c": -17.2,
                "min_temperature_c": -18.4,
                "max_temperature_c": -15.9,
                "online_sensors": 16,
                "total_sensors": 16,
                "active_alarms": 0,
                "last_seen_at": datetime(2026, 7, 24, 14, 23, 30, tzinfo=UTC),
                "version": 1,
                "created_by": "migration-bootstrap",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_refrigeration_equipment_active", table_name="refrigeration_equipment")
    op.drop_table("refrigeration_equipment")
