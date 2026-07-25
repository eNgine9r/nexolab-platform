from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from app.auth.domain import InvalidTokenError, Principal, Role, permissions_for_role


@dataclass(frozen=True, slots=True)
class JwtConfiguration:
    secret: str
    issuer: str
    audience: str
    leeway_seconds: int = 30


class Hs256TokenValidator:
    """Strict JWT HS256 validation for externally issued NEXOLAB access tokens."""

    def __init__(self, configuration: JwtConfiguration) -> None:
        if len(configuration.secret.encode("utf-8")) < 32:
            raise ValueError("AUTH_JWT_SECRET must contain at least 32 bytes")
        self._configuration = configuration

    def validate(self, token: str, *, now: float | None = None) -> Principal:
        if not token or len(token) > 8192:
            raise InvalidTokenError("invalid_access_token", "access token is missing or too large")

        encoded_header, encoded_payload, encoded_signature = _split_token(token)
        header = _decode_json(encoded_header, section="header")
        payload = _decode_json(encoded_payload, section="payload")

        if header.get("alg") != "HS256":
            raise InvalidTokenError("unsupported_token_algorithm", "access token must use HS256")
        if header.get("typ") not in {None, "JWT"}:
            raise InvalidTokenError("invalid_access_token", "access token type is invalid")

        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected_signature = hmac.new(
            self._configuration.secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual_signature = _decode_base64url(encoded_signature, section="signature")
        if not hmac.compare_digest(actual_signature, expected_signature):
            raise InvalidTokenError("invalid_access_token_signature", "access token signature is invalid")

        timestamp = time.time() if now is None else now
        leeway = self._configuration.leeway_seconds
        _validate_registered_claims(
            payload,
            issuer=self._configuration.issuer,
            audience=self._configuration.audience,
            now=timestamp,
            leeway=leeway,
        )

        subject = _required_string(payload, "sub")
        organization_id = _required_string(payload, "org_id")
        role_value = _required_string(payload, "role")
        try:
            role = Role(role_value)
        except ValueError as error:
            raise InvalidTokenError("invalid_role_claim", "access token role is not supported") from error

        return Principal(
            subject=subject,
            organization_id=organization_id,
            role=role,
            permissions=permissions_for_role(role),
            email=_optional_string(payload, "email"),
            display_name=_optional_string(payload, "name"),
            token_id=_optional_string(payload, "jti"),
            provider="jwt",
        )


def _split_token(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise InvalidTokenError("malformed_access_token", "access token must contain three JWT sections")
    return parts[0], parts[1], parts[2]


def _decode_base64url(value: str, *, section: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise InvalidTokenError(
            "malformed_access_token",
            f"access token {section} is not valid base64url",
        ) from error


def _decode_json(value: str, *, section: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_decode_base64url(value, section=section))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InvalidTokenError(
            "malformed_access_token",
            f"access token {section} is not valid JSON",
        ) from error
    if not isinstance(decoded, dict):
        raise InvalidTokenError(
            "malformed_access_token",
            f"access token {section} must be a JSON object",
        )
    return decoded


def _validate_registered_claims(
    payload: dict[str, Any],
    *,
    issuer: str,
    audience: str,
    now: float,
    leeway: int,
) -> None:
    if payload.get("iss") != issuer:
        raise InvalidTokenError("invalid_token_issuer", "access token issuer is invalid")

    audience_claim = payload.get("aud")
    audiences = (
        [audience_claim]
        if isinstance(audience_claim, str)
        else audience_claim
        if isinstance(audience_claim, list)
        else []
    )
    if audience not in audiences:
        raise InvalidTokenError("invalid_token_audience", "access token audience is invalid")

    expires_at = _numeric_claim(payload, "exp")
    if expires_at <= now - leeway:
        raise InvalidTokenError("access_token_expired", "access token has expired")

    issued_at = _numeric_claim(payload, "iat", required=False)
    if issued_at is not None and issued_at > now + leeway:
        raise InvalidTokenError("invalid_token_issued_at", "access token was issued in the future")

    not_before = _numeric_claim(payload, "nbf", required=False)
    if not_before is not None and not_before > now + leeway:
        raise InvalidTokenError("access_token_not_active", "access token is not active yet")


def _numeric_claim(
    payload: dict[str, Any],
    name: str,
    *,
    required: bool = True,
) -> float | None:
    value = payload.get(name)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidTokenError("invalid_access_token", f"access token {name} claim must be numeric")
    return float(value)


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InvalidTokenError("invalid_access_token", f"access token {name} claim is invalid")
    return value.strip()


def _optional_string(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InvalidTokenError("invalid_access_token", f"access token {name} claim is invalid")
    return value.strip()
