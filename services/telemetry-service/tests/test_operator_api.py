from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.operator_api import create_operator_router
from app.operator_identity import OperatorIdentityResolver


def test_operator_session_reports_tailscale_identity() -> None:
    app = FastAPI()
    app.include_router(create_operator_router(OperatorIdentityResolver("tailscale_serve")))
    client = TestClient(app)

    response = client.get(
        "/api/v1/operator/session",
        headers={
            "Tailscale-User-Login": "operator@example.com",
            "Tailscale-User-Name": "NEXOLAB Operator",
            "X-Actor-Id": "spoofed-browser-actor",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "actor_id": "operator@example.com",
        "display_name": "NEXOLAB Operator",
        "provider": "tailscale",
        "authenticated": True,
    }


def test_operator_session_requires_tailscale_identity_in_proxy_mode() -> None:
    app = FastAPI()
    app.include_router(create_operator_router(OperatorIdentityResolver("tailscale_serve")))
    client = TestClient(app)

    response = client.get(
        "/api/v1/operator/session",
        headers={"X-Actor-Id": "browser-actor"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "operator_identity_required"
