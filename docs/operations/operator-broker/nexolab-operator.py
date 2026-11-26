#!/usr/bin/env python3
"""NEXOLAB Operator Broker client (#1758), run unprivileged by the development account.

  python3 docs/operations/operator-broker/nexolab-operator.py broker.list
  python3 docs/operations/operator-broker/nexolab-operator.py logs.unit unit=nexolab-lan-gateway.service lines=50
  python3 docs/operations/operator-broker/nexolab-operator.py service.recover unit=nexolab-lan-gateway.service
  python3 docs/operations/operator-broker/nexolab-operator.py <approved-op> k=v --approval <id-from-owner>

Arguments are key=value; integers are sent as integers. The broker validates everything;
this client only builds the request. Exit 0 on success, 2 when rejected, 3 when unreachable.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import uuid

SOCKET = "/run/nexolab-operator/broker.sock"


def call(op: str, args: dict, *, approval_id: str | None = None, path: str = SOCKET, timeout: float = 3600) -> dict:
    request = {"v": 1, "op": op, "args": args, "request_id": str(uuid.uuid4()), "ts": time.time()}
    if approval_id:
        request["approval_id"] = approval_id
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall(json.dumps(request).encode() + b"\n")
        sock.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data)


def parse_args(items: list[str]) -> dict:
    args: dict = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise SystemExit(f"argument must be key=value: {item!r}")
        args[key] = int(value) if re.fullmatch(r"-?\d{1,9}", value) and key != "boot" else value  # hashes stay strings
    return args


def render(response: dict) -> str:
    if not response.get("ok"):
        return f"REJECTED {response.get('error')} {response.get('detail', '')}".rstrip()
    result = response.get("result", {})
    if "steps" not in result:
        return json.dumps(result, indent=2, sort_keys=True)
    parts = []
    for item in result["steps"]:
        flags = " TIMEOUT" if item.get("timed_out") else ""
        flags += " TRUNCATED" if item.get("truncated") else ""
        parts.append(f"== {item['step']} (exit {item.get('exit')}){flags}\n{item.get('output', '').rstrip()}")
    extra = {k: v for k, v in result.items() if k != "steps"}
    if extra:
        parts.append(json.dumps(extra, indent=2, sort_keys=True))
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("op")
    parser.add_argument("args", nargs="*")
    parser.add_argument("--approval")
    parser.add_argument("--json", action="store_true", help="print the raw response including the audit receipt")
    parser.add_argument("--socket", default=SOCKET)
    ns = parser.parse_args()
    try:
        response = call(ns.op, parse_args(ns.args), approval_id=ns.approval, path=ns.socket)
    except (OSError, ValueError) as exc:
        print(f"UNREACHABLE {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(response, indent=2, sort_keys=True) if ns.json else render(response))
    receipt = response.get("receipt", {})
    print(f"-- receipt seq={receipt.get('seq')} hash={str(receipt.get('hash'))[:16]}", file=sys.stderr)
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
