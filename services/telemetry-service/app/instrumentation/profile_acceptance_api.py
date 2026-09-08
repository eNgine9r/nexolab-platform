from __future__ import annotations

from datetime import datetime
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.instrumentation.profile_acceptance import (
    AcquisitionProfileAcceptanceError,
    AcquisitionProfileAcceptanceIntegrityError,
    AcquisitionProfileAcceptanceOrderError,
    AcquisitionProfileAcceptanceRepository,
    AcquisitionProfileAcceptanceResolutionError,
    AcquisitionProfileIdentityUnavailableError,
    AcquisitionProfileNotFoundError,
    ProfileAcceptanceAppendRequest,
    ProfileAcceptanceHistoryResponse,
    ProfileAcceptanceResponse,
    profile_acceptance_response,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


def create_profile_acceptance_router(
    repository: AcquisitionProfileAcceptanceRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/instrumentation",
        tags=["instrumentation-registry"],
    )
    read_access = _access_dependency(
        security_dependencies, Permission.READ_DASHBOARD, default_organization_id
    )
    manage_access = _access_dependency(
        security_dependencies, Permission.MANAGE_EQUIPMENT, default_organization_id
    )
    base = (
        "/instruments/{instrument_id}/signals/{signal_id}"
        "/acquisition-sources/{acquisition_source_id}/profile-acceptance-history"
    )

    @router.get(base, response_model=ProfileAcceptanceHistoryResponse)
    def list_profile_acceptance_history(
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        scaling_profile_id: str | None = Query(default=None),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ProfileAcceptanceHistoryResponse:
        try:
            rows = repository.list_history(
                instrument_id,
                signal_id,
                acquisition_source_id,
                scaling_profile_id=scaling_profile_id,
                organization_id=authorized.principal.organization_id,
            )
        except AcquisitionProfileAcceptanceError as error:
            raise _http_error(error) from error
        return ProfileAcceptanceHistoryResponse(
            items=[profile_acceptance_response(row) for row in rows]
        )

    @router.post(
        base,
        response_model=ProfileAcceptanceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def append_profile_acceptance(
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        payload: ProfileAcceptanceAppendRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> ProfileAcceptanceResponse:
        try:
            row = repository.append(
                instrument_id,
                signal_id,
                acquisition_source_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument_signal.acquisition_profile_acceptance_appended",
                    entity_type="instrument_acquisition_profile_acceptance",
                    entity_id=acquisition_source_id,
                    reason=audit_reason,
                ),
            )
        except AcquisitionProfileAcceptanceError as error:
            raise _http_error(error) from error
        return profile_acceptance_response(row)

    @router.get(base + "/effective", response_model=ProfileAcceptanceResponse)
    def resolve_profile_acceptance(
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        at: datetime = Query(...),
        scaling_profile_id: str | None = Query(default=None),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ProfileAcceptanceResponse:
        try:
            row = repository.resolve(
                instrument_id,
                signal_id,
                acquisition_source_id,
                at,
                scaling_profile_id=scaling_profile_id,
                organization_id=authorized.principal.organization_id,
            )
        except AcquisitionProfileAcceptanceError as error:
            raise _http_error(error) from error
        return profile_acceptance_response(row)

    return router


def _http_error(error: AcquisitionProfileAcceptanceError) -> HTTPException:
    if isinstance(error, AcquisitionProfileNotFoundError):
        status_code = 404
    elif isinstance(
        error,
        (
            AcquisitionProfileIdentityUnavailableError,
            AcquisitionProfileAcceptanceOrderError,
            AcquisitionProfileAcceptanceIntegrityError,
            AcquisitionProfileAcceptanceResolutionError,
        ),
    ):
        status_code = 409
    else:
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": str(error)},
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
