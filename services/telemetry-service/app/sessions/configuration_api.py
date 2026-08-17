from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, Query, status

from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.sessions.api import _http_error
from app.sessions.configuration import ConfiguredSessionRepository
from app.sessions.configuration_schemas import (
    BindingMutationResponse,
    BindingRemovalResponse,
    LimitSetMutationResponse,
    ProductionBindingsCreate,
    ProductionBindingsResponse,
    SessionBindingCreate,
    SessionBindingOptionRead,
    SessionBindingRead,
    SessionBindingRemove,
    SessionConfigurationRead,
    SessionLimitRead,
    SessionLimitSetCreate,
)
from app.sessions.production_contract import (
    EXPECTED_PRODUCTION_SERIES_COUNT,
    PRODUCTION_CHANNELS,
)
from app.sessions.schemas import SessionRead


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
]


def create_session_configuration_router(
    repository: ConfiguredSessionRepository,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["session configuration"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
    )
    manage_access = _access_dependency(
        security_dependencies,
        Permission.MANAGE_SESSIONS,
    )

    @router.get(
        "/binding-options/production",
        response_model=list[SessionBindingOptionRead],
    )
    def list_production_binding_options(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> list[SessionBindingOptionRead]:
        del authorized
        return [
            SessionBindingOptionRead(
                node_id=channel.node_id,
                equipment_id=channel.equipment_id,
                channel_id=channel.channel_id,
                metric=channel.metric,
                unit=channel.unit,
                device_type=channel.device_type,
                profile_version=channel.profile_version,
                register_key=channel.register_key,
                register_address=channel.register_address,
            )
            for channel in PRODUCTION_CHANNELS
        ]

    @router.post(
        "/{session_id}/bindings",
        response_model=BindingMutationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_binding(
        session_id: str,
        payload: SessionBindingCreate,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> BindingMutationResponse:
        try:
            result = repository.for_organization(authorized.principal.organization_id).add_binding(
                session_id,
                _trusted_command(payload, authorized),
                idempotency_key=idempotency_key,
            )
            return BindingMutationResponse(
                binding=result.binding,
                event=result.event,
                replayed=result.replayed,
                active_config_snapshot_id=result.active_config_snapshot_id,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{session_id}/bindings/production",
        response_model=ProductionBindingsResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_production_bindings(
        session_id: str,
        payload: ProductionBindingsCreate,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> ProductionBindingsResponse:
        try:
            result = repository.for_organization(authorized.principal.organization_id).add_production_bindings(
                session_id,
                _trusted_command(payload, authorized),
                idempotency_key=idempotency_key,
            )
            return ProductionBindingsResponse(
                bindings=result.bindings,
                event=result.event,
                replayed=result.replayed,
                active_config_snapshot_id=result.active_config_snapshot_id,
                expected_series_count=EXPECTED_PRODUCTION_SERIES_COUNT,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/bindings",
        response_model=list[SessionBindingRead],
    )
    def list_bindings(
        session_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
        include_released: Annotated[bool, Query()] = False,
    ) -> list[SessionBindingRead]:
        try:
            return [
                SessionBindingRead.model_validate(item)
                for item in repository.for_organization(authorized.principal.organization_id).bindings(
                    session_id,
                    include_released=include_released,
                )
            ]
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{session_id}/bindings/{binding_id}/remove",
        response_model=BindingRemovalResponse,
    )
    def remove_binding(
        session_id: str,
        binding_id: str,
        payload: SessionBindingRemove,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> BindingRemovalResponse:
        try:
            result = repository.for_organization(authorized.principal.organization_id).remove_binding(
                session_id,
                binding_id,
                _trusted_command(payload, authorized),
                idempotency_key=idempotency_key,
            )
            return BindingRemovalResponse(
                binding_id=result.binding_id,
                event=result.event,
                replayed=result.replayed,
                active_config_snapshot_id=result.active_config_snapshot_id,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{session_id}/limits",
        response_model=LimitSetMutationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_limit_set(
        session_id: str,
        payload: SessionLimitSetCreate,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> LimitSetMutationResponse:
        try:
            result = repository.for_organization(authorized.principal.organization_id).add_limit_set(
                session_id,
                _trusted_command(payload, authorized),
                idempotency_key=idempotency_key,
            )
            return LimitSetMutationResponse(
                version=result.version,
                limits=result.limits,
                event=result.event,
                replayed=result.replayed,
                active_config_snapshot_id=result.active_config_snapshot_id,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/limits",
        response_model=list[SessionLimitRead],
    )
    def list_limits(
        session_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
        version: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[SessionLimitRead]:
        try:
            return [
                SessionLimitRead.model_validate(item)
                for item in repository.for_organization(authorized.principal.organization_id).limits(session_id, version=version)
            ]
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/configuration",
        response_model=SessionConfigurationRead,
    )
    def get_configuration(
        session_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> SessionConfigurationRead:
        try:
            result = repository.for_organization(authorized.principal.organization_id).configuration(session_id)
            return SessionConfigurationRead(
                session=SessionRead.model_validate(result.session),
                bindings=result.bindings,
                active_limits=result.active_limits,
                active_snapshot=result.active_snapshot,
                snapshots=result.snapshots,
            )
        except Exception as error:
            raise _http_error(error) from error

    return router


def _trusted_command(payload: object, authorized: AuthorizedRequest):
    return payload.model_copy(
        update={
            "actor_id": authorized.principal.subject,
            "actor_source": authorized.principal.provider,
        }
    )


def _access_dependency(
    security_dependencies: SecurityDependencies | None,
    permission: Permission,
) -> Callable[..., AuthorizedRequest]:
    if security_dependencies is not None:
        return security_dependencies.authorized_request(permission)

    def development_access() -> AuthorizedRequest:
        return AuthorizedRequest(
            identity_id=None,
            principal=AuthenticatedPrincipal(
                subject="development-system",
                organization_id="00000000-0000-0000-0000-000000000001",
                roles=frozenset({Role.ADMINISTRATOR}),
                provider="disabled",
            ),
        )

    return development_access
