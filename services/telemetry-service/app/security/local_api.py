from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.security.local_service import (
    InvalidLocalCredentialsError,
    InvalidLocalRefreshTokenError,
    LocalAccountAccessError,
    LocalAccountLockedError,
    LocalAuthService,
    LocalAuthenticationError,
    LocalTokenPair,
)


class LocalLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LocalRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=1024)


class LocalLogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=1024)


class LocalTokenResponse(BaseModel):
    token_type: str = "Bearer"
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int


def create_local_auth_router(service: LocalAuthService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth/local", tags=["local-auth"])

    @router.post("/login", response_model=LocalTokenResponse)
    def login(payload: LocalLoginRequest, request: Request, response: Response) -> LocalTokenResponse:
        try:
            pair = service.login(
                username=payload.username,
                password=payload.password,
                source_ip=(request.client.host if request.client is not None else None),
                user_agent=request.headers.get("User-Agent"),
            )
        except InvalidLocalCredentialsError as error:
            raise _unauthorized(error.code, "Неправильний логін або пароль.") from error
        except LocalAccountLockedError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": error.code,
                    "message": "Обліковий запис тимчасово заблоковано після невдалих спроб входу.",
                },
                headers={"Retry-After": str(error.retry_after_seconds)},
            ) from error
        except LocalAccountAccessError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": error.code, "message": str(error)},
            ) from error
        _no_store(response)
        return _token_response(pair)

    @router.post("/refresh", response_model=LocalTokenResponse)
    def refresh(payload: LocalRefreshRequest, response: Response) -> LocalTokenResponse:
        try:
            pair = service.refresh(payload.refresh_token)
        except InvalidLocalRefreshTokenError as error:
            raise _unauthorized(error.code, "Локальна сесія завершена або недійсна.") from error
        except LocalAccountAccessError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": error.code, "message": str(error)},
            ) from error
        _no_store(response)
        return _token_response(pair)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(payload: LocalLogoutRequest, response: Response) -> Response:
        try:
            service.logout(payload.refresh_token)
        except LocalAuthenticationError:
            pass
        _no_store(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    return router


def _token_response(pair: LocalTokenPair) -> LocalTokenResponse:
    return LocalTokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
        refresh_expires_in=pair.refresh_expires_in,
    )


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
