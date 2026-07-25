from __future__ import annotations

from app.auth.domain import (
    AuthenticationRequiredError,
    Principal,
    Role,
    permissions_for_role,
)
from app.auth.repository import AuthRepository
from app.auth.token import Hs256TokenValidator, JwtConfiguration


_WEBSOCKET_PROTOCOL = "nexolab.v1"
_WEBSOCKET_TOKEN_PREFIX = "nexolab.jwt."


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        *,
        mode: str,
        jwt_secret: str | None,
        jwt_issuer: str,
        jwt_audience: str,
        jwt_leeway_seconds: int,
        default_organization_id: str,
        auto_provision_memberships: bool,
    ) -> None:
        self._repository = repository
        self._mode = mode
        self._default_organization_id = default_organization_id
        self._auto_provision_memberships = auto_provision_memberships
        self._validator: Hs256TokenValidator | None = None

        if mode == "jwt":
            if jwt_secret is None:
                raise ValueError("AUTH_JWT_SECRET is required when AUTH_MODE=jwt")
            self._validator = Hs256TokenValidator(
                JwtConfiguration(
                    secret=jwt_secret,
                    issuer=jwt_issuer,
                    audience=jwt_audience,
                    leeway_seconds=jwt_leeway_seconds,
                )
            )
        elif mode != "disabled":
            raise ValueError(f"unsupported AUTH_MODE {mode!r}")

    @property
    def persistence_enforced(self) -> bool:
        return self._mode == "jwt"

    @property
    def websocket_subprotocol(self) -> str:
        return _WEBSOCKET_PROTOCOL

    def authenticate(self, authorization_header: str | None) -> Principal:
        if self._mode == "disabled":
            return self._development_principal()

        token = _bearer_token(authorization_header)
        return self._authenticate_token(token)

    def authenticate_websocket(
        self,
        *,
        authorization_header: str | None,
        protocol_header: str | None,
    ) -> Principal:
        if self._mode == "disabled":
            return self._development_principal()

        if authorization_header is not None:
            return self.authenticate(authorization_header)

        token = _websocket_protocol_token(protocol_header)
        return self._authenticate_token(token)

    def _authenticate_token(self, token: str) -> Principal:
        assert self._validator is not None
        claimed = self._validator.validate(token)
        return self._repository.resolve_principal(
            claimed,
            auto_provision_memberships=self._auto_provision_memberships,
        )

    def _development_principal(self) -> Principal:
        return Principal(
            subject="development-admin",
            organization_id=self._default_organization_id,
            role=Role.ADMIN,
            permissions=permissions_for_role(Role.ADMIN),
            email="development-admin@nexolab.local",
            display_name="Development administrator",
            provider="development",
        )


def _bearer_token(authorization_header: str | None) -> str:
    if authorization_header is None:
        raise AuthenticationRequiredError()
    scheme, separator, token = authorization_header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationRequiredError("Authorization must contain a Bearer token")
    return token.strip()


def _websocket_protocol_token(protocol_header: str | None) -> str:
    if protocol_header is None:
        raise AuthenticationRequiredError("WebSocket authentication protocol is required")
    protocols = [item.strip() for item in protocol_header.split(",") if item.strip()]
    if _WEBSOCKET_PROTOCOL not in protocols:
        raise AuthenticationRequiredError("NEXOLAB WebSocket protocol is required")
    for protocol in protocols:
        if protocol.startswith(_WEBSOCKET_TOKEN_PREFIX):
            token = protocol.removeprefix(_WEBSOCKET_TOKEN_PREFIX).strip()
            if token:
                return token
    raise AuthenticationRequiredError("WebSocket Bearer token is required")
