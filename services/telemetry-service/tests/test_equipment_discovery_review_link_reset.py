from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.models import MeasurementDevice
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database
from app.equipment_discovery.repository import EquipmentDiscoveryRepository
from app.equipment_discovery.scanner import DiscoveryObservationInput, DiscoveryScanResult
from app.model_registry import register_models
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def audit(action: str, entity_type: str, entity_id: str) -> AuditEventInput:
    return AuditEventInput(
        organization_id=ORGANIZATION_ID,
        actor_identity_id=None,
        actor_subject="engineer",
        actor_roles=frozenset({Role.ENGINEER}),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def observation() -> DiscoveryObservationInput:
    return DiscoveryObservationInput(
        ip_address="192.168.50.2",
        mac_address=None,
        hostname=None,
        source_interface=None,
        source_subnet="192.168.50.0/29",
        services=(
            {
                "port": 443,
                "transport": "tcp",
                "service": "https",
                "evidence": "connect_succeeded",
            },
        ),
        evidence={
            "neighbor_table": False,
            "tcp_connect_only": True,
            "payload_bytes_sent": 0,
            "open_ports": [443],
        },
        observed_at=datetime.now(UTC),
        fingerprint_sha256="a" * 64,
    )


def start_scan(repository: EquipmentDiscoveryRepository) -> str:
    record = repository.start_scan(
        organization_id=ORGANIZATION_ID,
        requested_cidrs=("192.168.50.0/29",),
        requested_ports=(443,),
        host_budget=6,
        probe_budget=6,
        actor_subject="engineer",
        audit_event=audit("equipment_discovery.scan_started", "equipment_discovery_scan", "pending"),
    )
    return record.id


def test_review_clears_canonical_link_and_reappearance_does_not_restore_match(tmp_path: Path) -> None:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'discovery-review.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Lab",
    )
    PostgresClimateCatalogRepository(database, security_repository=security).seed_default_catalog(
        organization_id=ORGANIZATION_ID
    )
    repository = EquipmentDiscoveryRepository(database, security_repository=security)

    first_scan_id = start_scan(repository)
    repository.apply_scan_result(
        first_scan_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(
            observations=(observation(),),
            hosts_considered=6,
            probes_attempted=6,
        ),
    )
    candidate = repository.list_candidates(organization_id=ORGANIZATION_ID)[0]

    with Session(database.engine) as session:
        device = session.scalar(
            select(MeasurementDevice)
            .where(MeasurementDevice.organization_id == ORGANIZATION_ID)
            .limit(1)
        )
    assert device is not None
    equipment_key = f"device:{device.id}"

    linked, _ = repository.act_on_candidate(
        candidate.id,
        organization_id=ORGANIZATION_ID,
        expected_version=candidate.version,
        action="link_existing",
        actor_subject="engineer",
        display_name=None,
        linked_equipment_key=equipment_key,
        audit_event=audit(
            "equipment_discovery.candidate_link_existing",
            "equipment_discovery_candidate",
            candidate.id,
        ),
    )
    assert linked.lifecycle == "matched_existing"
    assert linked.linked_equipment_key == equipment_key

    reviewed, _ = repository.act_on_candidate(
        candidate.id,
        organization_id=ORGANIZATION_ID,
        expected_version=linked.version,
        action="review",
        actor_subject="engineer",
        display_name=None,
        linked_equipment_key=None,
        audit_event=audit(
            "equipment_discovery.candidate_review",
            "equipment_discovery_candidate",
            candidate.id,
        ),
    )
    assert reviewed.lifecycle == "reviewed"
    assert reviewed.linked_equipment_key is None

    absent_scan_id = start_scan(repository)
    repository.apply_scan_result(
        absent_scan_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(observations=(), hosts_considered=6, probes_attempted=6),
    )
    disappeared = repository.list_candidates(organization_id=ORGANIZATION_ID)[0]
    assert disappeared.lifecycle == "disappeared"
    assert disappeared.linked_equipment_key is None

    return_scan_id = start_scan(repository)
    repository.apply_scan_result(
        return_scan_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(
            observations=(observation(),),
            hosts_considered=6,
            probes_attempted=6,
        ),
    )
    returned = repository.list_candidates(organization_id=ORGANIZATION_ID)[0]
    assert returned.lifecycle == "new"
    assert returned.linked_equipment_key is None
