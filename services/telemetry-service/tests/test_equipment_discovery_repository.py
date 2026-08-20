from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.climate_catalog.models import MeasurementDevice
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database
from app.equipment_discovery.api import create_equipment_discovery_router
from app.equipment_discovery.models import (
    EquipmentDiscoveryObservation,
    EquipmentNetworkAsset,
)
from app.equipment_discovery.policy import DiscoveryPolicy
from app.equipment_discovery.repository import EquipmentDiscoveryRepository
from app.equipment_discovery.scanner import DiscoveryObservationInput, DiscoveryScanResult
from app.model_registry import register_models
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository
from app.config import Settings


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def headers(subject: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": ORGANIZATION_ID,
    }


class StubDiscoveryService:
    def __init__(self, policy: DiscoveryPolicy) -> None:
        self.policy = policy
        self.schedule_interval_seconds = 0
        self.launched: list[tuple[str, str, tuple[str, ...], tuple[int, ...]]] = []

    def launch(self, scan_id: str, *, organization_id: str, scope: object) -> None:
        self.launched.append(
            (
                scan_id,
                organization_id,
                tuple(str(item) for item in scope.networks),
                tuple(scope.ports),
            )
        )


def build_fixture(tmp_path: Path) -> tuple[
    TestClient,
    Database,
    SecurityRepository,
    EquipmentDiscoveryRepository,
    StubDiscoveryService,
]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'discovery.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Lab",
    )
    for subject, role in (("engineer", Role.ENGINEER), ("viewer", Role.VIEWER)):
        security.provision_membership(
            organization_id=ORGANIZATION_ID,
            claims=VerifiedIdentityClaims(
                provider="test-oidc",
                subject=subject,
                email=None,
                display_name=subject,
            ),
            roles={role},
        )
    climate = PostgresClimateCatalogRepository(database, security_repository=security)
    climate.seed_default_catalog(organization_id=ORGANIZATION_ID)
    repository = EquipmentDiscoveryRepository(database, security_repository=security)
    policy = DiscoveryPolicy.from_settings(
        Settings(
            equipment_discovery_allowed_cidrs="192.168.50.0/29",
            equipment_discovery_allowed_ports="80,443",
            equipment_discovery_max_hosts=16,
            equipment_discovery_max_ports=2,
        )
    )
    service = StubDiscoveryService(policy)
    dependencies = SecurityDependencies(
        security,
        mode="jwt",
        authenticator=JwtAuthenticator(
            public_key=SECRET,
            algorithm="HS256",
            issuer=ISSUER,
            audience=AUDIENCE,
            provider="test-oidc",
        ),
        default_organization_id=ORGANIZATION_ID,
    )
    app = FastAPI()
    app.include_router(
        create_equipment_discovery_router(
            repository,
            service,  # type: ignore[arg-type]
            policy,
            dependencies,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    return TestClient(app), database, security, repository, service


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


def observation(
    ip: str,
    *,
    fingerprint: str,
    port: int = 443,
    when: datetime | None = None,
) -> DiscoveryObservationInput:
    return DiscoveryObservationInput(
        ip_address=ip,
        mac_address=None,
        hostname=None,
        source_interface=None,
        source_subnet="192.168.50.0/29",
        services=(
            {
                "port": port,
                "transport": "tcp",
                "service": "https" if port == 443 else "http",
                "evidence": "connect_succeeded",
            },
        ),
        evidence={
            "neighbor_table": False,
            "tcp_connect_only": True,
            "payload_bytes_sent": 0,
            "open_ports": [port],
        },
        observed_at=when or datetime.now(UTC),
        fingerprint_sha256=fingerprint,
    )


def start_repo_scan(repository: EquipmentDiscoveryRepository, *, actor: str = "engineer") -> str:
    row = repository.start_scan(
        organization_id=ORGANIZATION_ID,
        requested_cidrs=("192.168.50.0/29",),
        requested_ports=(80, 443),
        host_budget=6,
        probe_budget=12,
        actor_subject=actor,
        audit_event=audit("equipment_discovery.scan_started", "equipment_discovery_scan", "pending"),
    )
    return row.id


def test_discovery_api_is_readable_but_mutations_require_equipment_manage(tmp_path: Path) -> None:
    api, _, security, _, service = build_fixture(tmp_path)

    overview = api.get("/api/v1/equipment-discovery", headers=headers("viewer"))
    assert overview.status_code == 200
    assert overview.json()["policy"]["enabled"] is True
    assert overview.json()["policy"]["probe_mode"] == "tcp-connect-only"
    assert overview.json()["policy"]["payload_bytes_sent_per_probe"] == 0
    assert overview.json()["policy"]["schedule_interval_seconds"] == 0

    denied = api.post(
        "/api/v1/equipment-discovery/scans",
        headers=headers("viewer"),
        json={"cidrs": ["192.168.50.0/30"], "ports": [443]},
    )
    assert denied.status_code == 403
    assert service.launched == []

    accepted = api.post(
        "/api/v1/equipment-discovery/scans",
        headers=headers("engineer"),
        json={"cidrs": ["192.168.50.0/30"], "ports": [443]},
    )
    assert accepted.status_code == 202
    scan_id = accepted.json()["id"]
    assert service.launched == [
        (scan_id, ORGANIZATION_ID, ("192.168.50.0/30",), (443,))
    ]
    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="equipment_discovery_scan",
        entity_id=scan_id,
        limit=10,
    )
    assert len(events) == 1
    assert events[0].action == "equipment_discovery.scan_started"


def test_repository_persists_scan_diff_and_disappeared_lifecycle(tmp_path: Path) -> None:
    _, database, _, repository, _ = build_fixture(tmp_path)
    first_id = start_repo_scan(repository)
    first_time = datetime.now(UTC)
    first = repository.apply_scan_result(
        first_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(
            observations=(
                observation("192.168.50.2", fingerprint="a" * 64, when=first_time),
                observation("192.168.50.3", fingerprint="b" * 64, when=first_time),
            ),
            hosts_considered=6,
            probes_attempted=12,
            duration_ms=25,
            process_cpu_ms=4,
            network_connect_attempts=12,
            network_payload_bytes=0,
        ),
    )
    assert first.status == "completed"
    assert first.duration_ms == 25
    assert first.process_cpu_ms == 4
    assert first.network_connect_attempts == 12
    assert first.network_payload_bytes == 0
    assert first.trigger == "manual"
    assert first.new_candidates == 2
    assert first.changed_candidates == 0
    assert first.disappeared_candidates == 0

    second_id = start_repo_scan(repository)
    second = repository.apply_scan_result(
        second_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(
            observations=(
                observation(
                    "192.168.50.2",
                    fingerprint="c" * 64,
                    port=80,
                    when=first_time + timedelta(minutes=1),
                ),
            ),
            hosts_considered=6,
            probes_attempted=12,
        ),
    )
    assert second.new_candidates == 0
    assert second.changed_candidates == 1
    assert second.disappeared_candidates == 1
    candidates = repository.list_candidates(organization_id=ORGANIZATION_ID)
    by_ip = {item.ip_address: item for item in candidates}
    assert by_ip["192.168.50.2"].present is True
    assert by_ip["192.168.50.2"].changed_since_previous_scan is True
    assert by_ip["192.168.50.3"].present is False
    assert by_ip["192.168.50.3"].lifecycle == "disappeared"

    with Session(database.engine) as session:
        observation_count = int(
            session.scalar(select(func.count()).select_from(EquipmentDiscoveryObservation)) or 0
        )
    assert observation_count == 3


def test_candidate_actions_are_versioned_audited_and_adoption_is_admin_only(tmp_path: Path) -> None:
    api, database, security, repository, _ = build_fixture(tmp_path)
    scan_id = start_repo_scan(repository)
    repository.apply_scan_result(
        scan_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(
            observations=(observation("192.168.50.2", fingerprint="d" * 64),),
            hosts_considered=6,
            probes_attempted=12,
        ),
    )
    candidate = repository.list_candidates(organization_id=ORGANIZATION_ID)[0]

    viewer = api.patch(
        f"/api/v1/equipment-discovery/candidates/{candidate.id}",
        headers={**headers("viewer"), "If-Match": f'W/"equipment-discovery-candidate-v{candidate.version}"'},
        json={"action": "review"},
    )
    assert viewer.status_code == 403

    reviewed = api.patch(
        f"/api/v1/equipment-discovery/candidates/{candidate.id}",
        headers={
            **headers("engineer"),
            "If-Match": f'W/"equipment-discovery-candidate-v{candidate.version}"',
            "X-Audit-Reason": "Reviewed discovery evidence",
        },
        json={"action": "review"},
    )
    assert reviewed.status_code == 200
    reviewed_candidate = reviewed.json()["candidate"]
    assert reviewed_candidate["lifecycle"] == "reviewed"
    assert reviewed.headers["etag"] == 'W/"equipment-discovery-candidate-v2"'

    stale = api.patch(
        f"/api/v1/equipment-discovery/candidates/{candidate.id}",
        headers={**headers("engineer"), "If-Match": 'W/"equipment-discovery-candidate-v1"'},
        json={"action": "ignore"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "equipment_discovery_candidate_version_conflict"

    with Session(database.engine) as session:
        device_count_before = int(session.scalar(select(func.count()).select_from(MeasurementDevice)) or 0)

    adopted = api.patch(
        f"/api/v1/equipment-discovery/candidates/{candidate.id}",
        headers={**headers("engineer"), "If-Match": 'W/"equipment-discovery-candidate-v2"'},
        json={"action": "adopt", "display_name": "LAB network device"},
    )
    assert adopted.status_code == 200
    assert adopted.json()["candidate"]["lifecycle"] == "adopted"
    network_asset = adopted.json()["network_asset"]
    assert network_asset["asset_key"].startswith("network:")
    assert network_asset["display_name"] == "LAB network device"

    with Session(database.engine) as session:
        device_count_after = int(session.scalar(select(func.count()).select_from(MeasurementDevice)) or 0)
        network_count = int(session.scalar(select(func.count()).select_from(EquipmentNetworkAsset)) or 0)
    assert device_count_after == device_count_before
    assert network_count == 1

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="equipment_discovery_candidate",
        entity_id=candidate.id,
        limit=10,
    )
    assert [event.action for event in events] == [
        "equipment_discovery.candidate_adopt",
        "equipment_discovery.candidate_review",
    ]


def test_link_existing_accepts_only_real_canonical_registry_keys(tmp_path: Path) -> None:
    api, _, _, repository, _ = build_fixture(tmp_path)
    scan_id = start_repo_scan(repository)
    repository.apply_scan_result(
        scan_id,
        organization_id=ORGANIZATION_ID,
        result=DiscoveryScanResult(
            observations=(observation("192.168.50.4", fingerprint="e" * 64),),
            hosts_considered=6,
            probes_attempted=12,
        ),
    )
    candidate = repository.list_candidates(organization_id=ORGANIZATION_ID)[0]

    invalid = api.patch(
        f"/api/v1/equipment-discovery/candidates/{candidate.id}",
        headers={**headers("engineer"), "If-Match": f'W/"equipment-discovery-candidate-v{candidate.version}"'},
        json={"action": "link_existing", "linked_equipment_key": "device:not-real"},
    )
    assert invalid.status_code == 404
    assert invalid.json()["detail"]["code"] == "equipment_discovery_link_target_not_found"

    with Session(repository._engine) as session:  # noqa: SLF001 - test verifies canonical storage directly
        real_device = session.scalar(
            select(MeasurementDevice).where(MeasurementDevice.organization_id == ORGANIZATION_ID).limit(1)
        )
    assert real_device is not None
    linked = api.patch(
        f"/api/v1/equipment-discovery/candidates/{candidate.id}",
        headers={**headers("engineer"), "If-Match": f'W/"equipment-discovery-candidate-v{candidate.version}"'},
        json={"action": "link_existing", "linked_equipment_key": f"device:{real_device.id}"},
    )
    assert linked.status_code == 200
    assert linked.json()["candidate"]["lifecycle"] == "matched_existing"
    assert linked.json()["candidate"]["linked_equipment_key"] == f"device:{real_device.id}"
    assert linked.json()["network_asset"] is None
