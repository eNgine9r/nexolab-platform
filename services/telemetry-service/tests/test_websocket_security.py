from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import Role
from tests.websocket_test_support import websocket_session

SECRET = "test-only-websocket-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@example.test",
            "name": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def app_for(tmp_path: Path):
    return create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'secure-live.db'}",
            auto_create_schema=True,
            mqtt_enabled=False,
            auth_mode="jwt",
            auth_default_organization_id=ORGANIZATION_ID,
            auth_jwt_public_key=SECRET,
            auth_jwt_algorithm="HS256",
            auth_jwt_issuer=ISSUER,
            auth_jwt_audience=AUDIENCE,
            auth_jwt_provider="test-oidc",
            websocket_auth_timeout_seconds=0.25,
            websocket_heartbeat_seconds=30,
        )
    )


def provision(app, *, subject: str, roles: set[Role]) -> None:
    repository = app.state.security_repository
    repository.provision_organization(organization_id=ORGANIZATION_ID, slug="nexolab-lab", name="NEXOLAB Laboratory")
    repository.provision_organization(organization_id=OTHER_ORGANIZATION_ID, slug="other-lab", name="Other Laboratory")
    repository.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=VerifiedIdentityClaims(provider="test-oidc", subject=subject, email=f"{subject}@example.test", display_name=subject),
        roles=roles,
    )


def authentication(subject: str, organization_id: str = ORGANIZATION_ID) -> dict[str, str]:
    return {"type": "authenticate", "access_token": token(subject), "organization_id": organization_id}


def temperature_event(captured_at: datetime) -> TelemetryEvent:
    return TelemetryEvent(event_id=uuid4(), node_id="edge-01", captured_at=captured_at, metric="temperature.probe", value=4.2, unit="degC", quality="valid", source="dixell-xjp60d", equipment_id="K106", channel_id="106-03", alarm=None, raw_value=42, raw_status=4354)


def test_authenticated_viewer_receives_ack_before_replay(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    subject = "viewer-user"
    captured_at = datetime(2026, 7, 26, 6, 0, tzinfo=UTC)
    sample = temperature_event(captured_at)
    with TestClient(app) as client:
        provision(app, subject=subject, roles={Role.VIEWER})
        assert app.state.database.persist(sample, sample.normalized_payload())
        query = urlencode({"channel_id": "106-03", "after": (captured_at - timedelta(seconds=1)).isoformat()})
        with websocket_session(client, f"/api/v1/telemetry/live?{query}") as websocket:
            assert app.state.runtime.snapshot()["websocket_clients"] == 0
            websocket.send_json(authentication(subject))
            acknowledgement = websocket.receive_json()
            replay = websocket.receive_json()
        assert acknowledgement == {"type": "authenticated", "subject": subject, "organization_id": ORGANIZATION_ID}
        assert replay["event_id"] == str(sample.event_id)
        assert replay["channel_id"] == "106-03"


def test_missing_websocket_token_is_rejected_before_registration(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    with TestClient(app) as client:
        with websocket_session(client, "/api/v1/telemetry/live") as websocket:
            websocket.send_json({"type": "authenticate", "access_token": "", "organization_id": ORGANIZATION_ID})
            response = websocket.receive_json()
        assert response["type"] == "error"
        assert response["code"] == "missing_bearer_token"
        assert app.state.runtime.snapshot()["websocket_clients"] == 0


def test_cross_organization_websocket_is_denied(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    subject = "viewer-user"
    with TestClient(app) as client:
        provision(app, subject=subject, roles={Role.VIEWER})
        with websocket_session(client, "/api/v1/telemetry/live") as websocket:
            websocket.send_json(authentication(subject, OTHER_ORGANIZATION_ID))
            response = websocket.receive_json()
        assert response["type"] == "error"
        assert response["code"] == "organization_membership_not_found"
        assert app.state.runtime.snapshot()["websocket_clients"] == 0
