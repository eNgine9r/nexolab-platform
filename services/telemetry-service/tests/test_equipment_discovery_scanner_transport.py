from __future__ import annotations

import asyncio
import errno

import app.equipment_discovery.scanner as scanner_module
from app.equipment_discovery.scanner import tcp_connect


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
