from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app


_SECRET = "nexolab-test-secret-that-is-longer-than-thirty-two-bytes"
_ISSUER = "https://auth.nexolab.test"
_AUDIENCE = "nexolab-api"


def _token(*, role: str = "viewer") -> str:
    now = datetime.now(UTC)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": "websocket-viewer",
        "org_id": "laboratory-a",
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }

    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    encoded_header = encode(header)
    encoded_payload = encode(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return (
        f"{encoded_header}.{encoded_payload}."
        f"{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url=f"sqlite+pysqlite:///{tmp_path / 'websocket-auth.db'}",
                auto_create_schema=True,
                mqtt_enabled=False,
                retention_enabled=False,
                auth_mode="jwt",
                auth_jwt_secret=_SECRET,
                auth_jwt_issuer=_ISSUER,
                auth_jwt_audience=_AUDIENCE,
                auth_auto_provision_memberships=True,
            )
        )
    )


def test_browser_subprotocol_authenticates_websocket(tmp_path: Path) -> None:
    token = _token()
    with _client(tmp_path) as client:
        with client.websocket_connect(
            "/api/v1/telemetry/live",
            subprotocols=["nexolab.v1", f"nexolab.jwt.{token}"],
        ) as websocket:
            assert websocket.accepted_subprotocol == "nexolab.v1"


def test_missing_websocket_token_is_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with pytest.raises(WebSocketDisconnect) as raised:
            with client.websocket_connect(
                "/api/v1/telemetry/live",
                subprotocols=["nexolab.v1"],
            ):
                pass

    assert raised.value.code == 4401
