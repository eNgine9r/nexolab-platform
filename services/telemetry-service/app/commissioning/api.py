from __future__ import annotations

import re
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.commissioning.catalog import SUPPORTED_DEVICE_PROFILES, supported_profile
from app.commissioning.models import EquipmentCommissioningSession
from app.commissioning.repository import (
    CommissioningEquipmentReferenceError,
    CommissioningIdempotencyConflictError,
    CommissioningLifecycleConflictError,
    CommissioningNotFoundError,
    CommissioningRepository,
    CommissioningRepositoryError,
    CommissioningVersionConflictError,
)
from app.commissioning.schemas import (
    CommissioningSessionListResponse,
    CommissioningSessionPatch,
    CommissioningSessionResponse,
    CommissioningSessionWrite,
    SupportedDeviceProfileListResponse,
    SupportedDeviceProfileResponse,
)
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput

_ETAG_RE = re.compile(r'^W/"commissioning-session-v(?P<version>[1-9][0-9]*)"$')


def create_commissioning_router(
    repository: CommissioningRepository,
    security_dependencies: SecurityDependencies | None = None,
    *,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment/commissioning", tags=["equipment-commissioning"])
    read_access = _access_dependency(security_dependencies, Permission.READ_DASHBOARD, default_organization_id)
    manage_access = _access_dependency(security_dependencies, Permission.MANAGE_EQUIPMENT, default_organization_id)

    @router.get("/profiles", response_model=SupportedDeviceProfileListResponse)
    def profiles(_: AuthorizedRequest = Depends(read_access)) -> SupportedDeviceProfileListResponse:
        return SupportedDeviceProfileListResponse(
            items=[
                SupportedDeviceProfileResponse(
                    id=item.id,
                    version=item.version,
                    device_family=item.device_family,
                    device_class=item.device_class,
                    manufacturer=item.manufacturer,
                    models=list(item.models),
                    display_name=item.display_name,
                    transport_kind="modbus_rtu",
                    capability_status=item.capability_status,  # type: ignore[arg-type]
                    evidence_note=item.evidence_note,
                    read_only=True,
                )
                for item in SUPPORTED_DEVICE_PROFILES
            ]
        )

    @router.get("/profiles/{profile_id}", response_model=SupportedDeviceProfileResponse)
    def profile(
        profile_id: str,
        _: AuthorizedRequest = Depends(read_access),
    ) -> SupportedDeviceProfileResponse:
        item = supported_profile(profile_id)
        if item is None:
            raise _http_error(
                404,
                "commissioning_profile_not_found",
                "Supported commissioning profile was not found",
            )
        return SupportedDeviceProfileResponse(
            id=item.id,
            version=item.version,
            device_family=item.device_family,
            device_class=item.device_class,
            manufacturer=item.manufacturer,
            models=list(item.models),
            display_name=item.display_name,
            transport_kind="modbus_rtu",
            capability_status=item.capability_status,  # type: ignore[arg-type]
            evidence_note=item.evidence_note,
            read_only=True,
        )

    @router.get("/sessions", response_model=CommissioningSessionListResponse)
    def list_sessions(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CommissioningSessionListResponse:
        return CommissioningSessionListResponse(
            items=[
                _response(item)
                for item in repository.list_sessions(
                    organization_id=authorized.principal.organization_id,
                )
            ]
        )

    @router.post(
        "/sessions",
        response_model=CommissioningSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_session(
        payload: CommissioningSessionWrite,
        request: Request,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CommissioningSessionResponse:
        if idempotency_key is None or not idempotency_key.strip():
            raise _http_error(428, "commissioning_idempotency_key_required", "Idempotency-Key is required")
        try:
            result = repository.create_session(
                payload,
                organization_id=authorized.principal.organization_id,
                idempotency_key=idempotency_key,
                actor_subject=authorized.principal.subject,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.commissioning.created",
                    entity_id="pending",
                    reason=audit_reason or "Create commissioning draft",
                ),
            )
        except CommissioningRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = commissioning_etag(result.session.version)
        response.headers["Location"] = f"/api/v1/equipment/commissioning/sessions/{result.session.id}"
        response.headers["Idempotent-Replay"] = "true" if result.replayed else "false"
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return _response(result.session)

    @router.get("/sessions/{session_id}", response_model=CommissioningSessionResponse)
    def get_session(
        session_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CommissioningSessionResponse:
        try:
            item = repository.get_session(
                session_id,
                organization_id=authorized.principal.organization_id,
            )
        except CommissioningRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = commissioning_etag(item.version)
        return _response(item)

    @router.patch("/sessions/{session_id}", response_model=CommissioningSessionResponse)
    def update_session(
        session_id: str,
        payload: CommissioningSessionPatch,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CommissioningSessionResponse:
        try:
            item = repository.update_session(
                session_id,
                payload,
                organization_id=authorized.principal.organization_id,
                expected_version=parse_commissioning_if_match(if_match),
                actor_subject=authorized.principal.subject,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.commissioning.updated",
                    entity_id=session_id,
                    reason=audit_reason or "Update commissioning draft",
                ),
            )
        except CommissioningRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = commissioning_etag(item.version)
        return _response(item)

    @router.post("/sessions/{session_id}/cancel", response_model=CommissioningSessionResponse)
    def cancel_session(
        session_id: str,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CommissioningSessionResponse:
        try:
            item = repository.cancel_session(
                session_id,
                organization_id=authorized.principal.organization_id,
                expected_version=parse_commissioning_if_match(if_match),
                actor_subject=authorized.principal.subject,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.commissioning.cancelled",
                    entity_id=session_id,
                    reason=audit_reason or "Cancel commissioning draft",
                ),
            )
        except CommissioningRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = commissioning_etag(item.version)
        return _response(item)

    return router


def commissioning_etag(version: int) -> str:
    return f'W/"commissioning-session-v{version}"'


def parse_commissioning_if_match(value: str | None) -> int:
    match = _ETAG_RE.fullmatch(value.strip()) if value is not None else None
    if match is None:
        raise _http_error(
            428,
            "commissioning_version_required",
            'If-Match must contain the current commissioning ETag, for example W/"commissioning-session-v2"',
        )
    return int(match.group("version"))


def _response(item: EquipmentCommissioningSession) -> CommissioningSessionResponse:
    return CommissioningSessionResponse(
        id=item.id,
        lifecycle=item.lifecycle,  # type: ignore[arg-type]
        device_class=item.device_class,
        manufacturer=item.manufacturer,
        model=item.model,
        profile_id=item.profile_id,
        profile_version=item.profile_version,
        transport_kind=item.transport_kind,
        node_id=item.node_id,
        bus_id=item.bus_id,
        stable_transport_identifier=item.stable_transport_identifier,
        unit_id=item.unit_id,
        ip_address=item.ip_address,
        target_equipment_key=item.target_equipment_key,
        blocked_reason=item.blocked_reason,
        unsupported_reason=item.unsupported_reason,
        version=item.version,
        created_by=item.created_by,
        updated_by=item.updated_by,
        created_at=item.created_at,
        updated_at=item.updated_at,
        cancelled_at=item.cancelled_at,
    )


def _repository_http_error(error: CommissioningRepositoryError) -> HTTPException:
    if isinstance(error, CommissioningNotFoundError):
        return _http_error(404, error.code, str(error))
    if isinstance(error, CommissioningVersionConflictError):
        return _http_error(
            409,
            error.code,
            str(error),
            expected_version=error.expected_version,
            actual_version=error.actual_version,
        )
    if isinstance(error, CommissioningEquipmentReferenceError):
        return _http_error(422, error.code, str(error))
    if isinstance(error, (CommissioningIdempotencyConflictError, CommissioningLifecycleConflictError)):
        return _http_error(409, error.code, str(error))
    return _http_error(500, error.code, str(error))


def _http_error(status_code: int, code: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


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
    entity_id: str,
    reason: str,
) -> AuditEventInput:
    return AuditEventInput(
        organization_id=authorized.principal.organization_id,
        actor_identity_id=authorized.identity_id,
        actor_subject=authorized.principal.subject,
        actor_roles=authorized.principal.roles,
        action=action,
        entity_type="equipment_commissioning_session",
        entity_id=entity_id,
        reason=reason,
        request_id=request.headers.get("X-Request-ID"),
        source_ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("User-Agent"),
    )
