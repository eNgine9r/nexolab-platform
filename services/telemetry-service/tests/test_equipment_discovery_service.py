from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.config import Settings
from app.equipment_discovery.policy import DiscoveryPolicy
from app.equipment_discovery.repository import ScanAlreadyRunningError
from app.equipment_discovery.service import EquipmentDiscoveryService


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


class StubRepository:
    def __init__(self, *, running: bool = False) -> None:
        self.running = running
        self.calls: list[dict[str, object]] = []

    def start_scan(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.running:
            raise ScanAlreadyRunningError("already running")
        return SimpleNamespace(id="scheduled-scan-1")


def configured_policy() -> DiscoveryPolicy:
    return DiscoveryPolicy.from_settings(
        Settings(
            equipment_discovery_allowed_cidrs="192.168.50.0/30",
            equipment_discovery_allowed_ports="80,443",
            equipment_discovery_max_hosts=4,
            equipment_discovery_max_ports=2,
        )
    )


def test_scheduler_is_disabled_by_default() -> None:
    async def run() -> None:
        service = EquipmentDiscoveryService(
            StubRepository(),  # type: ignore[arg-type]
            configured_policy(),
            schedule_interval_seconds=0,
            scheduled_organization_id=ORGANIZATION_ID,
        )
        assert service.start_scheduler() is False
        await service.shutdown()

    asyncio.run(run())


def test_scheduled_scan_uses_only_configured_scope_and_system_audit_actor() -> None:
    async def run() -> None:
        repository = StubRepository()
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            configured_policy(),
            schedule_interval_seconds=300,
            scheduled_organization_id=ORGANIZATION_ID,
        )
        launched: list[tuple[str, str, tuple[str, ...], tuple[int, ...]]] = []
        service.launch = (  # type: ignore[method-assign]
            lambda scan_id, *, organization_id, scope: launched.append(
                (scan_id, organization_id, scope.cidrs, scope.ports)
            )
        )

        assert await service._run_scheduled_once() is True  # noqa: SLF001
        assert launched == [
            ("scheduled-scan-1", ORGANIZATION_ID, ("192.168.50.0/30",), (80, 443))
        ]
        call = repository.calls[0]
        assert call["trigger"] == "scheduled"
        assert call["actor_subject"] == "system:equipment-discovery-scheduler"
        audit_event = call["audit_event"]
        assert getattr(audit_event, "action") == "equipment_discovery.scan_scheduled"

    asyncio.run(run())


def test_scheduled_scan_skips_when_one_is_already_running() -> None:
    async def run() -> None:
        repository = StubRepository(running=True)
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            configured_policy(),
            schedule_interval_seconds=300,
            scheduled_organization_id=ORGANIZATION_ID,
        )
        launched: list[str] = []
        service.launch = (  # type: ignore[method-assign]
            lambda scan_id, *, organization_id, scope: launched.append(scan_id)
        )

        assert await service._run_scheduled_once() is False  # noqa: SLF001
        assert launched == []
        assert repository.calls[0]["trigger"] == "scheduled"

    asyncio.run(run())
