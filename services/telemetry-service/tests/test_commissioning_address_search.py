import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.commissioning.address_search import AddressSearchRequest, search_address
from app.commissioning.api import create_commissioning_router
from app.commissioning.preflight_client import DeviceAgentPreflightError
from app.security.authorization import Permission


def command(**overrides):
    data = dict(
        node_id="edge-01",
        bus_id="commissioning-1234567890abcdef",
        stable_transport_identifier="/dev/serial/by-id/usb-test",
        unit_id=7,
        profile_id="dixell-xjp60d",
        profile_version="dixell-xjp60d-fc03-v1",
        isolated_bus_confirmed=True,
    )
    data.update(overrides)
    return data


def evidence(**overrides):
    data = command()
    data.pop("isolated_bus_confirmed")
    data.update(
        schema_version=1,
        state="completed",
        attempted=1,
        total=1,
        candidates=[7],
        exception_addresses=[],
        error_code=None,
        modbus_writes="none",
        hardware_writes="none",
    )
    data.update(overrides)
    return data


def test_strict_input_rejects_write_scope_and_missing_isolation():
    for change in (
        {"isolated_bus_confirmed": False},
        {"isolated_bus_confirmed": 1},
        {"unit_id": True},
        {"unit_id": 0},
        {"bus_id": "rs485-main"},
        {"register": 256},
        {"profile_id": "other"},
    ):
        with pytest.raises(ValidationError):
            AddressSearchRequest.model_validate(command(**change))


def test_general_search_supports_configured_bus_and_pins_all_catalog_profiles():
    from app.commissioning.catalog import SUPPORTED_DEVICE_PROFILES
    for profile in SUPPORTED_DEVICE_PROFILES:
        data=command(bus_id="rs485-sdm120",profile_id=profile.id,profile_version=profile.version)
        data.pop("isolated_bus_confirmed")
        data["read_only_confirmed"]=True
        parsed=AddressSearchRequest.model_validate(data)
        assert parsed.read_only_confirmed is True
    for change in ({"read_only_confirmed":False},{"profile_version":"unknown"}):
        data.update(change)
        with pytest.raises(ValidationError): AddressSearchRequest.model_validate(data)


def test_transport_is_bounded_and_pins_identity():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(evidence()).encode()
    with patch("app.commissioning.address_search._open_address_request", return_value=response) as open_url:
        result = search_address("http://127.0.0.1:8081", AddressSearchRequest.model_validate(command()))
    request = open_url.call_args.args[0]
    wire = json.loads(request.data)
    assert wire["first_unit_id"] == wire["last_unit_id"] == 7
    assert wire["deadline_seconds"] == 2.0
    assert open_url.call_args.kwargs["timeout"] == 4.0
    assert result.candidates == [7]
    for invalid in (
        evidence(node_id="other"),
        evidence(candidates=[8]),
        evidence(state="failed"),
        evidence(modbus_writes="present"),
    ):
        response.read.return_value = json.dumps(invalid).encode()
        with patch(
            "app.commissioning.address_search._open_address_request", return_value=response
        ), pytest.raises(DeviceAgentPreflightError):
            search_address("http://127.0.0.1:8081", AddressSearchRequest.model_validate(command()))


def test_endpoint_requires_manage_permission_before_touching_agent():
    class Denied:
        def authorized_request(self, permission):
            def check():
                assert permission == Permission.MANAGE_EQUIPMENT
                raise HTTPException(403, "denied")

            return check

    service = Mock()
    app = FastAPI()
    app.include_router(create_commissioning_router(Mock(), Denied(), preflight_service=service))
    response = TestClient(app).post("/api/v1/equipment/commissioning/address-search", json=command())
    assert response.status_code == 403
    service.client.search_address.assert_not_called()


def test_endpoint_passes_validated_request_without_persistent_job_state():
    service = Mock()
    service.client.search_address.return_value = evidence()
    app = FastAPI()
    app.include_router(create_commissioning_router(Mock(), preflight_service=service))
    response = TestClient(app).post("/api/v1/equipment/commissioning/address-search", json=command())
    assert response.status_code == 200
    assert response.json()["candidates"] == [7]
    assert service.client.search_address.call_args.args[0].unit_id == 7


def test_transport_refuses_redirect_before_following_a_different_endpoint():
    paths = []

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            paths.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/unexpected")
            self.end_headers()

        def do_GET(self):
            paths.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(DeviceAgentPreflightError) as error:
            search_address(
                f"http://127.0.0.1:{server.server_port}", AddressSearchRequest.model_validate(command())
            )
        assert error.value.code == "search_rejected"
        assert paths == ["/api/v1/commissioning/address-search"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
