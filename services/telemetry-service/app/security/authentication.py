from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt


class AuthenticationError(RuntimeError):
    code = "authentication_failed"


class MissingBearerTokenError(AuthenticationError):
    code = "missing_bearer_token"


class InvalidBearerTokenError(AuthenticationError):
    code = "invalid_bearer_token"


@dataclass(frozen=True, slots=True)
class VerifiedIdentityClaims:
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider is required")
        if not self.subject.strip():
            raise ValueError("subject is required")


class JwtAuthenticator:
    def __init__(
        self,
        *,
        public_key: str,
        algorithm: str,
        issuer: str | None,
        audience: str | None,
        provider: str,
    ) -> None:
        if not public_key.strip():
            raise ValueError("JWT public key is required")
        if not algorithm.strip():
            raise ValueError("JWT algorithm is required")
        if not provider.strip():
            raise ValueError("JWT provider is required")
        self._public_key = public_key
        self._algorithm = algorithm
        self._issuer = issuer or None
        self._audience = audience or None
        self._provider = provider

    def verify(self, authorization_header: str | None) -> VerifiedIdentityClaims:
        token = _extract_bearer_token(authorization_header)
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": ["exp", "iat", "sub"],
                    "verify_iss": self._issuer is not None,
                    "verify_aud": self._audience is not None,
                },
            )
        except jwt.PyJWTError as error:
            raise InvalidBearerTokenError("bearer token validation failed") from error

        subject = _required_string(payload, "sub")
        email = _optional_string(payload, "email")
        display_name = _optional_string(payload, "name") or _optional_string(
            payload, "preferred_username"
        )
        return VerifiedIdentityClaims(
            provider=self._provider,
            subject=subject,
            email=email,
            display_name=display_name,
        )


def _extract_bearer_token(authorization_header: str | None) -> str:
    if authorization_header is None:
        raise MissingBearerTokenError("Authorization bearer token is required")
    scheme, separator, value = authorization_header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not value.strip():
        raise MissingBearerTokenError("Authorization bearer token is required")
    return value.strip()


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidBearerTokenError(f"JWT claim {key!r} is required")
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidBearerTokenError(f"JWT claim {key!r} must be a string")
    normalized = value.strip()
    return normalized or None
