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
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

ALLOWED_QUALITIES = {
    "valid",
    "sensor_error",
    "communication_error",
    "unknown",
}
EXPECTED_TEMPERATURE_CHANNELS = {"106-03", "106-04"}
EXPECTED_METER_IDS = {"200", "201", "202", "203"}
EXPECTED_METER_SERIES = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the real edge-01 to NEXOLAB dashboard telemetry path."
    )
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--websocket-url", required=True)
    parser.add_argument("--node-id", default="edge-01")
    parser.add_argument("--expected-records", type=int, default=34)
    parser.add_argument("--max-age-seconds", type=int, default=90)
    parser.add_argument("--websocket-timeout-seconds", type=int, default=45)
    parser.add_argument("--evidence", type=Path, required=True)
    return parser.parse_args()


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise AssertionError(f"Timestamp is not timezone-aware: {value}")
    return parsed.astimezone(UTC)


def get_json(url: str, timeout: int = 10) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise AssertionError(f"GET {url} returned HTTP {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise AssertionError(f"GET {url} did not return a JSON object")
    return payload


def collection_url(base_url: str, endpoint: str, query: dict[str, str | int]) -> str:
    return f"{base_url.rstrip('/')}{endpoint}?{urlencode(query)}"


def meter_id(item: dict[str, Any]) -> str | None:
    equipment_id = str(item.get("equipment_id", ""))
    channel_id = str(item.get("channel_id", ""))
    for unit_id in EXPECTED_METER_IDS:
        if unit_id in equipment_id or channel_id.startswith(f"{unit_id}-"):
            return unit_id
    return None


def is_production_item(item: dict[str, Any]) -> bool:
    channel_id = str(item.get("channel_id", ""))
    return channel_id in EXPECTED_TEMPERATURE_CHANNELS or meter_id(item) is not None


def validate_sample(item: dict[str, Any]) -> None:
    required_strings = (
        "event_id",
        "node_id",
        "captured_at",
        "metric",
        "unit",
        "quality",
        "source",
        "equipment_id",
        "channel_id",
    )
    for key in required_strings:
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise AssertionError(f"Telemetry item has invalid {key}: {value!r}")

    parse_timestamp(item["captured_at"])
    quality = item["quality"]
    if quality not in ALLOWED_QUALITIES:
        raise AssertionError(f"Unsupported quality: {quality}")

    value = item.get("value")
    if quality == "valid" and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise AssertionError(
            f"Valid sample {item['event_id']} does not contain a numeric value"
        )
    if item.get("alarm") not in (None, "low", "high"):
        raise AssertionError(f"Unsupported alarm: {item.get('alarm')}")


def validate_latest(
    latest: dict[str, Any],
    *,
    node_id: str,
    expected_records: int,
    max_age_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = latest.get("items")
    if not isinstance(items, list):
        raise AssertionError("Latest response items is not an array")

    node_items: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise AssertionError("Latest response contains a non-object item")
        validate_sample(raw_item)
        if raw_item["node_id"] == node_id and is_production_item(raw_item):
            node_items.append(raw_item)

    series = {
        (
            item["equipment_id"],
            item["channel_id"],
            item["metric"],
        )
        for item in node_items
    }
    if len(series) < expected_records:
        raise AssertionError(
            f"Expected at least {expected_records} production series, got {len(series)}"
        )

    temperature_channels = {
        item["channel_id"]
        for item in node_items
        if item["channel_id"] in EXPECTED_TEMPERATURE_CHANNELS
    }
    if temperature_channels != EXPECTED_TEMPERATURE_CHANNELS:
        raise AssertionError(
            "Missing XJP60D channels: "
            f"{sorted(EXPECTED_TEMPERATURE_CHANNELS - temperature_channels)}"
        )

    meter_counts = Counter(
        unit_id
        for item in node_items
        if (unit_id := meter_id(item)) is not None
    )
    missing_meters = EXPECTED_METER_IDS - set(meter_counts)
    if missing_meters:
        raise AssertionError(f"Missing LE-01MP meters: {sorted(missing_meters)}")
    underfilled = {
        unit_id: count
        for unit_id, count in meter_counts.items()
        if count < EXPECTED_METER_SERIES
    }
    if underfilled:
        raise AssertionError(
            f"LE-01MP meters have fewer than {EXPECTED_METER_SERIES} series: "
            f"{underfilled}"
        )

    now = utc_now()
    ages = [
        max(0.0, (now - parse_timestamp(item["captured_at"])).total_seconds())
        for item in node_items
    ]
    oldest_age = max(ages, default=float("inf"))
    if oldest_age > max_age_seconds:
        raise AssertionError(
            f"Production latest data is stale: oldest age {oldest_age:.1f}s, "
            f"limit {max_age_seconds}s"
        )

    summary = {
        "response_count": latest.get("count"),
        "production_series_count": len(series),
        "temperature_channels": sorted(temperature_channels),
        "meter_series_counts": dict(sorted(meter_counts.items())),
        "quality_counts": dict(
            sorted(Counter(str(item["quality"]) for item in node_items).items())
        ),
        "alarm_counts": dict(
            sorted(
                Counter(str(item["alarm"] or "none") for item in node_items).items()
            )
        ),
        "oldest_sample_age_seconds": round(oldest_age, 3),
        "newest_captured_at": max(
            (item["captured_at"] for item in node_items), default=None
        ),
    }
    return node_items, summary


def websocket_uri(base_uri: str, *, node_id: str, after: str | None) -> str:
    parsed = urlparse(base_uri)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["node_id"] = node_id
    if after is not None:
        query["after"] = after
    return urlunparse(parsed._replace(query=urlencode(query)))


def recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("WebSocket connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_masked_frame(connection: socket.socket, opcode: int, payload: bytes) -> None:
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    connection.sendall(bytes(header) + masked)


def recv_frame(connection: socket.socket) -> tuple[int, bytes]:
    first, second = recv_exact(connection, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(connection, 8))[0]
    mask = recv_exact(connection, 4) if masked else b""
    payload = recv_exact(connection, length)
    if masked:
        payload = bytes(
            value ^ mask[index % 4] for index, value in enumerate(payload)
        )
    return opcode, payload


def open_websocket(uri: str, timeout_seconds: int) -> socket.socket:
    parsed = urlparse(uri)
    if parsed.scheme not in {"ws", "wss"}:
        raise ValueError("WebSocket URL must use ws:// or wss://")
    host = parsed.hostname
    if host is None:
        raise ValueError("WebSocket URL has no host")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    raw_socket = socket.create_connection((host, port), timeout=timeout_seconds)
    connection: socket.socket
    if parsed.scheme == "wss":
        connection = ssl.create_default_context().wrap_socket(
            raw_socket, server_hostname=host
        )
    else:
        connection = raw_socket
    connection.settimeout(timeout_seconds)

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    host_header = host if parsed.port is None else f"{host}:{port}"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    connection.sendall(request.encode("ascii"))

    response = bytearray()
    while b"\r\n\r\n" not in response:
        response.extend(connection.recv(4096))
        if len(response) > 65536:
            raise ConnectionError("WebSocket handshake response is too large")
    header_block = bytes(response).split(b"\r\n\r\n", 1)[0]
    lines = header_block.decode("latin-1").split("\r\n")
    if " 101 " not in lines[0]:
        raise ConnectionError(f"WebSocket handshake failed: {lines[0]}")
    headers = {
        key.strip().lower(): value.strip()
        for key, value in (
            line.split(":", 1) for line in lines[1:] if ":" in line
        )
    }
    expected_accept = base64.b64encode(
        hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()
    ).decode("ascii")
    if headers.get("sec-websocket-accept") != expected_accept:
        raise ConnectionError("Invalid Sec-WebSocket-Accept header")
    return connection


def wait_for_new_websocket_event(
    uri: str,
    *,
    known_event_ids: set[str],
    node_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    connection = open_websocket(uri, timeout_seconds)
    try:
        while time.monotonic() < deadline:
            connection.settimeout(max(1.0, deadline - time.monotonic()))
            opcode, payload = recv_frame(connection)
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed before a new event arrived")
            if opcode == 0x9:
                send_masked_frame(connection, 0xA, payload)
                continue
            if opcode != 0x1:
                continue
            message = json.loads(payload.decode("utf-8"))
            if not isinstance(message, dict):
                continue
            if message.get("type") == "heartbeat":
                continue
            if message.get("type") == "error":
                raise AssertionError(f"WebSocket error: {message.get('detail')}")
            validate_sample(message)
            if message["node_id"] != node_id:
                continue
            if message["event_id"] in known_event_ids:
                continue
            return message
    finally:
        connection.close()
    raise TimeoutError(
        f"No newly committed {node_id} event arrived within {timeout_seconds}s"
    )


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    api_base_url = args.api_base_url.rstrip("/")

    readiness = get_json(f"{api_base_url}/health/ready")
    if readiness.get("status") != "ready":
        raise AssertionError(f"Central backend is not ready: {readiness}")

    latest_url = collection_url(
        api_base_url,
        "/api/v1/telemetry/latest",
        {"node_id": args.node_id, "limit": 1000},
    )
    latest = get_json(latest_url)
    production_items, latest_summary = validate_latest(
        latest,
        node_id=args.node_id,
        expected_records=args.expected_records,
        max_age_seconds=args.max_age_seconds,
    )

    history_to = utc_now() + timedelta(seconds=5)
    history_from = history_to - timedelta(minutes=5)
    history_url = collection_url(
        api_base_url,
        "/api/v1/telemetry/history",
        {
            "node_id": args.node_id,
            "from": history_from.isoformat(),
            "to": history_to.isoformat(),
            "limit": 1000,
        },
    )
    history = get_json(history_url)
    if not isinstance(history.get("items"), list) or history.get("count", 0) <= 0:
        raise AssertionError("History API returned no recent edge-01 records")

    known_event_ids = {str(item["event_id"]) for item in production_items}
    websocket_url = websocket_uri(
        args.websocket_url,
        node_id=args.node_id,
        after=latest_summary["newest_captured_at"],
    )
    live_event = wait_for_new_websocket_event(
        websocket_url,
        known_event_ids=known_event_ids,
        node_id=args.node_id,
        timeout_seconds=args.websocket_timeout_seconds,
    )

    evidence = {
        "validation": "m3-edge-to-dashboard-cutover",
        "status": "passed",
        "started_at": started_at.isoformat(),
        "completed_at": utc_now().isoformat(),
        "node_id": args.node_id,
        "api_base_url": api_base_url,
        "websocket_url": args.websocket_url,
        "readiness": readiness,
        "latest": latest_summary,
        "history_recent_count": history.get("count"),
        "websocket_new_event": {
            "event_id": live_event["event_id"],
            "captured_at": live_event["captured_at"],
            "equipment_id": live_event["equipment_id"],
            "channel_id": live_event["channel_id"],
            "metric": live_event["metric"],
            "unit": live_event["unit"],
            "quality": live_event["quality"],
            "alarm": live_event.get("alarm"),
        },
    }

    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.evidence.with_suffix(args.evidence.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.evidence)
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"M3 cutover validation failed: {exc}", file=sys.stderr)
        raise
