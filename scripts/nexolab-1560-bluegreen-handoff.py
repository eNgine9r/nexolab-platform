#!/usr/bin/env python3
"""Bounded blue/green HTTPS *frontend-only* handoff for NEXOLAB #1560.

The old frontend on 3100 remains running. This never changes Docker, DB, MQTT,
Modbus, site routes/IPAM or authentication and never writes hardware.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCE = "08f1c8a4ed9212c25697d338583845bed5218ee5"
OLD_SOURCE = "4be678f6aa2581ad7fc79bcc22c26cd520c94272"
STAGE = Path("/home/nexolab/commander-workspaces/nexolab-1560-ui-release-staging/external")
SOURCE_RUNTIME = STAGE / "candidate-runtime"
RELEASE = Path("/opt/nexolab-external/releases/1560-" + SOURCE)
SERVICE = Path("/etc/systemd/system/nexolab-external-ui-1560.service")
BASE_SERVICE = Path("/etc/systemd/system/nexolab-external-frontend.service")
NGINX = Path("/opt/nexolab-external/nginx.conf")
NGINX_BIN = "/opt/nexolab-external/bin/nginx"
NGINX_UNIT = "nexolab-external-nginx.service"
JOURNAL_DIR = Path("/root/nexolab-1560-bluegreen-handoff")
ORIGINAL = JOURNAL_DIR / "nginx-before.conf"
UPDATED = JOURNAL_DIR / "nginx-updated.conf"
NEW_PORT = 3104
OLD_PORT = 3100

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()

def run(*cmd: str, timeout: int = 35) -> None:
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Command {cmd[0]} failed: exit={result.returncode}")

def read_json(url: str) -> dict:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=3) as res:
        if res.status != 200:
            raise RuntimeError("Unexpected HTTP status")
        data = json.load(res)
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected JSON")
        return data

def assert_http(url: str, expected: int = 200) -> None:
    with urlopen(url, timeout=4) as res:
        if res.status != expected:
            raise RuntimeError(f"Bad health response: {url}")

def verify_manifest(root: Path) -> None:
    manifest = root / "frontend-artifact-sha256.txt"
    if not manifest.is_file() or manifest.is_symlink():
        raise RuntimeError("Missing trusted frontend artifact manifest")
    for line in manifest.read_text().splitlines():
        checksum, space, filename = line.partition("  ")
        if len(checksum) != 64 or not space or "/" in filename or "\\" in filename or filename in ("", ".", ".."):
            raise RuntimeError("Unsafe manifest entry")
        candidate = root / filename
        if not candidate.is_file() or candidate.is_symlink() or digest(candidate) != checksum:
            raise RuntimeError("Artifact SHA-256 check failed: " + filename)
    if (root / "frontend-source-sha.txt").read_text().strip() != SOURCE:
        raise RuntimeError("Wrong source revision")
    if (root / "frontend-platform.txt").read_text().strip() != "linux/arm64":
        raise RuntimeError("Wrong package architecture")
    if (root / "frontend-runtime-contract.txt").read_text() != (
        Path("/home/nexolab/commander-workspaces/nexolab-1520-artifacts-4be678f6/external/frontend-runtime-contract.txt").read_text()
    ):
        raise RuntimeError("External HTTPS profile differs from active release")

def verify_runtime(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Candidate runtime missing or a symlink")
    resolved_root = root.resolve()
    for entry in root.rglob("*"):
        if entry.is_symlink() and not entry.resolve(strict=False).is_relative_to(resolved_root):
            raise RuntimeError("Candidate contains an external symlink")
    if (root / ".next" / "BUILD_ID").read_text().strip() != (STAGE / "frontend-build-id.txt").read_text().strip():
        raise RuntimeError("Build identity mismatch")
    identity = json.loads((root / ".nexolab-runtime-identity.json").read_text())
    if identity.get("source_commit") != SOURCE or identity.get("build_id") != (STAGE / "frontend-build-id.txt").read_text().strip():
        raise RuntimeError("Runtime identity mismatch")
    result = subprocess.run(
        ["sha256sum", "--check", "--status", str(STAGE / "frontend-runtime-files-sha256.txt")],
        cwd=root, timeout=180, capture_output=True
    )
    if result.returncode:
        raise RuntimeError("Unpacked candidate file hashes differ")

def generate_nginx(original: str) -> str:
    """Append failover upstream; preserve every existing OAuth and API location."""
    old = f"proxy_pass http://127.0.0.1:{OLD_PORT};"
    if original.count(old) != 2:
        raise ValueError("Expected exactly two protected UI proxy targets")
    if original.count("auth_request /_nexolab_external_auth;") < 3:
        raise ValueError("Protected OAuth guard missing")
    if "upstream nexolab_1560_bluegreen" in original:
        raise ValueError("Already handed over")
    anchor = "http {\n"
    if original.count(anchor) != 1:
        raise ValueError("Unexpected nginx topology")
    upstream = (
        "    # NEXOLAB #1560: new frontend first; original frontend is automatic backup.\n"
        "    upstream nexolab_1560_bluegreen {\n"
        f"        server 127.0.0.1:{NEW_PORT} max_fails=1 fail_timeout=5s;\n"
        f"        server 127.0.0.1:{OLD_PORT} backup;\n"
        "    }\n\n"
    )
    updated = original.replace(anchor, anchor + upstream)
    return updated.replace(old, "proxy_pass http://nexolab_1560_bluegreen;")

def generate_service(original: str) -> str:
    if original.count("[Service]") != 1 or original.count("[Unit]") != 1:
        raise ValueError("Unexpected systemd template")
    if "LoadCredential=" in original or "[Install]" in original:
        raise ValueError("Service template needs explicit ownership review")
    for contract in ("User=nexolab", "Group=nexolab", "NoNewPrivileges=yes", "ProtectSystem=strict", "PrivateTmp=yes"):
        if original.count(contract) != 1:
            raise ValueError("Required systemd isolation missing: " + contract)
    replacements = {
        "WorkingDirectory": str(RELEASE),
        "ExecStart": (
            "/home/nexolab/.nvm/versions/node/v22.23.1/bin/node "
            f"{RELEASE}/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port {NEW_PORT}"
        ),
        "ReadWritePaths": str(RELEASE / ".next/cache"),
        "Description": "NEXOLAB verified #1560 blue-green HTTPS frontend",
    }
    result = original
    for key, value in replacements.items():
        pattern = rf"(?m)^{re.escape(key)}=.*$"
        result, n = re.subn(pattern, lambda _: f"{key}={value}", result)
        if n != 1:
            raise ValueError("Unexpected service key count: " + key)
    if result.count("Wants=network-online.target") != 1:
        raise ValueError("Unexpected service ordering")
    result = result.replace("Wants=network-online.target", "Wants=network-online.target\nBefore=nexolab-external-nginx.service")
    result += f"\nEnvironment=NEXOLAB_RUNTIME_IDENTITY_FILE={RELEASE}/.nexolab-runtime-identity.json\n"
    result += "\n[Install]\nWantedBy=multi-user.target\n"
    return result

def snapshot() -> dict:
    verify_manifest(STAGE)
    verify_runtime(SOURCE_RUNTIME)
    original = NGINX.read_text()
    generate_nginx(original)
    generate_service(BASE_SERVICE.read_text())
    if not SERVICE.exists():
        current = read_json(f"http://127.0.0.1:{OLD_PORT}/api/runtime-identity")
        if current.get("source_commit") != OLD_SOURCE:
            raise RuntimeError("Active frontend identity is no longer approved baseline")
    for addr in ("http://127.0.0.1:3100/login", "http://172.18.48.66:8082/health/ready",
                 "http://127.0.0.1:8081/health"):
        assert_http(addr)
    return {
        "target_source": SOURCE,
        "target_build": (STAGE / "frontend-build-id.txt").read_text().strip(),
        "nginx_sha256": digest(NGINX),
        "frontend_mode": "HTTPS-only; old frontend remains available",
        "backend_write": False,
        "docker_changes": False,
        "modbus_write": False,
        "dr_coverage": "NOT_PROVEN_FULL_SITE",
    }

def atomic_bytes(path: Path, data: bytes, mode: int) -> None:
    temp = path.with_name(path.name + ".tmp-1560")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)

def validate_nginx() -> None:
    run("runuser", "-u", "nexolab-external-nginx", "--", NGINX_BIN,
        "-t", "-c", str(NGINX))

def reload_nginx() -> None:
    run("systemctl", "kill", "--kill-who=main", "--signal=HUP", NGINX_UNIT)

def recover() -> None:
    if not ORIGINAL.is_file() or not UPDATED.is_file():
        raise RuntimeError("Verified root rollback evidence not present")
    current = NGINX.read_bytes()
    if current not in (ORIGINAL.read_bytes(), UPDATED.read_bytes()):
        raise RuntimeError("Nginx was independently modified: stop, preserve all evidence")
    if current != ORIGINAL.read_bytes():
        atomic_bytes(NGINX, ORIGINAL.read_bytes(), 0o644)
        validate_nginx()
        reload_nginx()
    assert_http(f"http://127.0.0.1:{OLD_PORT}/login")
    print("EXTERNAL_NGINX_ROLLBACK_VERIFIED", flush=True)

def install() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Root required for actual site handoff")
    if RELEASE.exists() or SERVICE.exists() or JOURNAL_DIR.exists():
        raise RuntimeError("Existing release, unit or operation: do not overwrite")
    report = snapshot()
    JOURNAL_DIR.mkdir(mode=0o700)
    atomic_bytes(ORIGINAL, NGINX.read_bytes(), 0o600)
    atomic_bytes(UPDATED, generate_nginx(NGINX.read_text()).encode(), 0o600)
    atomic_bytes(JOURNAL_DIR / "preflight.json", json.dumps(report, indent=2).encode(), 0o600)
    try:
        shutil.copytree(SOURCE_RUNTIME, RELEASE, symlinks=True)
        (RELEASE / ".next/cache").mkdir(parents=True, exist_ok=True)
        run("chown", "-R", "nexolab:nexolab", str(RELEASE), timeout=180)
        verify_runtime(RELEASE)
        atomic_bytes(SERVICE, generate_service(BASE_SERVICE.read_text()).encode(), 0o644)
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", SERVICE.name, timeout=90)
        for _ in range(22):
            try:
                identity = read_json(f"http://127.0.0.1:{NEW_PORT}/api/runtime-identity")
                if identity.get("source_commit") == SOURCE and identity.get("build_id") == report["target_build"]:
                    assert_http(f"http://127.0.0.1:{NEW_PORT}/login")
                    break
            except (URLError, HTTPError, ValueError, OSError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError("New loopback frontend did not become healthy")
        # Check the stored original again before touching the protected proxy.
        if digest(NGINX) != report["nginx_sha256"]:
            raise RuntimeError("Nginx changed since preflight")
        atomic_bytes(NGINX, UPDATED.read_bytes(), 0o644)
        validate_nginx()
        reload_nginx()
        assert_http("http://172.18.48.66:8082/health/ready")
        assert_http("http://127.0.0.1:8081/health")
        assert_http(f"http://127.0.0.1:{OLD_PORT}/login")
        assert_http(f"http://127.0.0.1:{NEW_PORT}/login")
        print("EXTERNAL_BLUEGREEN_HANDOFF_DONE", SOURCE, flush=True)
        print("SITE_FULL_DR_UNVERIFIED; DO_NOT_CLAIM_HARDWARE_ACCEPTANCE", flush=True)
    except BaseException:
        if ORIGINAL.exists() and UPDATED.exists():
            try:
                recover()
            except Exception:
                print("CRITICAL: automatic nginx rollback needs operator repair", file=sys.stderr)
        raise

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "execute", "rollback"])
    parser.add_argument("--expected-nginx-sha256", default="")
    parser.add_argument("--approved-frontend-only", action="store_true")
    args = parser.parse_args()
    if args.mode == "check":
        print(json.dumps(snapshot(), indent=2))
        return 0
    if os.geteuid() != 0:
        raise RuntimeError("Root required")
    fd = os.open("/run/lock/nexolab-1560-bluegreen.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.mode == "rollback":
        recover()
        return 0
    if not args.approved_frontend_only:
        raise RuntimeError("Explicit operator approval required")
    if not re.fullmatch("[0-9a-f]{64}", args.expected_nginx_sha256):
        raise RuntimeError("Current nginx SHA pin required from check")
    if digest(NGINX) != args.expected_nginx_sha256:
        raise RuntimeError("Live nginx config no longer matches reviewed SHA")
    install()
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("FRONTEND_HANDOFF_BLOCKED:", str(exc), file=sys.stderr)
        raise SystemExit(78)
