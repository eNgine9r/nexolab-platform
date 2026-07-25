from __future__ import annotations

import pytest

from app.operator_identity import (
    OperatorIdentityRequiredError,
    OperatorIdentityResolver,
)


def test_client_mode_uses_bounded_client_actor() -> None:
    resolver = OperatorIdentityResolver("client")

    identity = resolver.resolve({}, client_actor_id=f"  {'x' * 200}  ")

    assert identity.actor_id == "x" * 128
    assert identity.display_name is None
    assert identity.provider == "client"
    assert identity.authenticated is False


def test_tailscale_mode_uses_proxy_identity_and_ignores_client_actor() -> None:
    resolver = OperatorIdentityResolver("tailscale_serve")

    identity = resolver.resolve(
        {
            "tailscale-user-login": "operator@example.com",
            "tailscale-user-name": "=?utf-8?b?0J7Qv9C10YDQsNGC0L7RgCDQndCV0JrQodCe0JvQkNCR?=",
        },
        client_actor_id="spoofed-browser-actor",
    )

    assert identity.actor_id == "operator@example.com"
    assert identity.display_name == "Оператор НЕКСОЛАБ"
    assert identity.provider == "tailscale"
    assert identity.authenticated is True


def test_tailscale_mode_rejects_requests_without_user_identity() -> None:
    resolver = OperatorIdentityResolver("tailscale_serve")

    with pytest.raises(OperatorIdentityRequiredError):
        resolver.resolve({}, client_actor_id="browser-actor")
