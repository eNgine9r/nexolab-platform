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


_SCAN_STATUSES = "'running', 'completed', 'cancelled', 'failed'"
_CANDIDATE_LIFECYCLES = "'new', 'reviewed', 'matched_existing', 'adopted', 'ignored', 'disappeared'"
_ASSET_STATUSES = "'active', 'inactive'"


class EquipmentDiscoveryScan(Base):
    __tablename__ = "equipment_discovery_scans"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_equipment_discovery_scans_organization_id"),
        CheckConstraint(f"status IN ({_SCAN_STATUSES})", name="ck_equipment_discovery_scans_status"),
        CheckConstraint("host_budget >= 1", name="ck_equipment_discovery_scans_host_budget"),
        CheckConstraint("probe_budget >= 1", name="ck_equipment_discovery_scans_probe_budget"),
        CheckConstraint("hosts_considered >= 0", name="ck_equipment_discovery_scans_hosts_considered"),
        CheckConstraint("probes_attempted >= 0", name="ck_equipment_discovery_scans_probes_attempted"),
        CheckConstraint("responsive_hosts >= 0", name="ck_equipment_discovery_scans_responsive_hosts"),
        CheckConstraint("duration_ms >= 0", name="ck_equipment_discovery_scans_duration_ms"),
        CheckConstraint("process_cpu_ms >= 0", name="ck_equipment_discovery_scans_process_cpu_ms"),
        CheckConstraint("network_connect_attempts >= 0", name="ck_equipment_discovery_scans_network_connect_attempts"),
        CheckConstraint("network_payload_bytes = 0", name="ck_equipment_discovery_scans_zero_payload"),
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="ck_equipment_discovery_scans_trigger"),
        Index(
            "ix_equipment_discovery_scans_organization_started",
            "organization_id",
            "started_at",
            "id",
        ),
        Index(
            "uq_equipment_discovery_scans_running_organization",
            "organization_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_equipment_discovery_scans_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_cidrs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    requested_ports: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    host_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    probe_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    hosts_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    probes_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    responsive_hosts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    process_cpu_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    network_connect_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    network_payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    new_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    changed_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    disappeared_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class EquipmentDiscoveryCandidate(Base):
    __tablename__ = "equipment_discovery_candidates"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_equipment_discovery_candidates_organization_id"),
        UniqueConstraint(
            "organization_id",
            "candidate_key",
            name="uq_equipment_discovery_candidates_organization_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "last_scan_id"],
            ["equipment_discovery_scans.organization_id", "equipment_discovery_scans.id"],
            name="fk_equipment_discovery_candidates_last_scan",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"lifecycle IN ({_CANDIDATE_LIFECYCLES})",
            name="ck_equipment_discovery_candidates_lifecycle",
        ),
        CheckConstraint("version >= 1", name="ck_equipment_discovery_candidates_version"),
        Index(
            "ix_equipment_discovery_candidates_inbox",
            "organization_id",
            "present",
            "lifecycle",
            "last_seen_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_equipment_discovery_candidates_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    candidate_key: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_interface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_subnet: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False, default="new", server_default="new")
    present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_scan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    linked_equipment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))


class EquipmentDiscoveryObservation(Base):
    __tablename__ = "equipment_discovery_observations"
    __table_args__ = (
        UniqueConstraint(
            "scan_id",
            "candidate_id",
            name="uq_equipment_discovery_observations_scan_candidate",
        ),
        ForeignKeyConstraint(
            ["organization_id", "scan_id"],
            ["equipment_discovery_scans.organization_id", "equipment_discovery_scans.id"],
            name="fk_equipment_discovery_observations_scan",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["equipment_discovery_candidates.organization_id", "equipment_discovery_candidates.id"],
            name="fk_equipment_discovery_observations_candidate",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_equipment_discovery_observations_candidate_time",
            "organization_id",
            "candidate_id",
            "observed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_interface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_subnet: Mapped[str] = mapped_column(String(64), nullable=False)
    services: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class EquipmentNetworkAsset(Base):
    __tablename__ = "equipment_network_assets"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "asset_key",
            name="uq_equipment_network_assets_organization_key",
        ),
        UniqueConstraint(
            "organization_id",
            "source_candidate_id",
            name="uq_equipment_network_assets_source_candidate",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_candidate_id"],
            ["equipment_discovery_candidates.organization_id", "equipment_discovery_candidates.id"],
            name="fk_equipment_network_assets_candidate",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN ({_ASSET_STATUSES})", name="ck_equipment_network_assets_status"),
        CheckConstraint("version >= 1", name="ck_equipment_network_assets_version"),
        Index(
            "ix_equipment_network_assets_organization_status",
            "organization_id",
            "status",
            "display_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_equipment_network_assets_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    asset_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
