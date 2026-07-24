from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.sessions.api import _http_error
from app.sessions.configuration import ConfiguredSessionRepository
from app.sessions.configuration_schemas import (
    BindingMutationResponse,
    BindingRemovalResponse,
    LimitSetMutationResponse,
    ProductionBindingsCreate,
    ProductionBindingsResponse,
    SessionBindingCreate,
    SessionBindingRead,
    SessionBindingRemove,
    SessionConfigurationRead,
    SessionLimitRead,
    SessionLimitSetCreate,
)
from app.sessions.production_contract import EXPECTED_PRODUCTION_SERIES_COUNT
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
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["session configuration"])

    @router.post(
        "/{session_id}/bindings",
        response_model=BindingMutationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_binding(
        session_id: str,
        payload: SessionBindingCreate,
        idempotency_key: IdempotencyKey,
    ) -> BindingMutationResponse:
        try:
            result = repository.add_binding(
                session_id,
                payload,
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
    ) -> ProductionBindingsResponse:
        try:
            result = repository.add_production_bindings(
                session_id,
                payload,
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
        include_released: Annotated[bool, Query()] = False,
    ) -> list[SessionBindingRead]:
        try:
            return [
                SessionBindingRead.model_validate(item)
                for item in repository.bindings(
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
    ) -> BindingRemovalResponse:
        try:
            result = repository.remove_binding(
                session_id,
                binding_id,
                payload,
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
    ) -> LimitSetMutationResponse:
        try:
            result = repository.add_limit_set(
                session_id,
                payload,
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
        version: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[SessionLimitRead]:
        try:
            return [
                SessionLimitRead.model_validate(item)
                for item in repository.limits(session_id, version=version)
            ]
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/configuration",
        response_model=SessionConfigurationRead,
    )
    def get_configuration(session_id: str) -> SessionConfigurationRead:
        try:
            result = repository.configuration(session_id)
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
