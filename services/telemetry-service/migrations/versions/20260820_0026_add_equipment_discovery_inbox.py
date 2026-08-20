"""add read-only LOCAL_LAN equipment discovery inbox

Revision ID: 20260820_0026
Revises: 20260819_0025
Create Date: 2026-08-20 08:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260820_0026"
down_revision = "20260819_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_discovery_scans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_cidrs", sa.JSON(), nullable=False),
        sa.Column("requested_ports", sa.JSON(), nullable=False),
        sa.Column("host_budget", sa.Integer(), nullable=False),
        sa.Column("probe_budget", sa.Integer(), nullable=False),
        sa.Column("hosts_considered", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("probes_attempted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("responsive_hosts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("process_cpu_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("network_connect_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("network_payload_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("trigger", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("new_candidates", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("changed_candidates", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("disappeared_candidates", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.CheckConstraint("status IN ('running', 'completed', 'cancelled', 'failed')", name="ck_equipment_discovery_scans_status"),
        sa.CheckConstraint("host_budget >= 1", name="ck_equipment_discovery_scans_host_budget"),
        sa.CheckConstraint("probe_budget >= 1", name="ck_equipment_discovery_scans_probe_budget"),
        sa.CheckConstraint("hosts_considered >= 0", name="ck_equipment_discovery_scans_hosts_considered"),
        sa.CheckConstraint("probes_attempted >= 0", name="ck_equipment_discovery_scans_probes_attempted"),
        sa.CheckConstraint("responsive_hosts >= 0", name="ck_equipment_discovery_scans_responsive_hosts"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_equipment_discovery_scans_duration_ms"),
        sa.CheckConstraint("process_cpu_ms >= 0", name="ck_equipment_discovery_scans_process_cpu_ms"),
        sa.CheckConstraint("network_connect_attempts >= 0", name="ck_equipment_discovery_scans_network_connect_attempts"),
        sa.CheckConstraint("network_payload_bytes = 0", name="ck_equipment_discovery_scans_zero_payload"),
        sa.CheckConstraint("trigger IN ('manual', 'scheduled')", name="ck_equipment_discovery_scans_trigger"),
        sa.ForeignKeyConstraint(["organization_id"], ["security_organizations.id"], name="fk_equipment_discovery_scans_organization", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_equipment_discovery_scans_organization_id"),
    )
    op.create_index("ix_equipment_discovery_scans_organization_started", "equipment_discovery_scans", ["organization_id", "started_at", "id"], unique=False)
    op.create_index("uq_equipment_discovery_scans_running_organization", "equipment_discovery_scans", ["organization_id"], unique=True, postgresql_where=sa.text("status = 'running'"))

    op.create_table(
        "equipment_discovery_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_key", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("mac_address", sa.String(length=32), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("source_interface", sa.String(length=64), nullable=True),
        sa.Column("source_subnet", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("present", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_scan_id", sa.String(length=36), nullable=False),
        sa.Column("linked_equipment_key", sa.String(length=255), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("lifecycle IN ('new', 'reviewed', 'matched_existing', 'adopted', 'ignored', 'disappeared')", name="ck_equipment_discovery_candidates_lifecycle"),
        sa.CheckConstraint("version >= 1", name="ck_equipment_discovery_candidates_version"),
        sa.ForeignKeyConstraint(["organization_id"], ["security_organizations.id"], name="fk_equipment_discovery_candidates_organization", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id", "last_scan_id"], ["equipment_discovery_scans.organization_id", "equipment_discovery_scans.id"], name="fk_equipment_discovery_candidates_last_scan", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_equipment_discovery_candidates_organization_id"),
        sa.UniqueConstraint("organization_id", "candidate_key", name="uq_equipment_discovery_candidates_organization_key"),
    )
    op.create_index("ix_equipment_discovery_candidates_inbox", "equipment_discovery_candidates", ["organization_id", "present", "lifecycle", "last_seen_at"], unique=False)

    op.create_table(
        "equipment_discovery_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("scan_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("mac_address", sa.String(length=32), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("source_interface", sa.String(length=64), nullable=True),
        sa.Column("source_subnet", sa.String(length=64), nullable=False),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "candidate_id"], ["equipment_discovery_candidates.organization_id", "equipment_discovery_candidates.id"], name="fk_equipment_discovery_observations_candidate", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id", "scan_id"], ["equipment_discovery_scans.organization_id", "equipment_discovery_scans.id"], name="fk_equipment_discovery_observations_scan", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "candidate_id", name="uq_equipment_discovery_observations_scan_candidate"),
    )
    op.create_index("ix_equipment_discovery_observations_candidate_time", "equipment_discovery_observations", ["organization_id", "candidate_id", "observed_at"], unique=False)

    op.create_table(
        "equipment_network_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("asset_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("mac_address", sa.String(length=32), nullable=True),
        sa.Column("manufacturer", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("source_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_equipment_network_assets_status"),
        sa.CheckConstraint("version >= 1", name="ck_equipment_network_assets_version"),
        sa.ForeignKeyConstraint(["organization_id"], ["security_organizations.id"], name="fk_equipment_network_assets_organization", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id", "source_candidate_id"], ["equipment_discovery_candidates.organization_id", "equipment_discovery_candidates.id"], name="fk_equipment_network_assets_candidate", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "asset_key", name="uq_equipment_network_assets_organization_key"),
        sa.UniqueConstraint("organization_id", "source_candidate_id", name="uq_equipment_network_assets_source_candidate"),
    )
    op.create_index("ix_equipment_network_assets_organization_status", "equipment_network_assets", ["organization_id", "status", "display_name"], unique=False)

    op.execute(
        """
        CREATE FUNCTION reject_equipment_discovery_observation_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'equipment discovery observations are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_equipment_discovery_observations_immutable
        BEFORE UPDATE OR DELETE ON equipment_discovery_observations
        FOR EACH ROW EXECUTE FUNCTION reject_equipment_discovery_observation_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_equipment_discovery_observations_immutable ON equipment_discovery_observations")
    op.execute("DROP FUNCTION IF EXISTS reject_equipment_discovery_observation_mutation()")
    op.drop_index("ix_equipment_network_assets_organization_status", table_name="equipment_network_assets")
    op.drop_table("equipment_network_assets")
    op.drop_index("ix_equipment_discovery_observations_candidate_time", table_name="equipment_discovery_observations")
    op.drop_table("equipment_discovery_observations")
    op.drop_index("ix_equipment_discovery_candidates_inbox", table_name="equipment_discovery_candidates")
    op.drop_table("equipment_discovery_candidates")
    op.drop_index("uq_equipment_discovery_scans_running_organization", table_name="equipment_discovery_scans")
    op.drop_index("ix_equipment_discovery_scans_organization_started", table_name="equipment_discovery_scans")
    op.drop_table("equipment_discovery_scans")
