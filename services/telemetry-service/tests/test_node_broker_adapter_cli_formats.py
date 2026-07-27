from __future__ import annotations

from app.nodes.broker_adapter import parse_dynamic_security_client


def test_parse_dynamic_security_client_accepts_mosquitto_prefixed_role() -> None:
    state = parse_dynamic_security_client(
        "\n".join(
            (
                "Username: node:org-a:edge-01",
                "Clientid: nexolab-org-a-edge-01",
                "Disabled: false",
                "Roles: nexolab-node-org-a-edge-01 (priority: 100)",
            )
        )
    )

    assert state.client_id == "nexolab-org-a-edge-01"
    assert state.disabled is False
    assert state.roles == frozenset({"nexolab-node-org-a-edge-01"})


def test_parse_dynamic_security_client_accepts_multiline_role_format() -> None:
    state = parse_dynamic_security_client(
        "\n".join(
            (
                "Clientid: nexolab-org-a-edge-01",
                "Disabled: true",
                "Roles:",
                "  nexolab-node-org-a-edge-01 (priority: 100)",
            )
        )
    )

    assert state.disabled is True
    assert state.roles == frozenset({"nexolab-node-org-a-edge-01"})
