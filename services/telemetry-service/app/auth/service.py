from __future__ import annotations

from app.auth.domain import (
    AuthenticationRequiredError,
    Principal,
    Role,
    permissions_for_role,
)
from app.auth.repository import AuthRepository
from app.auth.token import Hs256TokenValidator, JwtConfiguration


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

    def authenticate(self, authorization_header: str | None) -> Principal:
        if self._mode == "disabled":
            return Principal(
                subject="development-admin",
                organization_id=self._default_organization_id,
                role=Role.ADMIN,
                permissions=permissions_for_role(Role.ADMIN),
                email="development-admin@nexolab.local",
                display_name="Development administrator",
                provider="development",
            )

        token = _bearer_token(authorization_header)
        assert self._validator is not None
        claimed = self._validator.validate(token)
        return self._repository.resolve_principal(
            claimed,
            auto_provision_memberships=self._auto_provision_memberships,
        )


def _bearer_token(authorization_header: str | None) -> str:
    if authorization_header is None:
        raise AuthenticationRequiredError()
    scheme, separator, token = authorization_header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationRequiredError("Authorization must contain a Bearer token")
    return token.strip()
