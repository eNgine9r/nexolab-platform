from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network, ip_address
from pathlib import Path
from typing import Awaitable, Callable

from app.equipment_discovery.policy import ResolvedDiscoveryScope


_SERVICE_LABELS = {
    22: "ssh",
    80: "http",
    443: "https",
    502: "modbus-tcp-port",
    1883: "mqtt",
    8080: "http-alt",
    8081: "http-alt",
    8082: "nexolab-api-port",
}
_MAC_ADDRESS_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_ARP_HEADER_FIELDS = ("IP address", "HW type", "Flags", "HW address", "Mask", "Device")


@dataclass(frozen=True, slots=True)
class NeighborEvidence:
    ip_address: str
    mac_address: str
    interface: str


@dataclass(frozen=True, slots=True)
class DiscoveryObservationInput:
    ip_address: str
    mac_address: str | None
    hostname: str | None
    source_interface: str | None
    source_subnet: str
    services: tuple[dict[str, object], ...]
    evidence: dict[str, object]
    observed_at: datetime
    fingerprint_sha256: str

    @property
    def candidate_key(self) -> str:
        # Endpoint identity stays IP-stable. MAC is observed evidence only:
        # proxy ARP or multi-address devices can legitimately expose one MAC
        # for multiple scanned IPs and must not collapse distinct candidates.
        return f"ip:{self.ip_address}"


@dataclass(frozen=True, slots=True)
class DiscoveryScanResult:
    observations: tuple[DiscoveryObservationInput, ...]
    hosts_considered: int
    probes_attempted: int
    duration_ms: int = 0
    process_cpu_ms: int = 0
    network_connect_attempts: int = 0
    network_payload_bytes: int = 0

    @property
    def responsive_hosts(self) -> int:
        return len(self.observations)


class ScanCancelledError(RuntimeError):
    def __init__(self, result: DiscoveryScanResult) -> None:
        super().__init__("equipment discovery scan was cancelled")
        self.result = result


class NeighborSnapshotError(RuntimeError):
    """Raised when an explicitly configured neighbor snapshot is unusable."""


TcpConnector = Callable[[str, int, float], Awaitable[bool]]
CancelCheck = Callable[[], Awaitable[bool]]


class LocalLanDiscoveryScanner:
    def __init__(
        self,
        *,
        connect_timeout_seconds: float,
        concurrency: int,
        tcp_connector: TcpConnector | None = None,
        neighbor_table_path: Path | None = None,
    ) -> None:
        self._connect_timeout_seconds = connect_timeout_seconds
        self._concurrency = concurrency
        self._tcp_connector = tcp_connector or tcp_connect
        # Production telemetry runs in a bridge-network namespace, so its
        # /proc/net/arp is not authoritative physical-LAN evidence. Neighbor
        # evidence is therefore opt-in only from an explicitly supplied,
        # trustworthy read-only snapshot source.
        self._neighbor_table_path = neighbor_table_path

    async def scan(
        self,
        scope: ResolvedDiscoveryScope,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> DiscoveryScanResult:
        cancel = cancel_check or _never_cancelled
        started = time.perf_counter()
        cpu_started = time.process_time()
        neighbors = (
            read_ipv4_neighbors(self._neighbor_table_path)
            if self._neighbor_table_path is not None
            else {}
        )
        semaphore = asyncio.Semaphore(self._concurrency)
        observations: list[DiscoveryObservationInput] = []
        probes_attempted = 0
        hosts_considered = 0
        batch_size = max(1, min(self._concurrency, 32))

        def snapshot() -> DiscoveryScanResult:
            return DiscoveryScanResult(
                observations=tuple(
                    sorted(observations, key=lambda item: int(ip_address(item.ip_address)))
                ),
                hosts_considered=hosts_considered,
                probes_attempted=probes_attempted,
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                process_cpu_ms=max(0, round((time.process_time() - cpu_started) * 1000)),
                network_connect_attempts=probes_attempted,
                network_payload_bytes=0,
            )

        for start in range(0, len(scope.addresses), batch_size):
            if await cancel():
                raise ScanCancelledError(snapshot())
            batch = scope.addresses[start : start + batch_size]
            results = await asyncio.gather(
                *(
                    self._probe_host(address, scope, neighbors, semaphore)
                    for address in batch
                )
            )
            hosts_considered += len(batch)
            for observation, attempts in results:
                probes_attempted += attempts
                if observation is not None:
                    observations.append(observation)

        result = snapshot()
        if await cancel():
            raise ScanCancelledError(result)
        return result

    async def _probe_host(
        self,
        address: IPv4Address,
        scope: ResolvedDiscoveryScope,
        neighbors: dict[str, NeighborEvidence],
        semaphore: asyncio.Semaphore,
    ) -> tuple[DiscoveryObservationInput | None, int]:
        rendered = str(address)
        neighbor = neighbors.get(rendered)

        async def probe(port: int) -> tuple[int, bool]:
            async with semaphore:
                return port, await self._tcp_connector(
                    rendered,
                    port,
                    self._connect_timeout_seconds,
                )

        port_results = await asyncio.gather(*(probe(port) for port in scope.ports))
        open_ports = tuple(port for port, opened in port_results if opened)
        if neighbor is None and not open_ports:
            return None, len(scope.ports)

        source_subnet = _source_subnet(address, scope.networks)
        services = tuple(
            {
                "port": port,
                "transport": "tcp",
                "service": _SERVICE_LABELS.get(port, "tcp"),
                "evidence": "connect_succeeded",
            }
            for port in open_ports
        )
        evidence: dict[str, object] = {
            "neighbor_table": neighbor is not None,
            "tcp_connect_only": True,
            "payload_bytes_sent": 0,
            "open_ports": list(open_ports),
        }
        fingerprint = fingerprint_sha256(
            ip_address=rendered,
            mac_address=neighbor.mac_address if neighbor else None,
            hostname=None,
            source_interface=neighbor.interface if neighbor else None,
            source_subnet=source_subnet,
            services=services,
        )
        return (
            DiscoveryObservationInput(
                ip_address=rendered,
                mac_address=neighbor.mac_address if neighbor else None,
                hostname=None,
                source_interface=neighbor.interface if neighbor else None,
                source_subnet=source_subnet,
                services=services,
                evidence=evidence,
                observed_at=datetime.now(UTC),
                fingerprint_sha256=fingerprint,
            ),
            len(scope.ports),
        )


async def tcp_connect(ip: str, port: int, timeout_seconds: float) -> bool:
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout_seconds,
        )
        return True
    except (TimeoutError, asyncio.TimeoutError, ConnectionRefusedError):
        return False
    finally:
        if writer is not None:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()


def read_ipv4_neighbors(path: Path) -> dict[str, NeighborEvidence]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise NeighborSnapshotError(f"unable to read neighbor snapshot: {path}") from error

    if not lines or not all(field in lines[0] for field in _ARP_HEADER_FIELDS):
        raise NeighborSnapshotError(f"invalid neighbor snapshot header: {path}")

    neighbors: dict[str, NeighborEvidence] = {}
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 6:
            raise NeighborSnapshotError(
                f"invalid neighbor snapshot row {line_number}: expected six fields"
            )
        ip_value, _, flags, mac_address, _, interface = fields[:6]
        try:
            parsed = ip_address(ip_value)
        except ValueError as error:
            raise NeighborSnapshotError(
                f"invalid neighbor snapshot address on row {line_number}: {ip_value}"
            ) from error
        if not isinstance(parsed, IPv4Address):
            raise NeighborSnapshotError(
                f"neighbor snapshot row {line_number} is not IPv4: {ip_value}"
            )
        try:
            flags_value = int(flags, 0)
        except ValueError as error:
            raise NeighborSnapshotError(
                f"invalid neighbor snapshot flags on row {line_number}: {flags}"
            ) from error
        if flags_value == 0:
            continue
        if not _MAC_ADDRESS_RE.fullmatch(mac_address):
            raise NeighborSnapshotError(
                f"invalid neighbor snapshot MAC on row {line_number}: {mac_address}"
            )
        normalized_mac = mac_address.lower()
        if normalized_mac == "00:00:00:00:00:00":
            continue
        neighbors[str(parsed)] = NeighborEvidence(
            ip_address=str(parsed),
            mac_address=normalized_mac,
            interface=interface,
        )
    return neighbors


def fingerprint_sha256(
    *,
    ip_address: str,
    mac_address: str | None,
    hostname: str | None,
    source_interface: str | None,
    source_subnet: str,
    services: tuple[dict[str, object], ...],
) -> str:
    payload = {
        "ip_address": ip_address,
        "mac_address": mac_address,
        "hostname": hostname,
        "source_interface": source_interface,
        "source_subnet": source_subnet,
        "services": list(services),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_subnet(address: IPv4Address, networks: tuple[IPv4Network, ...]) -> str:
    matches = [network for network in networks if address in network]
    if not matches:
        raise RuntimeError(f"address {address} escaped resolved discovery scope")
    return str(max(matches, key=lambda network: network.prefixlen))


async def _never_cancelled() -> bool:
    return False
