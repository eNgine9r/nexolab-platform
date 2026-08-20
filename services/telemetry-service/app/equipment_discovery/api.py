from __future__ import annotations

import re
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.equipment_discovery.policy import (
    DiscoveryBudgetExceededError,
    DiscoveryDisabledError,
    DiscoveryPolicy,
    DiscoveryPolicyError,
    DiscoveryScopeDeniedError,
)
from app.equipment_discovery.repository import (
    CandidateActionConflictError,
    CandidateNotFoundError,
    CandidateRecord,
    CandidateVersionConflictError,
    EquipmentDiscoveryRepository,
    EquipmentDiscoveryRepositoryError,
    EquipmentLinkNotFoundError,
    NetworkAssetRecord,
    ScanAlreadyRunningError,
    ScanNotFoundError,
    ScanRecord,
)
from app.equipment_discovery.schemas import (
    DiscoveryCandidateActionRequest,
    DiscoveryCandidateActionResponse,
    DiscoveryCandidateResponse,
    DiscoveryOverviewResponse,
    DiscoveryPolicyResponse,
    DiscoveryScanRequest,
    DiscoveryScanResponse,
    NetworkAssetResponse,
)
from app.equipment_discovery.service import EquipmentDiscoveryService
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput


_CANDIDATE_ETAG_PATTERN = re.compile(
    r'^W/"equipment-discovery-candidate-v(?P<version>[1-9][0-9]*)"$'
)


def create_equipment_discovery_router(
    repository: EquipmentDiscoveryRepository,
    service: EquipmentDiscoveryService,
    policy: DiscoveryPolicy,
    security_dependencies: SecurityDependencies | None = None,
    *,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment-discovery", tags=["equipment-discovery"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
        default_organization_id,
    )
    manage_access = _access_dependency(
        security_dependencies,
        Permission.MANAGE_EQUIPMENT,
        default_organization_id,
    )

    @router.get("", response_model=DiscoveryOverviewResponse)
    def overview(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DiscoveryOverviewResponse:
        organization_id = authorized.principal.organization_id
        scans = repository.list_scans(organization_id=organization_id, limit=20)
        active_scan = next((item for item in scans if item.status == "running"), None)
        last_scan = next((item for item in scans if item.status != "running"), None)
        return DiscoveryOverviewResponse(
            policy=_policy_response(policy),
            active_scan=_scan_response(active_scan) if active_scan else None,
            last_scan=_scan_response(last_scan) if last_scan else None,
            candidates=[
                _candidate_response(item)
                for item in repository.list_candidates(organization_id=organization_id)
            ],
            network_assets=[
                _network_asset_response(item)
                for item in repository.list_network_assets(organization_id=organization_id)
            ],
        )

    @router.post(
        "/scans",
        response_model=DiscoveryScanResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def start_scan(
        payload: DiscoveryScanRequest,
        request: Request,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> DiscoveryScanResponse:
        organization_id = authorized.principal.organization_id
        try:
            scope = policy.resolve(
                requested_cidrs=payload.cidrs,
                requested_ports=payload.ports,
            )
            scan = repository.start_scan(
                organization_id=organization_id,
                requested_cidrs=scope.cidrs,
                requested_ports=scope.ports,
                host_budget=len(scope.addresses),
                probe_budget=scope.probe_budget,
                actor_subject=authorized.principal.subject,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment_discovery.scan_started",
                    entity_type="equipment_discovery_scan",
                    entity_id="pending",
                    reason="Manual LOCAL_LAN discovery scan",
                ),
            )
        except DiscoveryPolicyError as error:
            raise _policy_http_error(error) from error
        except EquipmentDiscoveryRepositoryError as error:
            raise _repository_http_error(error) from error

        # The persistent scan row is created before launch. The service is isolated
        # from the request lifecycle so cancellation remains possible.
        try:
            service.launch(scan.id, organization_id=organization_id, scope=scope)
        except Exception as error:
            repository.finish_failed(
                scan.id,
                organization_id=organization_id,
                error_code="equipment_discovery_launch_failed",
                error_message=str(error) or error.__class__.__name__,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "equipment_discovery_launch_failed",
                    "message": "Discovery scan could not be launched",
                },
            ) from error
        return _scan_response(scan)

    @router.post(
        "/scans/{scan_id}/cancel",
        response_model=DiscoveryScanResponse,
    )
    def cancel_scan(
        scan_id: str,
        request: Request,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> DiscoveryScanResponse:
        try:
            scan = repository.request_cancel(
                scan_id,
                organization_id=authorized.principal.organization_id,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment_discovery.scan_cancel_requested",
                    entity_type="equipment_discovery_scan",
                    entity_id=scan_id,
                    reason="Operator requested bounded scan cancellation",
                ),
            )
        except EquipmentDiscoveryRepositoryError as error:
            raise _repository_http_error(error) from error
        return _scan_response(scan)

    @router.patch(
        "/candidates/{candidate_id}",
        response_model=DiscoveryCandidateActionResponse,
    )
    def act_on_candidate(
        candidate_id: str,
        payload: DiscoveryCandidateActionRequest,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> DiscoveryCandidateActionResponse:
        try:
            candidate, network_asset = repository.act_on_candidate(
                candidate_id,
                organization_id=authorized.principal.organization_id,
                expected_version=parse_candidate_if_match(if_match),
                action=payload.action,
                actor_subject=authorized.principal.subject,
                display_name=payload.display_name,
                linked_equipment_key=payload.linked_equipment_key,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action=f"equipment_discovery.candidate_{payload.action}",
                    entity_type="equipment_discovery_candidate",
                    entity_id=candidate_id,
                    reason=audit_reason,
                ),
            )
        except EquipmentDiscoveryRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = candidate_etag(candidate.version)
        return DiscoveryCandidateActionResponse(
            candidate=_candidate_response(candidate),
            network_asset=(
                _network_asset_response(network_asset) if network_asset is not None else None
            ),
        )

    return router


def candidate_etag(version: int) -> str:
    if version < 1:
        raise ValueError("candidate version must be positive")
    return f'W/"equipment-discovery-candidate-v{version}"'


def parse_candidate_if_match(value: str) -> int:
    match = _CANDIDATE_ETAG_PATTERN.fullmatch(value.strip())
    if match is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "equipment_discovery_candidate_version_required",
                "message": "If-Match must contain the current discovery candidate ETag",
            },
        )
    return int(match.group("version"))


def _policy_response(policy: DiscoveryPolicy) -> DiscoveryPolicyResponse:
    return DiscoveryPolicyResponse(
        enabled=policy.enabled,
        allowed_cidrs=[str(item) for item in policy.allowed_networks],
        allowed_ports=list(policy.allowed_ports),
        max_hosts=policy.max_hosts,
        max_ports=policy.max_ports,
        connect_timeout_seconds=policy.connect_timeout_seconds,
        concurrency=policy.concurrency,
        schedule_interval_seconds=service.schedule_interval_seconds,
    )


def _scan_response(record: ScanRecord) -> DiscoveryScanResponse:
    return DiscoveryScanResponse(
        id=record.id,
        status=record.status,
        requested_cidrs=list(record.requested_cidrs),
        requested_ports=list(record.requested_ports),
        host_budget=record.host_budget,
        probe_budget=record.probe_budget,
        hosts_considered=record.hosts_considered,
        probes_attempted=record.probes_attempted,
        responsive_hosts=record.responsive_hosts,
        duration_ms=record.duration_ms,
        process_cpu_ms=record.process_cpu_ms,
        network_connect_attempts=record.network_connect_attempts,
        network_payload_bytes=record.network_payload_bytes,
        trigger=record.trigger,  # type: ignore[arg-type]
        new_candidates=record.new_candidates,
        changed_candidates=record.changed_candidates,
        disappeared_candidates=record.disappeared_candidates,
        cancel_requested=record.cancel_requested,
        requested_by=record.requested_by,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_code=record.error_code,
        error_message=record.error_message,
    )


def _candidate_response(record: CandidateRecord) -> DiscoveryCandidateResponse:
    return DiscoveryCandidateResponse(
        id=record.id,
        candidate_key=record.candidate_key,
        ip_address=record.ip_address,
        mac_address=record.mac_address,
        hostname=record.hostname,
        source_interface=record.source_interface,
        source_subnet=record.source_subnet,
        lifecycle=record.lifecycle,  # type: ignore[arg-type]
        present=record.present,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        last_scan_id=record.last_scan_id,
        linked_equipment_key=record.linked_equipment_key,
        version=record.version,
        services=list(record.services),  # type: ignore[arg-type]
        evidence=record.evidence,
        changed_since_previous_scan=record.changed_since_previous_scan,
    )


def _network_asset_response(record: NetworkAssetRecord) -> NetworkAssetResponse:
    return NetworkAssetResponse(
        id=record.id,
        asset_key=record.asset_key,
        display_name=record.display_name,
        ip_address=record.ip_address,
        mac_address=record.mac_address,
        manufacturer=record.manufacturer,
        model=record.model,
        source_candidate_id=record.source_candidate_id,
        status=record.status,  # type: ignore[arg-type]
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _access_dependency(
    security_dependencies: SecurityDependencies | None,
    permission: Permission,
    default_organization_id: str,
) -> Callable[..., AuthorizedRequest]:
    if security_dependencies is not None:
        return security_dependencies.authorized_request(permission)

    def development_access() -> AuthorizedRequest:
        return AuthorizedRequest(
            identity_id=None,
            principal=AuthenticatedPrincipal(
                subject="development-system",
                organization_id=default_organization_id,
                roles=frozenset({Role.ADMINISTRATOR}),
                display_name="Development system",
                provider="disabled",
            ),
        )

    return development_access


def _audit_event(
    authorized: AuthorizedRequest,
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    reason: str | None,
) -> AuditEventInput:
    return AuditEventInput(
        organization_id=authorized.principal.organization_id,
        actor_identity_id=authorized.identity_id,
        actor_subject=authorized.principal.subject,
        actor_roles=authorized.principal.roles,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        request_id=request.headers.get("X-Request-ID"),
        source_ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("User-Agent"),
    )


def _policy_http_error(error: DiscoveryPolicyError) -> HTTPException:
    if isinstance(error, DiscoveryDisabledError):
        code = 409
    elif isinstance(error, (DiscoveryScopeDeniedError, DiscoveryBudgetExceededError)):
        code = 422
    else:
        code = 422
    return HTTPException(
        status_code=code,
        detail={"code": error.code, "message": str(error)},
    )


def _repository_http_error(error: EquipmentDiscoveryRepositoryError) -> HTTPException:
    if isinstance(error, (ScanNotFoundError, CandidateNotFoundError, EquipmentLinkNotFoundError)):
        code = 404
    elif isinstance(
        error,
        (ScanAlreadyRunningError, CandidateVersionConflictError, CandidateActionConflictError),
    ):
        code = 409
    else:
        code = 422
    detail: dict[str, object] = {"code": error.code, "message": str(error)}
    if isinstance(error, CandidateVersionConflictError):
        detail["expected_version"] = error.expected_version
        detail["actual_version"] = error.actual_version
    return HTTPException(status_code=code, detail=detail)
