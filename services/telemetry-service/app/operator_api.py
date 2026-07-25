from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.operator_identity import (
    OperatorIdentityRequiredError,
    OperatorIdentityResolver,
)


class OperatorSessionResponse(BaseModel):
    actor_id: str
    display_name: str | None
    provider: Literal["client", "tailscale"]
    authenticated: bool


def create_operator_router(resolver: OperatorIdentityResolver) -> APIRouter:
    router = APIRouter(prefix="/api/v1/operator", tags=["operator-session"])

    @router.get("/session", response_model=OperatorSessionResponse)
    def get_operator_session(
        request: Request,
        actor_id: str | None = Header(default=None, alias="X-Actor-Id", max_length=128),
    ) -> OperatorSessionResponse:
        try:
            identity = resolver.resolve(request.headers, client_actor_id=actor_id)
        except OperatorIdentityRequiredError as error:
            raise HTTPException(
                status_code=401,
                detail={"code": error.code, "message": str(error)},
            ) from error
        return OperatorSessionResponse(
            actor_id=identity.actor_id,
            display_name=identity.display_name,
            provider=identity.provider,
            authenticated=identity.authenticated,
        )

    return router
