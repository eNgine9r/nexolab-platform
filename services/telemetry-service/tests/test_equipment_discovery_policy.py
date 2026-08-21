from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.equipment_discovery.policy import (
    DiscoveryBudgetExceededError,
    DiscoveryDisabledError,
    DiscoveryPolicy,
    DiscoveryScopeDeniedError,
)
from app.equipment_discovery.scanner import LocalLanDiscoveryScanner, ScanCancelledError


def policy(**overrides: object) -> DiscoveryPolicy:
    values: dict[str, object] = {
        "equipment_discovery_allowed_cidrs": "192.168.50.0/29,10.20.0.0/30",
        "equipment_discovery_allowed_ports": "80,443,502",
        "equipment_discovery_max_hosts": 16,
        "equipment_discovery_max_ports": 3,
        "equipment_discovery_connect_timeout_seconds": 0.1,
        "equipment_discovery_concurrency": 4,
    }
    values.update(overrides)
    settings = Settings(**values)
    return DiscoveryPolicy.from_settings(settings)


def test_discovery_policy_is_fail_closed_and_private_only() -> None:
    disabled = DiscoveryPolicy.from_settings(Settings())
    assert not disabled.enabled
    with pytest.raises(DiscoveryDisabledError):
        disabled.resolve()

    resolved = policy().resolve(requested_cidrs=["192.168.50.0/30"], requested_ports=[80, 502])
    assert resolved.cidrs == ("192.168.50.0/30",)
    assert [str(item) for item in resolved.addresses] == ["192.168.50.1", "192.168.50.2"]
    assert resolved.ports == (80, 502)
    assert resolved.probe_budget == 4

    with pytest.raises(DiscoveryScopeDeniedError):
        policy().resolve(requested_cidrs=["8.8.8.0/30"], requested_ports=[80])
    with pytest.raises(DiscoveryScopeDeniedError):
        policy().resolve(requested_cidrs=["192.168.50.0/30"], requested_ports=[22])


def test_discovery_policy_enforces_host_and_port_budgets() -> None:
    with pytest.raises(DiscoveryBudgetExceededError):
        policy(equipment_discovery_max_hosts=2).resolve(
            requested_cidrs=["192.168.50.0/29"], requested_ports=[80]
        )
    with pytest.raises(DiscoveryBudgetExceededError):
        policy(
            equipment_discovery_allowed_cidrs="10.0.0.0/8",
            equipment_discovery_max_hosts=16,
        ).resolve(requested_cidrs=["10.0.0.0/8"], requested_ports=[80])
    with pytest.raises(DiscoveryBudgetExceededError):
        policy(equipment_discovery_max_ports=1).resolve(
            requested_cidrs=["10.20.0.0/30"], requested_ports=[80, 443]
        )


def test_scanner_uses_only_connect_probes_and_neighbor_evidence(tmp_path: Path) -> None:
    async def run() -> None:
        arp = tmp_path / "arp"
        arp.write_text(
            "IP address       HW type     Flags       HW address            Mask     Device\n"
            "192.168.50.1     0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0\n",
            encoding="utf-8",
        )
        attempts: list[tuple[str, int, float]] = []

        async def connector(ip: str, port: int, timeout: float) -> bool:
            attempts.append((ip, port, timeout))
            return ip == "192.168.50.2" and port == 443

        scanner = LocalLanDiscoveryScanner(
            connect_timeout_seconds=0.1,
            concurrency=2,
            tcp_connector=connector,
            neighbor_table_path=arp,
        )
        scope = policy().resolve(requested_cidrs=["192.168.50.0/30"], requested_ports=[80, 443])
        result = await scanner.scan(scope)

        assert attempts == [
            ("192.168.50.1", 80, 0.1),
            ("192.168.50.1", 443, 0.1),
            ("192.168.50.2", 80, 0.1),
            ("192.168.50.2", 443, 0.1),
        ]
        assert result.hosts_considered == 2
        assert result.probes_attempted == 4
        assert result.responsive_hosts == 2
        assert result.duration_ms >= 0
        assert result.process_cpu_ms >= 0
        assert result.network_connect_attempts == 4
        assert result.network_payload_bytes == 0
        neighbor, connected = result.observations
        assert neighbor.candidate_key == "ip:192.168.50.1"
        assert neighbor.services == ()
        assert neighbor.evidence["neighbor_table"] is True
        assert connected.candidate_key == "ip:192.168.50.2"
        assert [item["port"] for item in connected.services] == [443]
        assert connected.evidence["tcp_connect_only"] is True
        assert connected.evidence["payload_bytes_sent"] == 0

    asyncio.run(run())


def test_scanner_honors_cancellation_between_bounded_batches() -> None:
    async def run() -> None:
        checks = 0

        async def connector(ip: str, port: int, timeout: float) -> bool:
            return False

        async def cancel() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 2

        scanner = LocalLanDiscoveryScanner(
            connect_timeout_seconds=0.1,
            concurrency=1,
            tcp_connector=connector,
            neighbor_table_path=Path("/definitely/missing"),
        )
        scope = policy().resolve(requested_cidrs=["192.168.50.0/29"], requested_ports=[80])
        with pytest.raises(ScanCancelledError):
            await scanner.scan(scope, cancel_check=cancel)

    asyncio.run(run())


def test_scheduled_discovery_interval_is_disabled_by_default_and_low_frequency_only() -> None:
    assert Settings().equipment_discovery_schedule_interval_seconds == 0
    with pytest.raises(ValueError, match="must be 0 or at least 300"):
        Settings(equipment_discovery_schedule_interval_seconds=60)
    assert Settings(equipment_discovery_schedule_interval_seconds=300).equipment_discovery_schedule_interval_seconds == 300
