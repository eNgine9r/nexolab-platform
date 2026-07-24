from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

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
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["session audit"])

    @router.post(
        "/{session_id}/stages/advance",
        response_model=StageAdvanceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def advance_stage(
        session_id: str,
        payload: StageAdvanceRequest,
        idempotency_key: IdempotencyKey,
    ) -> StageAdvanceResponse:
        try:
            result = repository.advance_stage(
                session_id,
                payload,
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
    def list_stages(session_id: str) -> list[SessionStageRead]:
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
    ) -> SessionNoteResponse:
        try:
            result = repository.add_note(
                session_id,
                payload,
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
