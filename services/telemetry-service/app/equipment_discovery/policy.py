from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, ip_network

from app.config import Settings


class DiscoveryPolicyError(ValueError):
    code = "equipment_discovery_policy_error"


class DiscoveryDisabledError(DiscoveryPolicyError):
    code = "equipment_discovery_disabled"


class DiscoveryScopeDeniedError(DiscoveryPolicyError):
    code = "equipment_discovery_scope_denied"


class DiscoveryBudgetExceededError(DiscoveryPolicyError):
    code = "equipment_discovery_budget_exceeded"


@dataclass(frozen=True, slots=True)
class ResolvedDiscoveryScope:
    networks: tuple[IPv4Network, ...]
    ports: tuple[int, ...]
    addresses: tuple[IPv4Address, ...]
    probe_budget: int

    @property
    def cidrs(self) -> tuple[str, ...]:
        return tuple(str(network) for network in self.networks)


@dataclass(frozen=True, slots=True)
class DiscoveryPolicy:
    allowed_networks: tuple[IPv4Network, ...]
    allowed_ports: tuple[int, ...]
    max_hosts: int
    max_ports: int
    connect_timeout_seconds: float
    concurrency: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "DiscoveryPolicy":
        return cls(
            allowed_networks=parse_private_cidrs(settings.equipment_discovery_allowed_cidrs),
            allowed_ports=parse_ports(settings.equipment_discovery_allowed_ports),
            max_hosts=settings.equipment_discovery_max_hosts,
            max_ports=settings.equipment_discovery_max_ports,
            connect_timeout_seconds=settings.equipment_discovery_connect_timeout_seconds,
            concurrency=settings.equipment_discovery_concurrency,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.allowed_networks and self.allowed_ports)

    def resolve(
        self,
        *,
        requested_cidrs: list[str] | None = None,
        requested_ports: list[int] | None = None,
    ) -> ResolvedDiscoveryScope:
        if not self.enabled:
            raise DiscoveryDisabledError(
                "LOCAL_LAN discovery is disabled until private CIDR and port allowlists are configured"
            )

        networks = (
            parse_private_cidrs(",".join(requested_cidrs))
            if requested_cidrs
            else self.allowed_networks
        )
        ports = tuple(sorted(set(requested_ports or self.allowed_ports)))
        if not networks or not ports:
            raise DiscoveryScopeDeniedError("at least one CIDR and one TCP port are required")

        for network in networks:
            if not any(network.subnet_of(allowed) for allowed in self.allowed_networks):
                raise DiscoveryScopeDeniedError(
                    f"CIDR {network} is outside the configured LOCAL_LAN allowlist"
                )
        denied_ports = [port for port in ports if port not in self.allowed_ports]
        if denied_ports:
            raise DiscoveryScopeDeniedError(
                "TCP ports are outside the configured allowlist: "
                + ", ".join(str(port) for port in denied_ports)
            )
        if len(ports) > self.max_ports:
            raise DiscoveryBudgetExceededError(
                f"requested {len(ports)} ports exceeds max {self.max_ports}"
            )

        addresses = _bounded_deduplicated_hosts(networks, max_hosts=self.max_hosts)
        probe_budget = len(addresses) * len(ports)
        if probe_budget <= 0:
            raise DiscoveryScopeDeniedError("discovery scope contains no host probes")
        return ResolvedDiscoveryScope(
            networks=networks,
            ports=ports,
            addresses=addresses,
            probe_budget=probe_budget,
        )


def parse_private_cidrs(value: str) -> tuple[IPv4Network, ...]:
    networks: list[IPv4Network] = []
    seen: set[str] = set()
    for token in value.split(","):
        raw = token.strip()
        if not raw:
            continue
        try:
            parsed = ip_network(raw, strict=False)
        except ValueError as error:
            raise DiscoveryScopeDeniedError(f"invalid discovery CIDR: {raw}") from error
        if not isinstance(parsed, IPv4Network):
            raise DiscoveryScopeDeniedError("only IPv4 RFC1918 discovery scopes are supported")
        if not _is_rfc1918_network(parsed):
            raise DiscoveryScopeDeniedError(
                f"discovery CIDR must be fully inside RFC1918 space: {parsed}"
            )
        rendered = str(parsed)
        if rendered not in seen:
            seen.add(rendered)
            networks.append(parsed)
    return tuple(sorted(networks, key=lambda item: (int(item.network_address), item.prefixlen)))


def parse_ports(value: str) -> tuple[int, ...]:
    ports: set[int] = set()
    for token in value.split(","):
        raw = token.strip()
        if not raw:
            continue
        try:
            port = int(raw)
        except ValueError as error:
            raise DiscoveryScopeDeniedError(f"invalid discovery TCP port: {raw}") from error
        if port < 1 or port > 65535:
            raise DiscoveryScopeDeniedError(f"invalid discovery TCP port: {port}")
        ports.add(port)
    return tuple(sorted(ports))


def _bounded_deduplicated_hosts(
    networks: tuple[IPv4Network, ...], *, max_hosts: int
) -> tuple[IPv4Address, ...]:
    hosts: set[IPv4Address] = set()
    for network in networks:
        for address in network.hosts():
            hosts.add(address)
            if len(hosts) > max_hosts:
                raise DiscoveryBudgetExceededError(
                    f"requested discovery scope exceeds max {max_hosts} hosts"
                )
    return tuple(sorted(hosts, key=int))


def _is_rfc1918_network(network: IPv4Network) -> bool:
    ranges = (
        IPv4Network("10.0.0.0/8"),
        IPv4Network("172.16.0.0/12"),
        IPv4Network("192.168.0.0/16"),
    )
    return any(network.subnet_of(private) for private in ranges)
