from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.climate_catalog.models import MeasurementDevice, PhysicalSensor
from app.db import Database
from app.equipment_discovery.models import (
    EquipmentDiscoveryCandidate,
    EquipmentDiscoveryObservation,
    EquipmentDiscoveryScan,
    EquipmentNetworkAsset,
)
from app.equipment_discovery.scanner import DiscoveryObservationInput, DiscoveryScanResult
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import AuditEventInput, SecurityRepository


class EquipmentDiscoveryRepositoryError(RuntimeError):
    code = "equipment_discovery_repository_error"


class ScanAlreadyRunningError(EquipmentDiscoveryRepositoryError):
    code = "equipment_discovery_scan_already_running"


class ScanNotFoundError(EquipmentDiscoveryRepositoryError):
    code = "equipment_discovery_scan_not_found"


class CandidateNotFoundError(EquipmentDiscoveryRepositoryError):
    code = "equipment_discovery_candidate_not_found"


class CandidateVersionConflictError(EquipmentDiscoveryRepositoryError):
    code = "equipment_discovery_candidate_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"candidate version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class CandidateActionConflictError(EquipmentDiscoveryRepositoryError):
    code = "equipment_discovery_candidate_action_conflict"


class EquipmentLinkNotFoundError(EquipmentDiscoveryRepositoryError):
    code = "equipment_discovery_link_target_not_found"


@dataclass(frozen=True, slots=True)
class ScanRecord:
    id: str
    organization_id: str
    status: str
    requested_cidrs: tuple[str, ...]
    requested_ports: tuple[int, ...]
    host_budget: int
    probe_budget: int
    hosts_considered: int
    probes_attempted: int
    responsive_hosts: int
    duration_ms: int
    process_cpu_ms: int
    network_connect_attempts: int
    network_payload_bytes: int
    trigger: str
    new_candidates: int
    changed_candidates: int
    disappeared_candidates: int
    cancel_requested: bool
    requested_by: str
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    id: str
    organization_id: str
    candidate_key: str
    ip_address: str
    mac_address: str | None
    hostname: str | None
    source_interface: str | None
    source_subnet: str
    lifecycle: str
    present: bool
    first_seen_at: datetime
    last_seen_at: datetime
    last_scan_id: str
    linked_equipment_key: str | None
    version: int
    services: tuple[dict[str, object], ...]
    evidence: dict[str, object]
    changed_since_previous_scan: bool


@dataclass(frozen=True, slots=True)
class NetworkAssetRecord:
    id: str
    organization_id: str
    asset_key: str
    display_name: str
    ip_address: str
    mac_address: str | None
    manufacturer: str | None
    model: str | None
    source_candidate_id: str
    status: str
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class EquipmentDiscoveryRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository or SecurityRepository(database)

    def reconcile_interrupted_scans(self) -> int:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                rows = list(
                    session.scalars(
                        select(EquipmentDiscoveryScan)
                        .where(EquipmentDiscoveryScan.status == "running")
                        .with_for_update()
                    )
                )
                for row in rows:
                    row.status = "failed"
                    row.completed_at = now
                    row.error_code = "equipment_discovery_service_restarted"
                    row.error_message = "Discovery service restarted before the scan completed"
            return len(rows)

    def start_scan(
        self,
        *,
        organization_id: str,
        requested_cidrs: tuple[str, ...],
        requested_ports: tuple[int, ...],
        host_budget: int,
        probe_budget: int,
        actor_subject: str,
        audit_event: AuditEventInput,
        trigger: str = "manual",
    ) -> ScanRecord:
        row = EquipmentDiscoveryScan(
            id=str(uuid4()),
            organization_id=organization_id,
            status="running",
            requested_cidrs=list(requested_cidrs),
            requested_ports=list(requested_ports),
            host_budget=host_budget,
            probe_budget=probe_budget,
            hosts_considered=0,
            probes_attempted=0,
            responsive_hosts=0,
            duration_ms=0,
            process_cpu_ms=0,
            network_connect_attempts=0,
            network_payload_bytes=0,
            trigger=trigger,
            new_candidates=0,
            changed_candidates=0,
            disappeared_candidates=0,
            cancel_requested=False,
            requested_by=actor_subject,
            started_at=datetime.now(UTC),
            completed_at=None,
            error_code=None,
            error_message=None,
        )
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    session.add(row)
                    session.flush()
                    self._security_repository.append_audit_event(
                        replace(
                            audit_event,
                            entity_id=row.id,
                            after_snapshot=_scan_snapshot(row),
                        ),
                        session=session,
                    )
                return _scan_record(row)
        except IntegrityError as error:
            raise ScanAlreadyRunningError(
                "a discovery scan is already running for this organization"
            ) from error

    def get_scan(self, scan_id: str, *, organization_id: str) -> ScanRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.scalar(
                select(EquipmentDiscoveryScan).where(
                    EquipmentDiscoveryScan.id == scan_id,
                    EquipmentDiscoveryScan.organization_id == organization_id,
                )
            )
            if row is None:
                raise ScanNotFoundError(scan_id)
            return _scan_record(row)

    def list_scans(self, *, organization_id: str, limit: int = 20) -> tuple[ScanRecord, ...]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(EquipmentDiscoveryScan)
                    .where(EquipmentDiscoveryScan.organization_id == organization_id)
                    .order_by(EquipmentDiscoveryScan.started_at.desc(), EquipmentDiscoveryScan.id.desc())
                    .limit(limit)
                )
            )
            return tuple(_scan_record(row) for row in rows)

    def request_cancel(
        self,
        scan_id: str,
        *,
        organization_id: str,
        audit_event: AuditEventInput,
    ) -> ScanRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = session.scalar(
                    select(EquipmentDiscoveryScan)
                    .where(
                        EquipmentDiscoveryScan.id == scan_id,
                        EquipmentDiscoveryScan.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise ScanNotFoundError(scan_id)
                before = _scan_snapshot(row)
                if row.status == "running":
                    row.cancel_requested = True
                    session.flush()
                self._security_repository.append_audit_event(
                    replace(
                        audit_event,
                        before_snapshot=before,
                        after_snapshot=_scan_snapshot(row),
                    ),
                    session=session,
                )
                return _scan_record(row)

    def cancel_requested(self, scan_id: str, *, organization_id: str) -> bool:
        with Session(self._engine, expire_on_commit=False) as session:
            value = session.scalar(
                select(EquipmentDiscoveryScan.cancel_requested).where(
                    EquipmentDiscoveryScan.id == scan_id,
                    EquipmentDiscoveryScan.organization_id == organization_id,
                    EquipmentDiscoveryScan.status == "running",
                )
            )
            return bool(value)

    def finish_cancelled(self, scan_id: str, *, organization_id: str) -> None:
        self._finish_without_results(
            scan_id,
            organization_id=organization_id,
            status="cancelled",
            error_code=None,
            error_message=None,
        )

    def finish_failed(
        self,
        scan_id: str,
        *,
        organization_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        self._finish_without_results(
            scan_id,
            organization_id=organization_id,
            status="failed",
            error_code=error_code[:128],
            error_message=error_message[:1024],
        )

    def apply_scan_result(
        self,
        scan_id: str,
        *,
        organization_id: str,
        result: DiscoveryScanResult,
    ) -> ScanRecord:
        now = datetime.now(UTC)
        observed_candidate_ids: set[str] = set()
        new_count = 0
        changed_count = 0
        disappeared_count = 0
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                scan = session.scalar(
                    select(EquipmentDiscoveryScan)
                    .where(
                        EquipmentDiscoveryScan.id == scan_id,
                        EquipmentDiscoveryScan.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if scan is None:
                    raise ScanNotFoundError(scan_id)
                if scan.status != "running":
                    raise CandidateActionConflictError(
                        f"scan {scan_id} is no longer running"
                    )

                for observation in result.observations:
                    candidate = session.scalar(
                        select(EquipmentDiscoveryCandidate)
                        .where(
                            EquipmentDiscoveryCandidate.organization_id == organization_id,
                            EquipmentDiscoveryCandidate.candidate_key == observation.candidate_key,
                        )
                        .with_for_update()
                    )
                    previous_fingerprint: str | None = None
                    if candidate is None:
                        candidate = EquipmentDiscoveryCandidate(
                            id=str(uuid4()),
                            organization_id=organization_id,
                            candidate_key=observation.candidate_key,
                            ip_address=observation.ip_address,
                            mac_address=observation.mac_address,
                            hostname=observation.hostname,
                            source_interface=observation.source_interface,
                            source_subnet=observation.source_subnet,
                            lifecycle="new",
                            present=True,
                            first_seen_at=observation.observed_at,
                            last_seen_at=observation.observed_at,
                            last_scan_id=scan_id,
                            linked_equipment_key=None,
                            version=1,
                        )
                        session.add(candidate)
                        session.flush()
                        new_count += 1
                    else:
                        previous_fingerprint = session.scalar(
                            select(EquipmentDiscoveryObservation.fingerprint_sha256)
                            .where(
                                EquipmentDiscoveryObservation.organization_id == organization_id,
                                EquipmentDiscoveryObservation.candidate_id == candidate.id,
                            )
                            .order_by(
                                EquipmentDiscoveryObservation.observed_at.desc(),
                                EquipmentDiscoveryObservation.id.desc(),
                            )
                            .limit(1)
                        )
                        if (
                            previous_fingerprint is not None
                            and previous_fingerprint != observation.fingerprint_sha256
                        ):
                            changed_count += 1
                        candidate.ip_address = observation.ip_address
                        candidate.mac_address = observation.mac_address
                        candidate.hostname = observation.hostname
                        candidate.source_interface = observation.source_interface
                        candidate.source_subnet = observation.source_subnet
                        candidate.present = True
                        candidate.last_seen_at = observation.observed_at
                        candidate.last_scan_id = scan_id
                        if candidate.lifecycle == "disappeared":
                            candidate.lifecycle = (
                                "matched_existing"
                                if candidate.linked_equipment_key
                                else "new"
                            )
                        candidate.version += 1
                        session.flush()

                    observed_candidate_ids.add(candidate.id)
                    session.add(
                        EquipmentDiscoveryObservation(
                            id=str(uuid4()),
                            organization_id=organization_id,
                            scan_id=scan_id,
                            candidate_id=candidate.id,
                            observed_at=observation.observed_at,
                            ip_address=observation.ip_address,
                            mac_address=observation.mac_address,
                            hostname=observation.hostname,
                            source_interface=observation.source_interface,
                            source_subnet=observation.source_subnet,
                            services=[dict(item) for item in observation.services],
                            evidence=dict(observation.evidence),
                            fingerprint_sha256=observation.fingerprint_sha256,
                        )
                    )

                scan_networks = tuple(
                    ip_network(value, strict=False) for value in scan.requested_cidrs
                )
                scan_ports = set(scan.requested_ports)
                present_candidates = list(
                    session.scalars(
                        select(EquipmentDiscoveryCandidate)
                        .where(
                            EquipmentDiscoveryCandidate.organization_id == organization_id,
                            EquipmentDiscoveryCandidate.present.is_(True),
                        )
                        .with_for_update()
                    )
                )
                previous_observations = self._recent_observations_by_candidate(
                    session,
                    organization_id=organization_id,
                    candidate_ids=[item.id for item in present_candidates],
                    per_candidate=1,
                )
                for candidate in present_candidates:
                    if candidate.id in observed_candidate_ids:
                        continue
                    parsed_ip = ip_address(candidate.ip_address)
                    if not isinstance(parsed_ip, IPv4Address):
                        continue
                    if not any(parsed_ip in network for network in scan_networks):
                        continue
                    latest = previous_observations.get(candidate.id, ())
                    prior_open_ports = {
                        int(service["port"])
                        for service in (latest[0].services if latest else [])
                        if isinstance(service, dict) and isinstance(service.get("port"), int)
                    }
                    if not prior_open_ports or not prior_open_ports.issubset(scan_ports):
                        continue
                    candidate.present = False
                    if candidate.lifecycle not in {"ignored", "adopted"}:
                        candidate.lifecycle = "disappeared"
                    candidate.version += 1
                    disappeared_count += 1

                scan.status = "completed"
                scan.completed_at = now
                scan.hosts_considered = result.hosts_considered
                scan.probes_attempted = result.probes_attempted
                scan.responsive_hosts = result.responsive_hosts
                scan.duration_ms = result.duration_ms
                scan.process_cpu_ms = result.process_cpu_ms
                scan.network_connect_attempts = result.network_connect_attempts
                scan.network_payload_bytes = result.network_payload_bytes
                scan.new_candidates = new_count
                scan.changed_candidates = changed_count
                scan.disappeared_candidates = disappeared_count
                scan.error_code = None
                scan.error_message = None
                session.flush()
                return _scan_record(scan)

    def list_candidates(
        self,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> tuple[CandidateRecord, ...]:
        with Session(self._engine, expire_on_commit=False) as session:
            candidates = list(
                session.scalars(
                    select(EquipmentDiscoveryCandidate)
                    .where(EquipmentDiscoveryCandidate.organization_id == organization_id)
                    .order_by(
                        EquipmentDiscoveryCandidate.present.desc(),
                        EquipmentDiscoveryCandidate.last_seen_at.desc(),
                        EquipmentDiscoveryCandidate.id.asc(),
                    )
                    .limit(limit)
                )
            )
            observations = self._recent_observations_by_candidate(
                session,
                organization_id=organization_id,
                candidate_ids=[item.id for item in candidates],
                per_candidate=2,
            )
            return tuple(
                self._candidate_record_from_observations(item, observations.get(item.id, ()))
                for item in candidates
            )

    def list_network_assets(
        self,
        *,
        organization_id: str,
        include_inactive: bool = False,
    ) -> tuple[NetworkAssetRecord, ...]:
        filters = [EquipmentNetworkAsset.organization_id == organization_id]
        if not include_inactive:
            filters.append(EquipmentNetworkAsset.status == "active")
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(EquipmentNetworkAsset)
                    .where(*filters)
                    .order_by(EquipmentNetworkAsset.display_name, EquipmentNetworkAsset.id)
                )
            )
            return tuple(_network_asset_record(row) for row in rows)

    def act_on_candidate(
        self,
        candidate_id: str,
        *,
        organization_id: str,
        expected_version: int,
        action: str,
        actor_subject: str,
        display_name: str | None,
        linked_equipment_key: str | None,
        audit_event: AuditEventInput,
    ) -> tuple[CandidateRecord, NetworkAssetRecord | None]:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                candidate = session.scalar(
                    select(EquipmentDiscoveryCandidate)
                    .where(
                        EquipmentDiscoveryCandidate.id == candidate_id,
                        EquipmentDiscoveryCandidate.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if candidate is None:
                    raise CandidateNotFoundError(candidate_id)
                if candidate.version != expected_version:
                    raise CandidateVersionConflictError(
                        expected_version=expected_version,
                        actual_version=candidate.version,
                    )
                before = _candidate_snapshot(candidate)
                asset: EquipmentNetworkAsset | None = None

                if action == "review":
                    if candidate.lifecycle == "adopted":
                        raise CandidateActionConflictError("adopted candidates cannot return to review")
                    candidate.lifecycle = "reviewed"
                elif action == "ignore":
                    if candidate.lifecycle == "adopted":
                        raise CandidateActionConflictError("adopted candidates cannot be ignored")
                    candidate.lifecycle = "ignored"
                    candidate.linked_equipment_key = None
                elif action == "link_existing":
                    if candidate.lifecycle == "adopted":
                        raise CandidateActionConflictError("adopted candidates cannot be linked elsewhere")
                    assert linked_equipment_key is not None
                    if not self._canonical_equipment_exists(
                        session,
                        organization_id=organization_id,
                        equipment_key=linked_equipment_key,
                    ):
                        raise EquipmentLinkNotFoundError(linked_equipment_key)
                    candidate.lifecycle = "matched_existing"
                    candidate.linked_equipment_key = linked_equipment_key
                elif action == "adopt":
                    if not candidate.present:
                        raise CandidateActionConflictError("a disappeared candidate cannot be adopted")
                    existing_asset = session.scalar(
                        select(EquipmentNetworkAsset).where(
                            EquipmentNetworkAsset.organization_id == organization_id,
                            EquipmentNetworkAsset.source_candidate_id == candidate.id,
                        )
                    )
                    if existing_asset is not None:
                        raise CandidateActionConflictError("candidate is already adopted")
                    asset_id = str(uuid4())
                    asset = EquipmentNetworkAsset(
                        id=asset_id,
                        organization_id=organization_id,
                        asset_key=f"network:{asset_id}",
                        display_name=(display_name or f"Network device {candidate.ip_address}").strip(),
                        ip_address=candidate.ip_address,
                        mac_address=candidate.mac_address,
                        manufacturer=None,
                        model=None,
                        source_candidate_id=candidate.id,
                        status="active",
                        version=1,
                        created_by=actor_subject,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    session.add(asset)
                    candidate.lifecycle = "adopted"
                    candidate.linked_equipment_key = asset.asset_key
                else:
                    raise CandidateActionConflictError(f"unsupported candidate action: {action}")

                candidate.version += 1
                session.flush()
                record = self._candidate_record(session, candidate)
                self._security_repository.append_audit_event(
                    replace(
                        audit_event,
                        before_snapshot=before,
                        after_snapshot=_candidate_snapshot(candidate),
                    ),
                    session=session,
                )
                return record, _network_asset_record(asset) if asset is not None else None

    def _candidate_record(
        self,
        session: Session,
        candidate: EquipmentDiscoveryCandidate,
    ) -> CandidateRecord:
        observations = self._recent_observations_by_candidate(
            session,
            organization_id=candidate.organization_id,
            candidate_ids=[candidate.id],
            per_candidate=2,
        ).get(candidate.id, ())
        return self._candidate_record_from_observations(candidate, observations)

    def _recent_observations_by_candidate(
        self,
        session: Session,
        *,
        organization_id: str,
        candidate_ids: list[str],
        per_candidate: int,
    ) -> dict[str, tuple[EquipmentDiscoveryObservation, ...]]:
        if not candidate_ids:
            return {}
        ranked = (
            select(
                EquipmentDiscoveryObservation.id.label("observation_id"),
                EquipmentDiscoveryObservation.candidate_id.label("candidate_id"),
                func.row_number()
                .over(
                    partition_by=EquipmentDiscoveryObservation.candidate_id,
                    order_by=(
                        EquipmentDiscoveryObservation.observed_at.desc(),
                        EquipmentDiscoveryObservation.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(
                EquipmentDiscoveryObservation.organization_id == organization_id,
                EquipmentDiscoveryObservation.candidate_id.in_(candidate_ids),
            )
            .subquery()
        )
        rows = list(
            session.scalars(
                select(EquipmentDiscoveryObservation)
                .join(
                    ranked,
                    EquipmentDiscoveryObservation.id == ranked.c.observation_id,
                )
                .where(ranked.c.row_number <= per_candidate)
                .order_by(ranked.c.candidate_id, ranked.c.row_number)
            )
        )
        grouped: defaultdict[str, list[EquipmentDiscoveryObservation]] = defaultdict(list)
        for row in rows:
            grouped[row.candidate_id].append(row)
        return {candidate_id: tuple(items) for candidate_id, items in grouped.items()}

    @staticmethod
    def _candidate_record_from_observations(
        candidate: EquipmentDiscoveryCandidate,
        observations: tuple[EquipmentDiscoveryObservation, ...],
    ) -> CandidateRecord:
        latest = observations[0] if observations else None
        changed = (
            len(observations) > 1
            and observations[0].fingerprint_sha256 != observations[1].fingerprint_sha256
        )
        return CandidateRecord(
            id=candidate.id,
            organization_id=candidate.organization_id,
            candidate_key=candidate.candidate_key,
            ip_address=candidate.ip_address,
            mac_address=candidate.mac_address,
            hostname=candidate.hostname,
            source_interface=candidate.source_interface,
            source_subnet=candidate.source_subnet,
            lifecycle=candidate.lifecycle,
            present=candidate.present,
            first_seen_at=candidate.first_seen_at,
            last_seen_at=candidate.last_seen_at,
            last_scan_id=candidate.last_scan_id,
            linked_equipment_key=candidate.linked_equipment_key,
            version=candidate.version,
            services=tuple(latest.services) if latest is not None else (),
            evidence=dict(latest.evidence) if latest is not None else {},
            changed_since_previous_scan=changed,
        )

    def _canonical_equipment_exists(
        self,
        session: Session,
        *,
        organization_id: str,
        equipment_key: str,
    ) -> bool:
        prefix, separator, identifier = equipment_key.partition(":")
        if not separator or not identifier:
            return False
        if prefix == "refrigeration":
            return (
                session.scalar(
                    select(func.count())
                    .select_from(RefrigerationEquipmentRecord)
                    .where(
                        RefrigerationEquipmentRecord.organization_id == organization_id,
                        RefrigerationEquipmentRecord.id == identifier,
                        RefrigerationEquipmentRecord.deleted_at.is_(None),
                    )
                )
                or 0
            ) > 0
        if prefix == "device":
            return (
                session.scalar(
                    select(func.count())
                    .select_from(MeasurementDevice)
                    .where(
                        MeasurementDevice.organization_id == organization_id,
                        MeasurementDevice.id == identifier,
                    )
                )
                or 0
            ) > 0
        if prefix == "sensor":
            return (
                session.scalar(
                    select(func.count())
                    .select_from(PhysicalSensor)
                    .where(
                        PhysicalSensor.organization_id == organization_id,
                        PhysicalSensor.id == identifier,
                    )
                )
                or 0
            ) > 0
        if prefix == "network":
            return (
                session.scalar(
                    select(func.count())
                    .select_from(EquipmentNetworkAsset)
                    .where(
                        EquipmentNetworkAsset.organization_id == organization_id,
                        EquipmentNetworkAsset.asset_key == equipment_key,
                        EquipmentNetworkAsset.status == "active",
                    )
                )
                or 0
            ) > 0
        return False

    def _finish_without_results(
        self,
        scan_id: str,
        *,
        organization_id: str,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = session.scalar(
                    select(EquipmentDiscoveryScan)
                    .where(
                        EquipmentDiscoveryScan.id == scan_id,
                        EquipmentDiscoveryScan.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise ScanNotFoundError(scan_id)
                if row.status != "running":
                    return
                row.status = status
                row.completed_at = datetime.now(UTC)
                row.error_code = error_code
                row.error_message = error_message


def _scan_record(row: EquipmentDiscoveryScan) -> ScanRecord:
    return ScanRecord(
        id=row.id,
        organization_id=row.organization_id,
        status=row.status,
        requested_cidrs=tuple(str(item) for item in row.requested_cidrs),
        requested_ports=tuple(int(item) for item in row.requested_ports),
        host_budget=row.host_budget,
        probe_budget=row.probe_budget,
        hosts_considered=row.hosts_considered,
        probes_attempted=row.probes_attempted,
        responsive_hosts=row.responsive_hosts,
        duration_ms=row.duration_ms,
        process_cpu_ms=row.process_cpu_ms,
        network_connect_attempts=row.network_connect_attempts,
        network_payload_bytes=row.network_payload_bytes,
        trigger=row.trigger,
        new_candidates=row.new_candidates,
        changed_candidates=row.changed_candidates,
        disappeared_candidates=row.disappeared_candidates,
        cancel_requested=row.cancel_requested,
        requested_by=row.requested_by,
        started_at=row.started_at,
        completed_at=row.completed_at,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _network_asset_record(row: EquipmentNetworkAsset) -> NetworkAssetRecord:
    return NetworkAssetRecord(
        id=row.id,
        organization_id=row.organization_id,
        asset_key=row.asset_key,
        display_name=row.display_name,
        ip_address=row.ip_address,
        mac_address=row.mac_address,
        manufacturer=row.manufacturer,
        model=row.model,
        source_candidate_id=row.source_candidate_id,
        status=row.status,
        version=row.version,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _scan_snapshot(row: EquipmentDiscoveryScan) -> dict[str, object]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "status": row.status,
        "requested_cidrs": list(row.requested_cidrs),
        "requested_ports": list(row.requested_ports),
        "host_budget": row.host_budget,
        "probe_budget": row.probe_budget,
        "trigger": row.trigger,
        "duration_ms": row.duration_ms,
        "process_cpu_ms": row.process_cpu_ms,
        "network_connect_attempts": row.network_connect_attempts,
        "network_payload_bytes": row.network_payload_bytes,
        "cancel_requested": row.cancel_requested,
    }


def _candidate_snapshot(row: EquipmentDiscoveryCandidate) -> dict[str, object]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "candidate_key": row.candidate_key,
        "ip_address": row.ip_address,
        "mac_address": row.mac_address,
        "source_subnet": row.source_subnet,
        "lifecycle": row.lifecycle,
        "present": row.present,
        "linked_equipment_key": row.linked_equipment_key,
        "version": row.version,
    }
