#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

EXPECTED_XJP_CHANNELS = {"106-03", "106-04"}
EXPECTED_LE_UNITS = {"200", "201", "202", "203"}
EXPECTED_SOURCES = {"dixell-xjp60d", "f-and-f-le-01mp"}
MAX_FUTURE_SKEW_SECONDS = 30


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotEvidence:
    event_ids: set[str]
    latest_captured_at: str
    series_count: int
    sources: set[str]
    xjp_channels: set[str]
    le_units: set[str]


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{field} must be a non-empty timestamp")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise VerificationError(f"{field} is not ISO-8601: {value}") from exc
    if parsed.tzinfo is None:
        raise VerificationError(f"{field} must include a timezone: {value}")
    return parsed.astimezone(UTC)


def json_get(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except Exception as exc:
        raise VerificationError(f"GET failed for {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise VerificationError(f"Expected JSON object from {url}")
    return payload


def collection_items(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise VerificationError(f"{name}.items must be an array")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise VerificationError(f"{name}.items[{index}] must be an object")
        records.append(item)
    return records


def equipment_unit(record: dict[str, Any]) -> str | None:
    equipment = str(record.get("equipment_id", ""))
    channel = str(record.get("channel_id", ""))
    for unit in EXPECTED_LE_UNITS:
        if unit in equipment or channel == unit:
            return unit
    return None


def validate_snapshot(
    records: Iterable[dict[str, Any]],
    *,
    expected_node: str,
    expected_records: int,
    now: datetime | None = None,
) -> SnapshotEvidence:
    now = now or utc_now()
    rows = list(records)
    if len(rows) != expected_records:
        raise VerificationError(
            f"Expected {expected_records} latest records, received {len(rows)}"
        )

    event_ids: set[str] = set()
    series: set[tuple[str, str, str, str]] = set()
    sources: set[str] = set()
    xjp_channels: set[str] = set()
    le_units: set[str] = set()
    timestamps: list[datetime] = []

    for index, record in enumerate(rows):
        prefix = f"latest[{index}]"
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise VerificationError(f"{prefix}.event_id is missing")
        if event_id in event_ids:
            raise VerificationError(f"Duplicate event_id in latest snapshot: {event_id}")
        event_ids.add(event_id)

        node_id = record.get("node_id")
        if node_id != expected_node:
            raise VerificationError(
                f"{prefix}.node_id expected {expected_node}, received {node_id}"
            )

        source = record.get("source")
        if not isinstance(source, str) or not source:
            raise VerificationError(f"{prefix}.source is missing")
        if source == "simulator" or "simulator" in source.lower():
            raise VerificationError(f"Simulator payload reached production: {event_id}")
        sources.add(source)

        equipment_id = record.get("equipment_id")
        channel_id = record.get("channel_id")
        metric = record.get("metric")
        if not all(isinstance(value, str) and value for value in (equipment_id, channel_id, metric)):
            raise VerificationError(f"{prefix} has an incomplete series identity")
        series.add((str(node_id), str(equipment_id), str(channel_id), str(metric)))

        captured_at = parse_timestamp(record.get("captured_at"), f"{prefix}.captured_at")
        if captured_at > now + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
            raise VerificationError(
                f"Future timestamp exceeds {MAX_FUTURE_SKEW_SECONDS}s skew: {captured_at.isoformat()}"
            )
        timestamps.append(captured_at)

        if source == "dixell-xjp60d":
            xjp_channels.add(str(channel_id))
        if source == "f-and-f-le-01mp":
            unit = equipment_unit(record)
            if unit is None:
                raise VerificationError(
                    f"Cannot resolve LE-01MP unit from {equipment_id}/{channel_id}"
                )
            le_units.add(unit)

    if len(series) != expected_records:
        raise VerificationError(
            f"Expected {expected_records} unique series, received {len(series)}"
        )
    if not EXPECTED_SOURCES.issubset(sources):
        raise VerificationError(
            f"Missing production sources: {sorted(EXPECTED_SOURCES - sources)}"
        )
    if xjp_channels != EXPECTED_XJP_CHANNELS:
        raise VerificationError(
            f"XJP60D channels mismatch: expected {sorted(EXPECTED_XJP_CHANNELS)}, "
            f"received {sorted(xjp_channels)}"
        )
    if le_units != EXPECTED_LE_UNITS:
        raise VerificationError(
            f"LE-01MP units mismatch: expected {sorted(EXPECTED_LE_UNITS)}, "
            f"received {sorted(le_units)}"
        )

    latest = max(timestamps).isoformat().replace("+00:00", "Z")
    return SnapshotEvidence(
        event_ids=event_ids,
        latest_captured_at=latest,
        series_count=len(series),
        sources=sources,
        xjp_channels=xjp_channels,
        le_units=le_units,
    )


def validate_history(records: Iterable[dict[str, Any]], expected_node: str) -> int:
    seen: set[str] = set()
    count = 0
    for index, record in enumerate(records):
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise VerificationError(f"history[{index}].event_id is missing")
        if event_id in seen:
            raise VerificationError(f"Duplicate event_id in history: {event_id}")
        if record.get("node_id") != expected_node:
            raise VerificationError(f"history[{index}] belongs to another node")
        seen.add(event_id)
        count += 1
    return count


def websocket_url(base_url: str, expected_node: str, after: str) -> str:
    parts = urlsplit(base_url)
    query = urlencode({"node_id": expected_node, "after": after})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def read_exact(connection: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            raise VerificationError("WebSocket connection closed unexpectedly")
        chunks.extend(chunk)
    return bytes(chunks)


def masked_frame(opcode: int, payload: bytes) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, 0x80 | length))
    elif length < 65536:
        header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
    encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return header + mask + encoded


def read_websocket_json(connection: socket.socket) -> dict[str, Any]:
    while True:
        first, second = read_exact(connection, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        masked = bool(second & 0x80)
        if length == 126:
            length = struct.unpack("!H", read_exact(connection, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read_exact(connection, 8))[0]
        mask = read_exact(connection, 4) if masked else b""
        payload = read_exact(connection, length)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))

        if opcode == 0x8:
            raise VerificationError("WebSocket server closed before a telemetry event")
        if opcode == 0x9:
            connection.sendall(masked_frame(0xA, payload))
            continue
        if opcode != 0x1:
            continue
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationError("WebSocket returned invalid JSON") from exc
        if not isinstance(message, dict):
            raise VerificationError("WebSocket JSON message must be an object")
        return message


def wait_for_live_event(
    url: str,
    *,
    expected_node: str,
    snapshot_event_ids: set[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.scheme not in {"ws", "wss"} or not parts.hostname:
        raise VerificationError(f"Invalid WebSocket URL: {url}")
    port = parts.port or (443 if parts.scheme == "wss" else 80)
    raw = socket.create_connection((parts.hostname, port), timeout=timeout_seconds)
    connection: socket.socket
    if parts.scheme == "wss":
        connection = ssl.create_default_context().wrap_socket(raw, server_hostname=parts.hostname)
    else:
        connection = raw
    connection.settimeout(timeout_seconds)

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    connection.sendall(request.encode("ascii"))

    response = bytearray()
    while b"\r\n\r\n" not in response:
        response.extend(read_exact(connection, 1))
        if len(response) > 16384:
            raise VerificationError("WebSocket handshake headers are too large")
    header_text = response.decode("iso-8859-1")
    if not header_text.startswith("HTTP/1.1 101"):
        raise VerificationError(f"WebSocket handshake failed: {header_text.splitlines()[0]}")
    expected_accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    if f"sec-websocket-accept: {expected_accept}" not in header_text.lower():
        raise VerificationError("WebSocket accept header mismatch")

    try:
        while True:
            message = read_websocket_json(connection)
            if message.get("type") == "heartbeat":
                continue
            if message.get("type") == "error":
                raise VerificationError(f"WebSocket service error: {message.get('detail')}")
            event_id = message.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise VerificationError("WebSocket telemetry event_id is missing")
            if event_id in snapshot_event_ids:
                continue
            if message.get("node_id") != expected_node:
                continue
            if "simulator" in str(message.get("source", "")).lower():
                raise VerificationError("Simulator event received over production WebSocket")
            return message
    except socket.timeout as exc:
        raise VerificationError(
            f"No new WebSocket telemetry event within {timeout_seconds}s"
        ) from exc
    finally:
        try:
            connection.sendall(masked_frame(0x8, struct.pack("!H", 1000)))
        except OSError:
            pass
        connection.close()


def verify(args: argparse.Namespace) -> dict[str, Any]:
    api_base = args.api_base_url.rstrip("/")
    readiness = json_get(f"{api_base}/health/ready", args.timeout_seconds)
    if readiness.get("status") != "ready":
        raise VerificationError(f"Backend is not ready: {readiness}")

    latest_query = urlencode({"node_id": args.expected_node, "limit": 1000})
    latest_payload = json_get(
        f"{api_base}/api/v1/telemetry/latest?{latest_query}",
        args.timeout_seconds,
    )
    latest_records = collection_items(latest_payload, "latest")
    snapshot = validate_snapshot(
        latest_records,
        expected_node=args.expected_node,
        expected_records=args.expected_records,
    )

    live_url = websocket_url(
        args.websocket_url,
        args.expected_node,
        snapshot.latest_captured_at,
    )
    live_event = wait_for_live_event(
        live_url,
        expected_node=args.expected_node,
        snapshot_event_ids=snapshot.event_ids,
        timeout_seconds=args.timeout_seconds,
    )

    now = utc_now()
    history_query = urlencode(
        {
            "node_id": args.expected_node,
            "from": (now - timedelta(minutes=args.history_minutes)).isoformat(),
            "to": now.isoformat(),
            "limit": 1000,
        }
    )
    history_payload = json_get(
        f"{api_base}/api/v1/telemetry/history?{history_query}",
        args.timeout_seconds,
    )
    history_count = validate_history(
        collection_items(history_payload, "history"), args.expected_node
    )

    return {
        "status": "passed",
        "node_id": args.expected_node,
        "latest_unique_series": snapshot.series_count,
        "latest_event_ids": len(snapshot.event_ids),
        "sources": sorted(snapshot.sources),
        "xjp60d_channels": sorted(snapshot.xjp_channels),
        "le01mp_units": sorted(snapshot.le_units),
        "websocket_event_id": live_event["event_id"],
        "websocket_captured_at": live_event.get("captured_at"),
        "history_unique_events": history_count,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Verify the real edge-01 to NEXOLAB REST/WebSocket telemetry path."
    )
    result.add_argument("--api-base-url", default="http://127.0.0.1:8082")
    result.add_argument(
        "--websocket-url",
        default="ws://127.0.0.1:8082/api/v1/telemetry/live",
    )
    result.add_argument("--expected-node", default="edge-01")
    result.add_argument("--expected-records", type=int, default=34)
    result.add_argument("--timeout-seconds", type=float, default=45.0)
    result.add_argument("--history-minutes", type=int, default=10)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        evidence = verify(args)
    except VerificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
