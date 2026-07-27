from __future__ import annotations

from app.nodes.broker_adapter import parse_dynamic_security_client


def test_missing_disabled_field_normalizes_to_enabled() -> None:
    state = parse_dynamic_security_client(
        "\n".join(
            [
                "Username: node:org:edge-01",
                "Clientid: nexolab-org-edge-01",
                "Roles: nexolab-node-org-edge-01 (priority: 100)",
            ]
        )
    )

    assert state.client_id == "nexolab-org-edge-01"
    assert state.disabled is False
    assert state.roles == frozenset({"nexolab-node-org-edge-01"})


def test_explicit_disabled_field_remains_authoritative() -> None:
    state = parse_dynamic_security_client(
        "\n".join(
            [
                "Clientid: nexolab-org-edge-01",
                "Disabled: true",
            ]
        )
    )

    assert state.disabled is True
