"""Fail-closed external NEXOLAB HTTPS staging readiness policy tests.

Network-free; never touches production or connects to controllers.
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILE = ROOT / "scripts" / "inspection" / "nexolab_external_https_gate.py"
SPEC = importlib.util.spec_from_file_location("nexolab_external_https_gate", FILE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SAFE = {
    "profile": "isolated_external_stage",
    "public_origin": "https://nexolab-edge-01.example.ts.net",
    "api_base_url": "https://nexolab-edge-01.example.ts.net",
    "websocket_url": "wss://nexolab-edge-01.example.ts.net/api/v1/telemetry/live",
    "frontend_origin": "http://127.0.0.1:3100",
    "private_api_origin": "http://172.18.48.66:8082",
    "gateway_origin": "http://127.0.0.1:18790",
    "identity_gateway_origin": "http://127.0.0.1:4180",
    "frontend_auth_provider": "local",
    "backend_auth_mode": "jwt",
    "backend_local_auth": True,
    "dedicated_hostname": True,
    "named_identity_allowlist": True,
    "identity_mfa": True,
    "dashboard_rbac": True,
    "direct_wan_port_forwarding": False,
    "public_route_enabled": False,
    "object_storage_externally_exposed": False,
    "object_storage_browser_support": "blocked_pending_proxy",
    "modbus_writes_enabled": False,
    "owner_publication_authority_confirmed": True,
}


class ExternalHttpsGateTests(unittest.TestCase):
    def test_safe_profile_passes_stage_only(self) -> None:
        MODULE.validate(dict(SAFE))

    def test_unknown_field_rejected(self) -> None:
        self._reject(extra="unexpected")

    def test_missing_field_rejected(self) -> None:
        d = dict(SAFE)
        del d["identity_mfa"]
        with self.assertRaises(MODULE.GateError):
            MODULE.validate(d)

    def test_http_public_denied(self) -> None:
        self._reject(public_origin="http://nexolab-edge-01.example.ts.net")

    def test_websocket_insecure_denied(self) -> None:
        self._reject(websocket_url="ws://nexolab-edge-01.example.ts.net/api/v1/telemetry/live")

    def test_api_cross_origin_denied(self) -> None:
        self._reject(api_base_url="https://evil.example.com")

    def test_api_origin_query_denied(self) -> None:
        self._reject(api_base_url="https://nexolab-edge-01.example.ts.net/?token=foo")

    def test_websocket_query_token_denied(self) -> None:
        self._reject(websocket_url="wss://nexolab-edge-01.example.ts.net/api/v1/telemetry/live?token=foo")

    def test_publication_authority_required(self) -> None:
        self._reject(owner_publication_authority_confirmed=False)

    def test_publication_authority_must_be_exact_true(self) -> None:
        self._reject(owner_publication_authority_confirmed=1)

    def test_public_route_denied(self) -> None:
        self._reject(public_route_enabled=True)

    def test_identity_mfa_denied(self) -> None:
        self._reject(identity_mfa=False)

    def test_named_identity_denied(self) -> None:
        self._reject(named_identity_allowlist=False)

    def test_no_local_auth_denied(self) -> None:
        self._reject(backend_local_auth=False)

    def test_no_backend_jwt_denied(self) -> None:
        self._reject(backend_auth_mode="disabled")

    def test_no_rbac_denied(self) -> None:
        self._reject(dashboard_rbac=False)

    def test_modbus_write_denied(self) -> None:
        self._reject(modbus_writes_enabled=True)

    def test_object_storage_public_denied(self) -> None:
        self._reject(object_storage_externally_exposed=True)

    def test_unapproved_storage_proxy_denied(self) -> None:
        self._reject(object_storage_browser_support="exposed")

    def test_public_gateway_denied(self) -> None:
        self._reject(gateway_origin="http://0.0.0.0:18790")

    def test_unapproved_backend_port_denied(self) -> None:
        self._reject(private_api_origin="http://172.18.48.66:9000")

    def test_wan_forwarding_denied(self) -> None:
        self._reject(direct_wan_port_forwarding=True)

    def test_path_prefix_denied(self) -> None:
        self._reject(public_origin="https://btc-radar.example.ts.net/nexolab")

    def test_ip_public_origin_denied(self) -> None:
        self._reject(public_origin="https://100.113.204.81")

    def _reject(self, **changes: object) -> None:
        candidate = dict(SAFE)
        candidate.update(changes)
        with self.assertRaises(MODULE.GateError):
            MODULE.validate(candidate)


if __name__ == "__main__":
    unittest.main()
