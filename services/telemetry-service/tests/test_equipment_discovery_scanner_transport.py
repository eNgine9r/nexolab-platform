from __future__ import annotations

import asyncio
import errno
from ipaddress import ip_address, ip_network
from pathlib import Path

import pytest

import app.equipment_discovery.scanner as scanner_module
from app.equipment_discovery.policy import ResolvedDiscoveryScope
from app.equipment_discovery.scanner import (
    LocalLanDiscoveryScanner,
    NeighborSnapshotError,
    ScanFailedError,
    read_ipv4_neighbors,
    tcp_connect,
)


def test_tcp_connect_treats_connection_refused_as_closed_port(monkeypatch) -> None:
    async def refused(_ip: str, _port: int):
        raise ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")

    monkeypatch.setattr(scanner_module.asyncio, "open_connection", refused)

    assert asyncio.run(tcp_connect("192.168.50.2", 443, 0.1)) is False


def test_tcp_connect_treats_timeout_as_no_response(monkeypatch) -> None:
    async def timed_out(_ip: str, _port: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr(scanner_module.asyncio, "open_connection", timed_out)

    assert asyncio.run(tcp_connect("192.168.50.2", 443, 0.1)) is False


def test_tcp_connect_treats_host_unreachable_as_no_response(monkeypatch) -> None:
    async def host_unreachable(_ip: str, _port: int):
        raise OSError(errno.EHOSTUNREACH, "no route to host")

    monkeypatch.setattr(scanner_module.asyncio, "open_connection", host_unreachable)

    assert asyncio.run(tcp_connect("192.168.50.2", 443, 0.1)) is False


def test_tcp_connect_propagates_systemic_network_failure(monkeypatch) -> None:
    async def unreachable(_ip: str, _port: int):
        raise OSError(errno.ENETUNREACH, "network unreachable")

    monkeypatch.setattr(scanner_module.asyncio, "open_connection", unreachable)

    try:
        asyncio.run(tcp_connect("192.168.50.2", 443, 0.1))
    except OSError as error:
        assert error.errno == errno.ENETUNREACH
    else:
        raise AssertionError("systemic network failure must abort discovery instead of looking closed")


def test_tcp_connect_propagates_process_resource_failure(monkeypatch) -> None:
    async def exhausted(_ip: str, _port: int):
        raise OSError(errno.EMFILE, "too many open files")

    monkeypatch.setattr(scanner_module.asyncio, "open_connection", exhausted)

    try:
        asyncio.run(tcp_connect("192.168.50.2", 443, 0.1))
    except OSError as error:
        assert error.errno == errno.EMFILE
    else:
        raise AssertionError("process resource failure must abort discovery instead of looking closed")


def test_scanner_counts_failing_probe_in_partial_metrics() -> None:
    async def connector(ip: str, _port: int, _timeout: float) -> bool:
        if ip == "192.168.50.2":
            raise OSError(errno.ENETUNREACH, "network unreachable")
        return False

    scope = ResolvedDiscoveryScope(
        networks=(ip_network("192.168.50.0/30"),),
        ports=(443,),
        addresses=(ip_address("192.168.50.1"), ip_address("192.168.50.2")),
        probe_budget=2,
    )
    scanner = LocalLanDiscoveryScanner(
        connect_timeout_seconds=0.1,
        concurrency=1,
        tcp_connector=connector,
    )

    with pytest.raises(ScanFailedError) as captured:
        asyncio.run(scanner.scan(scope))

    assert isinstance(captured.value.cause, OSError)
    assert captured.value.result.hosts_considered == 2
    assert captured.value.result.probes_attempted == 2
    assert captured.value.result.network_connect_attempts == 2
    assert captured.value.result.network_payload_bytes == 0


def test_scanner_cancels_and_counts_started_siblings_when_batch_fails() -> None:
    async def run() -> None:
        all_started = asyncio.Event()
        blocker = asyncio.Event()
        started: list[tuple[str, int]] = []
        cancelled: list[tuple[str, int]] = []

        async def connector(ip: str, port: int, _timeout: float) -> bool:
            started.append((ip, port))
            if len(started) == 4:
                all_started.set()
            await all_started.wait()
            if ip == "192.168.50.1" and port == 80:
                raise OSError(errno.ENETUNREACH, "network unreachable")
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cancelled.append((ip, port))
                raise
            return False

        scope = ResolvedDiscoveryScope(
            networks=(ip_network("192.168.50.0/30"),),
            ports=(80, 443),
            addresses=(ip_address("192.168.50.1"), ip_address("192.168.50.2")),
            probe_budget=4,
        )
        scanner = LocalLanDiscoveryScanner(
            connect_timeout_seconds=0.1,
            concurrency=4,
            tcp_connector=connector,
        )

        with pytest.raises(ScanFailedError) as captured:
            await scanner.scan(scope)

        assert isinstance(captured.value.cause, OSError)
        assert captured.value.result.hosts_considered == 2
        assert captured.value.result.probes_attempted == 4
        assert captured.value.result.network_connect_attempts == 4
        assert captured.value.result.network_payload_bytes == 0
        assert sorted(started) == [
            ("192.168.50.1", 80),
            ("192.168.50.1", 443),
            ("192.168.50.2", 80),
            ("192.168.50.2", 443),
        ]
        assert sorted(cancelled) == [
            ("192.168.50.1", 443),
            ("192.168.50.2", 80),
            ("192.168.50.2", 443),
        ]

    asyncio.run(run())


def test_explicit_neighbor_snapshot_failure_aborts_before_probes(tmp_path: Path) -> None:
    connect_attempts = 0

    async def connector(_ip: str, _port: int, _timeout: float) -> bool:
        nonlocal connect_attempts
        connect_attempts += 1
        return False

    scope = ResolvedDiscoveryScope(
        networks=(ip_network("192.168.50.2/32"),),
        ports=(443,),
        addresses=(ip_address("192.168.50.2"),),
        probe_budget=1,
    )
    scanner = LocalLanDiscoveryScanner(
        connect_timeout_seconds=0.1,
        concurrency=1,
        tcp_connector=connector,
        neighbor_table_path=tmp_path / "missing-neighbors",
    )

    with pytest.raises(NeighborSnapshotError, match="unable to read neighbor snapshot"):
        asyncio.run(scanner.scan(scope))

    assert connect_attempts == 0


def test_malformed_neighbor_snapshot_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "neighbors"
    path.write_text("not a proc arp snapshot\n", encoding="utf-8")

    with pytest.raises(NeighborSnapshotError, match="invalid neighbor snapshot header"):
        read_ipv4_neighbors(path)


def test_invalid_completed_neighbor_row_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "neighbors"
    path.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.50.2     0x1         0x2         not-a-mac             *        eth0\n",
        encoding="utf-8",
    )

    with pytest.raises(NeighborSnapshotError, match="invalid neighbor snapshot MAC"):
        read_ipv4_neighbors(path)


def test_valid_empty_neighbor_snapshot_is_not_a_failure(tmp_path: Path) -> None:
    path = tmp_path / "neighbors"
    path.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n",
        encoding="utf-8",
    )

    assert read_ipv4_neighbors(path) == {}
