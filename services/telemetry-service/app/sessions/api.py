from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.sessions.domain import SessionAction, SessionDomainError, SessionState
from app.sessions.repository import (
    SessionConflictError,
    SessionNotFoundError,
    SessionRepository,
    SessionRepositoryError,
)
from app.sessions.schemas import (
    SessionCreate,
    SessionEventsPage,
    SessionPage,
    SessionPatch,
    SessionRead,
    SessionTransitionRequest,
    SessionTransitionResponse,
)


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
]


def create_session_router(
    repository: SessionRepository,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
    )
    manage_access = _access_dependency(
        security_dependencies,
        Permission.MANAGE_SESSIONS,
    )
    operate_access = _access_dependency(
        security_dependencies,
        Permission.OPERATE_SESSIONS,
    )

    @router.post(
        "",
        response_model=SessionTransitionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_session(
        payload: SessionCreate,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SessionTransitionResponse:
        trusted_payload = payload.model_copy(
            update={
                "actor_id": authorized.principal.subject,
                "actor_source": authorized.principal.provider,
            }
        )
        try:
            result = repository.for_organization(authorized.principal.organization_id).create(
                trusted_payload,
                idempotency_key=idempotency_key,
            )
            return SessionTransitionResponse(
                session=SessionRead.model_validate(result.session),
                event=result.event,
                replayed=result.replayed,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get("", response_model=SessionPage)
    def list_sessions(
        authorized: AuthorizedRequest = Depends(read_access),
        state_filter: Annotated[
            SessionState | None,
            Query(alias="state"),
        ] = None,
        node_id: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SessionPage:
        try:
            result = repository.for_organization(authorized.principal.organization_id).list(
                state=state_filter,
                node_id=node_id,
                limit=limit,
                offset=offset,
            )
            return SessionPage(
                items=[SessionRead.model_validate(item) for item in result.items],
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{session_id}", response_model=SessionRead)
    def get_session(
        session_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> SessionRead:
        try:
            return SessionRead.model_validate(repository.for_organization(authorized.principal.organization_id).get(session_id))
        except Exception as error:
            raise _http_error(error) from error

    @router.patch("/{session_id}", response_model=SessionRead)
    def patch_session(
        session_id: str,
        payload: SessionPatch,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SessionRead:
        try:
            return SessionRead.model_validate(repository.for_organization(authorized.principal.organization_id).patch(session_id, payload))
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{session_id}/events", response_model=SessionEventsPage)
    def get_session_events(
        session_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SessionEventsPage:
        try:
            result = repository.for_organization(authorized.principal.organization_id).events(
                session_id,
                limit=limit,
                offset=offset,
            )
            return SessionEventsPage(
                items=result.items,
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    def register_transition_route(
        action: SessionAction,
    ) -> None:
        path = f"/{{session_id}}/{action.value}"

        def execute_transition(
            session_id: str,
            payload: SessionTransitionRequest,
            idempotency_key: IdempotencyKey,
            authorized: AuthorizedRequest = Depends(operate_access),
        ) -> SessionTransitionResponse:
            trusted_payload = payload.model_copy(
                update={
                    "actor_id": authorized.principal.subject,
                    "actor_source": authorized.principal.provider,
                }
            )
            try:
                result = repository.for_organization(authorized.principal.organization_id).transition(
                    session_id,
                    action,
                    trusted_payload,
                    idempotency_key=idempotency_key,
                )
                return SessionTransitionResponse(
                    session=SessionRead.model_validate(result.session),
                    event=result.event,
                    replayed=result.replayed,
                )
            except Exception as error:
                raise _http_error(error) from error

        execute_transition.__name__ = f"{action.value}_session"
        router.add_api_route(
            path,
            execute_transition,
            methods=["POST"],
            response_model=SessionTransitionResponse,
        )

    for session_action in SessionAction:
        register_transition_route(session_action)

    return router


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


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, SessionNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, SessionDomainError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": error.code,
                "message": str(error),
                "current_state": (
                    error.current_state.value
                    if error.current_state is not None
                    else None
                ),
                "action": error.action.value if error.action is not None else None,
            },
        )
    if isinstance(error, SessionConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, SessionRepositoryError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, HTTPException):
        return error
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "session_internal_error",
            "message": "session operation failed",
        },
    )
