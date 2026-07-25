from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import Header, HTTPException, status

from app.security.authentication import (
    AuthenticationError,
    JwtAuthenticator,
    VerifiedIdentityClaims,
)
from app.security.authorization import (
    AuthenticatedPrincipal,
    Permission,
    Role,
    authorize,
)
from app.security.repository import (
    IdentityNotProvisionedError,
    MembershipSummary,
    OrganizationMembershipNotFoundError,
    SecurityRepository,
    SecuritySession,
)


@dataclass(frozen=True, slots=True)
class AuthorizedRequest:
    identity_id: str | None
    principal: AuthenticatedPrincipal


class SecurityDependencies:
    def __init__(
        self,
        repository: SecurityRepository,
        *,
        mode: Literal["disabled", "jwt"],
        authenticator: JwtAuthenticator | None,
        default_organization_id: str,
    ) -> None:
        if mode == "jwt" and authenticator is None:
            raise ValueError("JWT authenticator is required in jwt mode")
        self._repository = repository
        self._mode = mode
        self._authenticator = authenticator
        self._default_organization_id = default_organization_id

    def current_session(
        self,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> SecuritySession:
        if self._mode == "disabled":
            membership = MembershipSummary(
                organization_id=self._default_organization_id,
                organization_slug="development",
                organization_name="Development organization",
                roles=frozenset({Role.ADMINISTRATOR}),
            )
            return SecuritySession(
                identity_id="development-system",
                provider="disabled",
                subject="development-system",
                email=None,
                display_name="Development system",
                memberships=(membership,),
            )

        claims = self._verify(authorization)
        try:
            return self._repository.resolve_session(claims)
        except IdentityNotProvisionedError as error:
            raise _forbidden(error.code, str(error)) from error

    def authorized_request(
        self,
        permission: Permission,
    ) -> Callable[..., AuthorizedRequest]:
        def dependency(
            authorization: str | None = Header(default=None, alias="Authorization"),
            selected_organization_id: str | None = Header(
                default=None,
                alias="X-Organization-ID",
            ),
        ) -> AuthorizedRequest:
            resolved_organization_id = self._resolve_organization_id(
                selected_organization_id
            )
            if self._mode == "disabled":
                principal = AuthenticatedPrincipal(
                    subject="development-system",
                    organization_id=resolved_organization_id,
                    roles=frozenset({Role.ADMINISTRATOR}),
                    display_name="Development system",
                    provider="disabled",
                )
                identity_id: str | None = None
            else:
                claims = self._verify(authorization)
                try:
                    identity_id, principal = self._repository.resolve_principal(
                        claims,
                        organization_id=resolved_organization_id,
                    )
                except IdentityNotProvisionedError as error:
                    raise _forbidden(error.code, str(error)) from error
                except OrganizationMembershipNotFoundError as error:
                    raise _forbidden(error.code, str(error)) from error

            decision = authorize(
                principal,
                permission,
                resource_organization_id=resolved_organization_id,
            )
            if not decision.allowed:
                raise _forbidden(
                    decision.code,
                    f"permission {permission.value!r} is required",
                )
            return AuthorizedRequest(identity_id=identity_id, principal=principal)

        return dependency

    def _verify(self, authorization: str | None) -> VerifiedIdentityClaims:
        assert self._authenticator is not None
        try:
            return self._authenticator.verify(authorization)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": error.code, "message": str(error)},
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

    def _resolve_organization_id(self, organization_id: str | None) -> str:
        if organization_id is None or not organization_id.strip():
            if self._mode == "disabled":
                return self._default_organization_id
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "organization_header_required",
                    "message": "X-Organization-ID header is required",
                },
            )
        return organization_id.strip()


def _forbidden(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )
