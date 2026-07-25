from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Query, status

from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.sessions.api import IdempotencyKey, _http_error
from app.sessions.audit_repository import AuditedSessionRepository
from app.sessions.audit_schemas import (
    AuditLogRead,
    SessionAuditPage,
    SessionNoteCreate,
    SessionNoteRead,
    SessionNoteResponse,
    SessionNotesPage,
    SessionStageRead,
    SessionStageTransitionRead,
    StageAdvanceRequest,
    StageAdvanceResponse,
)


def create_session_audit_router(
    repository: AuditedSessionRepository,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["session audit"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
    )
    operate_access = _access_dependency(
        security_dependencies,
        Permission.OPERATE_SESSIONS,
    )
    audit_access = _access_dependency(
        security_dependencies,
        Permission.READ_AUDIT,
    )

    @router.post(
        "/{session_id}/stages/advance",
        response_model=StageAdvanceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def advance_stage(
        session_id: str,
        payload: StageAdvanceRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(operate_access),
    ) -> StageAdvanceResponse:
        try:
            result = repository.advance_stage(
                session_id,
                _trusted_command(payload, authorized),
                idempotency_key=idempotency_key,
            )
            return StageAdvanceResponse(
                stage=SessionStageRead.model_validate(result.stage),
                transition=SessionStageTransitionRead.model_validate(
                    result.transition
                ),
                event=result.event,
                replayed=result.replayed,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/stages",
        response_model=list[SessionStageRead],
    )
    def list_stages(
        session_id: str,
        _authorized: AuthorizedRequest = Depends(read_access),
    ) -> list[SessionStageRead]:
        try:
            return [
                SessionStageRead.model_validate(item)
                for item in repository.stages(session_id)
            ]
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{session_id}/notes",
        response_model=SessionNoteResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_note(
        session_id: str,
        payload: SessionNoteCreate,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(operate_access),
    ) -> SessionNoteResponse:
        try:
            result = repository.add_note(
                session_id,
                _trusted_command(payload, authorized),
                idempotency_key=idempotency_key,
            )
            return SessionNoteResponse(
                note=SessionNoteRead.model_validate(result.note),
                event=result.event,
                replayed=result.replayed,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/notes",
        response_model=SessionNotesPage,
    )
    def list_notes(
        session_id: str,
        _authorized: AuthorizedRequest = Depends(read_access),
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SessionNotesPage:
        try:
            result = repository.notes(
                session_id,
                limit=limit,
                offset=offset,
            )
            return SessionNotesPage(
                items=[
                    SessionNoteRead.model_validate(item) for item in result.items
                ],
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{session_id}/audit",
        response_model=SessionAuditPage,
    )
    def list_audit(
        session_id: str,
        _authorized: AuthorizedRequest = Depends(audit_access),
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SessionAuditPage:
        try:
            result = repository.audit(
                session_id,
                limit=limit,
                offset=offset,
            )
            return SessionAuditPage(
                items=[AuditLogRead.model_validate(item) for item in result.items],
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
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
