from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, status

from app.sessions.api import _http_error
from app.sessions.configuration import ConfiguredSessionRepository
from app.sessions.stage_schemas import (
    SessionStageRead,
    StageAdvanceRequest,
    StageAdvanceResponse,
    StagePlanCreate,
    StagePlanMutationResponse,
    StageTransitionRead,
)
from app.sessions.schemas import SessionEventRead, SessionRead


IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128),
]


def create_stage_router(repository: ConfiguredSessionRepository) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions", tags=["session stages"])

    @router.post(
        "/{session_id}/stages",
        response_model=StagePlanMutationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def configure_stage_plan(
        session_id: str,
        payload: StagePlanCreate,
        idempotency_key: IdempotencyKey,
    ) -> StagePlanMutationResponse:
        try:
            result = repository.configure_stage_plan(
                session_id,
                payload,
                idempotency_key=idempotency_key,
            )
            return StagePlanMutationResponse(
                stages=[
                    SessionStageRead.model_validate(item) for item in result.stages
                ],
                event=SessionEventRead.model_validate(result.event),
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
        "/{session_id}/stages/advance",
        response_model=StageAdvanceResponse,
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
                session=SessionRead.model_validate(result.session),
                current_stage=SessionStageRead.model_validate(
                    result.current_stage
                ),
                transition=StageTransitionRead.model_validate(result.transition),
                event=SessionEventRead.model_validate(result.event),
                replayed=result.replayed,
            )
        except Exception as error:
            raise _http_error(error) from error

    return router
