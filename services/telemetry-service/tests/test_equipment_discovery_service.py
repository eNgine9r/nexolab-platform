from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from psycopg import OperationalError as PsycopgOperationalError
from sqlalchemy.exc import IntegrityError, OperationalError

import app.equipment_discovery.scanner as scanner_module
from app.config import Settings
from app.equipment_discovery.policy import DiscoveryPolicy
from app.equipment_discovery.repository import ScanAlreadyRunningError
from app.equipment_discovery.scanner import (
    DiscoveryScanResult,
    LocalLanDiscoveryScanner,
    ScanCancelledError,
    ScanFailedError,
)
from app.equipment_discovery.service import EquipmentDiscoveryService


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
EMPTY_ARP_SNAPSHOT = "IP address       HW type     Flags       HW address            Mask     Device\n"


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


class TransientConnectionError(RuntimeError):
    sqlstate = "08006"


class FinalizationRepository:
    def __init__(
        self,
        *,
        permanent_apply_failure: bool = False,
        initial_connection_failure: bool = False,
    ) -> None:
        self.apply_calls = 0
        self.completed = False
        self.failed = False
        self.cancelled_result: DiscoveryScanResult | None = None
        self.failed_result: DiscoveryScanResult | None = None
        self.permanent_apply_failure = permanent_apply_failure
        self.initial_connection_failure = initial_connection_failure

    def cancel_requested(self, _scan_id: str, *, organization_id: str) -> bool:
        assert organization_id == ORGANIZATION_ID
        return False

    def apply_scan_result(
        self,
        _scan_id: str,
        *,
        organization_id: str,
        result: DiscoveryScanResult,
    ) -> None:
        assert organization_id == ORGANIZATION_ID
        assert result.network_payload_bytes == 0
        self.apply_calls += 1
        if self.permanent_apply_failure:
            raise IntegrityError("UPDATE equipment_discovery_scans", {}, RuntimeError("constraint"))
        if self.initial_connection_failure and self.apply_calls == 1:
            raise OperationalError(
                "UPDATE equipment_discovery_scans",
                {},
                PsycopgOperationalError("connection failed: connection refused"),
            )
        if self.apply_calls == 1:
            raise OperationalError(
                "UPDATE equipment_discovery_scans",
                {},
                TransientConnectionError("offline"),
            )
        self.completed = True

    def finish_cancelled(
        self,
        _scan_id: str,
        *,
        organization_id: str,
        result: DiscoveryScanResult,
    ) -> None:
        assert organization_id == ORGANIZATION_ID
        self.cancelled_result = result

    def finish_failed(
        self,
        _scan_id: str,
        *,
        organization_id: str,
        error_code: str,
        error_message: str,
        result: DiscoveryScanResult | None = None,
    ) -> None:
        assert organization_id == ORGANIZATION_ID
        assert error_code == "equipment_discovery_scan_failed"
        assert error_message
        self.failed = True
        self.failed_result = result


class SuccessfulScanner:
    async def scan(self, _scope: object, *, cancel_check: object) -> DiscoveryScanResult:
        assert callable(cancel_check)
        return DiscoveryScanResult(
            observations=(),
            hosts_considered=2,
            probes_attempted=4,
            network_connect_attempts=4,
            network_payload_bytes=0,
        )


class CancelledScanner:
    async def scan(self, _scope: object, *, cancel_check: object) -> DiscoveryScanResult:
        assert callable(cancel_check)
        raise ScanCancelledError(
            DiscoveryScanResult(
                observations=(),
                hosts_considered=1,
                probes_attempted=2,
                duration_ms=7,
                process_cpu_ms=3,
                network_connect_attempts=2,
                network_payload_bytes=0,
            )
        )


class FailedScanner:
    async def scan(self, _scope: object, *, cancel_check: object) -> DiscoveryScanResult:
        assert callable(cancel_check)
        result = DiscoveryScanResult(
            observations=(),
            hosts_considered=1,
            probes_attempted=2,
            duration_ms=9,
            process_cpu_ms=4,
            network_connect_attempts=2,
            network_payload_bytes=0,
        )
        raise ScanFailedError(result, OSError("network unreachable"))


def test_scan_finalization_retries_after_transient_database_outage() -> None:
    async def run() -> None:
        repository = FinalizationRepository()
        policy = configured_policy()
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            policy,
            scanner=SuccessfulScanner(),  # type: ignore[arg-type]
            database_retry_seconds=0,
        )
        await service._run_scan(  # noqa: SLF001
            "scan-1",
            organization_id=ORGANIZATION_ID,
            scope=policy.resolve(),
        )
        assert repository.apply_calls == 2
        assert repository.completed is True

    asyncio.run(run())


def test_scan_finalization_retries_initial_psycopg_connection_failure() -> None:
    async def run() -> None:
        repository = FinalizationRepository(initial_connection_failure=True)
        policy = configured_policy()
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            policy,
            scanner=SuccessfulScanner(),  # type: ignore[arg-type]
            database_retry_seconds=0,
        )
        await service._run_scan(  # noqa: SLF001
            "scan-1",
            organization_id=ORGANIZATION_ID,
            scope=policy.resolve(),
        )
        assert repository.apply_calls == 2
        assert repository.completed is True
        assert repository.failed is False

    asyncio.run(run())


def test_permanent_database_failure_is_not_retried_and_scan_is_failed() -> None:
    async def run() -> None:
        repository = FinalizationRepository(permanent_apply_failure=True)
        policy = configured_policy()
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            policy,
            scanner=SuccessfulScanner(),  # type: ignore[arg-type]
            database_retry_seconds=0,
        )
        await service._run_scan(  # noqa: SLF001
            "scan-1",
            organization_id=ORGANIZATION_ID,
            scope=policy.resolve(),
        )
        assert repository.apply_calls == 1
        assert repository.failed is True
        assert repository.completed is False
        assert repository.failed_result is None

    asyncio.run(run())


def test_cancelled_scan_passes_partial_metrics_to_finalization() -> None:
    async def run() -> None:
        repository = FinalizationRepository()
        policy = configured_policy()
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            policy,
            scanner=CancelledScanner(),  # type: ignore[arg-type]
            database_retry_seconds=0,
        )
        await service._run_scan(  # noqa: SLF001
            "scan-1",
            organization_id=ORGANIZATION_ID,
            scope=policy.resolve(),
        )
        result = repository.cancelled_result
        assert result is not None
        assert result.hosts_considered == 1
        assert result.probes_attempted == 2
        assert result.network_connect_attempts == 2
        assert result.network_payload_bytes == 0
        assert result.duration_ms == 7
        assert result.process_cpu_ms == 3

    asyncio.run(run())


def test_failed_scan_passes_partial_metrics_to_finalization() -> None:
    async def run() -> None:
        repository = FinalizationRepository()
        policy = configured_policy()
        service = EquipmentDiscoveryService(
            repository,  # type: ignore[arg-type]
            policy,
            scanner=FailedScanner(),  # type: ignore[arg-type]
            database_retry_seconds=0,
        )
        await service._run_scan(  # noqa: SLF001
            "scan-1",
            organization_id=ORGANIZATION_ID,
            scope=policy.resolve(),
        )
        result = repository.failed_result
        assert repository.failed is True
        assert result is not None
        assert result.hosts_considered == 1
        assert result.probes_attempted == 2
        assert result.network_connect_attempts == 2
        assert result.network_payload_bytes == 0
        assert result.duration_ms == 9
        assert result.process_cpu_ms == 4

    asyncio.run(run())


def test_scanner_cancellation_carries_metrics_from_completed_probe_batch(tmp_path: Path) -> None:
    async def run() -> None:
        policy = configured_policy()
        scope = policy.resolve()
        checks = 0
        arp = tmp_path / "empty-arp"
        arp.write_text(EMPTY_ARP_SNAPSHOT, encoding="utf-8")

        async def cancel_check() -> bool:
            nonlocal checks
            checks += 1
            return checks > 1

        async def connector(_ip: str, _port: int, _timeout: float) -> bool:
            return False

        scanner = LocalLanDiscoveryScanner(
            connect_timeout_seconds=0.01,
            concurrency=1,
            tcp_connector=connector,
            neighbor_table_path=arp,
        )
        try:
            await scanner.scan(scope, cancel_check=cancel_check)
        except ScanCancelledError as error:
            result = error.result
        else:
            raise AssertionError("scan should have been cancelled after the first bounded probe batch")

        assert result.hosts_considered == 1
        assert result.probes_attempted == 1
        assert result.network_connect_attempts == 1
        assert result.network_payload_bytes == 0
        assert result.observations == ()

    asyncio.run(run())


def test_scanner_does_not_read_container_neighbor_table_by_default(monkeypatch) -> None:
    async def run() -> None:
        async def connector(_ip: str, _port: int, _timeout: float) -> bool:
            return False

        def unexpected_neighbor_read(_path: Path) -> dict[str, object]:
            raise AssertionError("default production scanner must not read container /proc/net/arp")

        monkeypatch.setattr(scanner_module, "read_ipv4_neighbors", unexpected_neighbor_read)
        scanner = LocalLanDiscoveryScanner(
            connect_timeout_seconds=0.01,
            concurrency=1,
            tcp_connector=connector,
        )
        result = await scanner.scan(configured_policy().resolve())
        assert result.observations == ()
        assert result.network_payload_bytes == 0

    asyncio.run(run())
