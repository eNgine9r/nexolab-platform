from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from app.auth.domain import InvalidTokenError, Role
from app.auth.token import Hs256TokenValidator, JwtConfiguration


_SECRET = "nexolab-test-secret-that-is-longer-than-thirty-two-bytes"


def _encode(payload: dict[str, object], *, secret: str = _SECRET) -> str:
    header = {"alg": "HS256", "typ": "JWT"}

    def section(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    encoded_header = section(header)
    encoded_payload = section(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "iss": "https://auth.nexolab.test",
        "aud": "nexolab-api",
        "sub": "operator-1",
        "org_id": "laboratory-a",
        "role": "operator",
        "iat": 900,
        "exp": 1100,
        "jti": "token-1",
        "email": "operator@example.com",
        "name": "Operator One",
    }
    payload.update(overrides)
    return payload


def _validator() -> Hs256TokenValidator:
    return Hs256TokenValidator(
        JwtConfiguration(
            secret=_SECRET,
            issuer="https://auth.nexolab.test",
            audience="nexolab-api",
            leeway_seconds=0,
        )
    )


def test_valid_token_resolves_principal() -> None:
    principal = _validator().validate(_encode(_payload()), now=1000)

    assert principal.subject == "operator-1"
    assert principal.organization_id == "laboratory-a"
    assert principal.role is Role.OPERATOR
    assert principal.has(next(iter(principal.permissions)))
    assert principal.token_id == "token-1"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (_payload(exp=999), "access_token_expired"),
        (_payload(iss="https://wrong.example"), "invalid_token_issuer"),
        (_payload(aud="other-api"), "invalid_token_audience"),
        (_payload(role="owner"), "invalid_role_claim"),
        (_payload(nbf=1001), "access_token_not_active"),
    ],
)
def test_invalid_claims_are_rejected(
    payload: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(InvalidTokenError) as raised:
        _validator().validate(_encode(payload), now=1000)

    assert raised.value.code == code


def test_signature_mismatch_is_rejected() -> None:
    with pytest.raises(InvalidTokenError) as raised:
        _validator().validate(
            _encode(_payload(), secret="different-secret-that-is-also-long-enough-for-hmac"),
            now=1000,
        )

    assert raised.value.code == "invalid_access_token_signature"


def test_short_secret_is_rejected_at_startup() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Hs256TokenValidator(
            JwtConfiguration(
                secret="too-short",
                issuer="issuer",
                audience="audience",
            )
        )
