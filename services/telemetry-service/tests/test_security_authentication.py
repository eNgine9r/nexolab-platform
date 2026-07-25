from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.security.authentication import (
    InvalidBearerTokenError,
    JwtAuthenticator,
    MissingBearerTokenError,
)


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"


def authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        public_key=SECRET,
        algorithm="HS256",
        issuer=ISSUER,
        audience=AUDIENCE,
        provider="test-oidc",
    )


def token(**overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": "operator-123",
        "email": "operator@example.test",
        "name": "NEXOLAB Operator",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_verified_token_returns_provider_neutral_identity() -> None:
    claims = authenticator().verify(f"Bearer {token()}")

    assert claims.provider == "test-oidc"
    assert claims.subject == "operator-123"
    assert claims.email == "operator@example.test"
    assert claims.display_name == "NEXOLAB Operator"


def test_missing_bearer_token_is_rejected() -> None:
    with pytest.raises(MissingBearerTokenError):
        authenticator().verify(None)


def test_wrong_audience_is_rejected() -> None:
    with pytest.raises(InvalidBearerTokenError):
        authenticator().verify(f"Bearer {token(aud='wrong-api')}")


def test_expired_token_is_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(InvalidBearerTokenError):
        authenticator().verify(
            f"Bearer {token(iat=now - timedelta(minutes=10), exp=now - timedelta(minutes=5))}"
        )
