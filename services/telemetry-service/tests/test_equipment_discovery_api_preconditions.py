from __future__ import annotations

from ipaddress import ip_network
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.equipment_discovery.api import create_equipment_discovery_router
from app.equipment_discovery.policy import DiscoveryPolicy
from app.equipment_discovery.repository import EquipmentDiscoveryRepository
from app.equipment_discovery.service import EquipmentDiscoveryService


class _UnexpectedRepositoryCall:
    def act_on_candidate(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("repository must not be called without If-Match")


class _ServiceStub:
    schedule_interval_seconds = 0


def test_candidate_action_missing_if_match_returns_structured_428() -> None:
    app = FastAPI()
    app.include_router(
        create_equipment_discovery_router(
            cast(EquipmentDiscoveryRepository, _UnexpectedRepositoryCall()),
            cast(EquipmentDiscoveryService, _ServiceStub()),
            DiscoveryPolicy(
                allowed_networks=(ip_network("192.168.50.0/29"),),
                allowed_ports=(443,),
                max_hosts=16,
                max_ports=1,
                connect_timeout_seconds=0.2,
                concurrency=4,
            ),
        )
    )
    response = TestClient(app).patch(
        "/api/v1/equipment-discovery/candidates/candidate-1",
        json={"action": "review"},
    )

    assert response.status_code == 428
    assert response.json()["detail"] == {
        "code": "equipment_discovery_candidate_version_required",
        "message": "If-Match must contain the current discovery candidate ETag",
    }
