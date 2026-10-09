#!/usr/bin/env python3
"""Digest-bound, offline frontend handoff for an already-installed Google gateway."""
from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("protected_frontend", SCRIPT_DIR / "nexolab-protected-frontend.py")
frontend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontend)
UNIT = Path("/etc/systemd/system/nexolab-external-frontend.service")
NGINX = Path("/opt/nexolab-external/nginx.conf")
RELEASES = Path("/opt/nexolab-external/releases")


def artifact_metadata(bundle: Path, source: str, platform: str) -> dict[str, str] | None:
    artifact = bundle / "frontend-external"
    if not artifact.exists():
        return None
    contract: dict[str, str] = {}
    for line in (artifact / "frontend-runtime-contract.txt").read_text().splitlines():
        key, value = line.split("=", 1)
        if key in contract:
            raise ValueError("duplicate external artifact contract field")
        contract[key] = value
    if set(contract) != {"runtime_mode", "api_base_url", "websocket_url", "auth_provider", "organization_id", "external_https_stage"}:
        raise ValueError("external artifact contract fields differ")
    origin = contract["api_base_url"]
    host = frontend.origin_host(origin)
    if (contract["runtime_mode"] != "live" or contract["auth_provider"] != "local"
            or contract["external_https_stage"] != "true"
            or contract["websocket_url"] != f"wss://{host}/api/v1/telemetry/live"
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", contract["organization_id"])):
        raise ValueError("external artifact requires same-origin HTTPS/WSS, local auth and private image transport")
    if (artifact / "frontend-source-sha.txt").read_text().strip() != source:
        raise ValueError("external artifact source differs from package runtime source")
    if (artifact / "frontend-platform.txt").read_text().strip() != platform:
        raise ValueError("external artifact platform differs from package")
    checksums = artifact / "frontend-artifact-sha256.txt"
    seen: set[str] = set()
    for line in checksums.read_text().splitlines():
        digest, relative = line.split("  ", 1)
        if relative in seen or not re.fullmatch(r"[A-Za-z0-9._-]+", relative) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("unsafe external artifact checksum record")
        seen.add(relative)
        hasher = hashlib.sha256()
        with (artifact / relative).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ValueError("external artifact checksum differs")
    expected_files = {"frontend-runtime.tar.gz", "package.json", "package-lock.json", "frontend-source-sha.txt",
                      "frontend-package-sha256.txt", "frontend-runtime-contract.txt", "frontend-platform.txt",
                      "frontend-node-version.txt", "frontend-build-id.txt", "frontend-runtime-files-sha256.txt",
                      "frontend-public-contract.txt", "frontend-native-files.txt"}
    if seen != expected_files:
        raise ValueError("external artifact checksum inventory is incomplete")
    build = (artifact / "frontend-build-id.txt").read_text().strip()
    if not build or len(build) > 256:
        raise ValueError("external artifact build identity is absent")
    return {"artifact_directory": "frontend-external", "origin": origin,
            "organization_id": contract["organization_id"], "source_commit": source,
            "build_id": build, "profile": "google_https"}


def verify_metadata(bundle: Path, manifest: dict[str, Any]) -> dict[str, str] | None:
    metadata = artifact_metadata(bundle, manifest["source_commit"], manifest["platform"])
    if manifest.get("external_frontend") != metadata:
        raise ValueError("external frontend manifest does not match its artifact")
    if metadata and manifest.get("dashboard", {}).get("auth_provider") != "local":
        raise ValueError("protected package must preserve local application authentication")
    return metadata


class ProtectedPackageFrontend:
    def __init__(self, bundle: Path, manifest: dict[str, Any], current: dict[str, Any], evidence: Path):
        self.metadata = verify_metadata(bundle, manifest)
        self.enabled = UNIT.exists()
        self.touched = False
        self.candidate = ""
        self.bundle, self.evidence = bundle, evidence
        self.expected_current = current.get("source_commit")
        if not self.enabled:
            if self.metadata:
                raise ValueError("protected package requires the existing operator-installed Google gateway")
            return
        if not self.metadata:
            raise ValueError("protected_frontend_package_required: package lacks the matching HTTPS artifact")
        frontend.require_memory_controller()
        self.original = UNIT.read_text()
        self.values = frontend.directives(self.original)
        frontend.validate(self.original, NGINX.read_text(), self.metadata["origin"], self.metadata["organization_id"])
        self.node = self.values["ExecStart"].split(" ", 1)[0]
        self.api = self.values["env:NEXOLAB_SERVER_API_BASE_URL"]
        if f"proxy_pass {self.api};" not in NGINX.read_text():
            raise ValueError("protected gateway and frontend server API upstreams differ")
        if subprocess.run(["systemctl", "show", UNIT.name, "-p", "DropInPaths", "--value"], check=True, text=True, capture_output=True).stdout.strip():
            raise ValueError("protected frontend service overrides require review")
        self.was_active = subprocess.run(["systemctl", "is-active", "--quiet", UNIT.name]).returncode == 0
        if not self.was_active:
            raise ValueError("protected gateway frontend must be healthy before a package handoff")
        status, body = frontend.request(3100, "/api/runtime-identity", frontend.origin_host(self.metadata["origin"]))
        identity = json.loads(body)
        if status != 200 or identity.get("source_commit") != self.expected_current or not identity.get("build_id"):
            raise ValueError("current protected frontend does not match current package/source authority")
        self.original_identity = identity
        self.release = RELEASES / (manifest["source_commit"] + "-" + evidence.name)

    def run(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(args, check=True, **kwargs)

    def cleanup_candidate(self) -> None:
        if self.candidate:
            state = self.run(["systemctl", "show", self.candidate, "-p", "LoadState", "--value"], text=True, capture_output=True).stdout.strip()
            if state != "not-found":
                self.run(["systemctl", "stop", self.candidate])
            self.candidate = ""

    def prepare(self) -> None:
        if not self.enabled:
            return
        frontend.require_candidate_port(3102)
        self.evidence.mkdir(parents=True, exist_ok=True)
        (self.evidence / "external-unit-before.service").write_text(self.original)
        (self.evidence / "external-identity-before.json").write_text(json.dumps(self.original_identity))
        RELEASES.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.release.mkdir(mode=0o755)
        artifact = self.bundle / "frontend-external"
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(artifact / name, self.release / name)
        (self.release / ".nvmrc").write_text((artifact / "frontend-node-version.txt").read_text())
        env = dict(os.environ, PATH=str(Path(self.node).parent) + ":" + os.environ.get("PATH", ""))
        host = frontend.origin_host(self.metadata["origin"])
        self.run(["bash", "-c", 'source "$1"; shift; nexolab_frontend_import_artifact "$@"', "protected-import",
                  str(SCRIPT_DIR / "lib/raspberry-pi-frontend-release.sh"), str(artifact), str(self.bundle), str(self.release),
                  self.metadata["source_commit"], "live", self.metadata["origin"], f"wss://{host}/api/v1/telemetry/live", "local",
                  self.metadata["organization_id"], str(self.evidence / "external-artifact-import.txt"), "true"], env=env)
        unit = frontend.render_unit(self.original, str(self.release), self.node, self.api)
        (self.evidence / "external-unit-candidate.service").write_text(unit)
        (self.release / ".next/cache").mkdir(exist_ok=True)
        identity = {"schema_version": "nexolab-runtime-identity-v1", "service": "dashboard",
                    "source_commit": self.metadata["source_commit"], "build_id": self.metadata["build_id"],
                    "deployed_at": None, "identity_source": "offline_image_manifest"}
        (self.release / ".nexolab-runtime-identity.json").write_text(json.dumps(identity))
        owner = pwd.getpwnam(self.values["User"])
        for directory, directories, files in os.walk(self.release):
            for path in [Path(directory)] + [Path(directory) / name for name in directories + files]:
                os.chown(path, owner.pw_uid, owner.pw_gid, follow_symlinks=False)
        # The kernel enforces the same cap as the installed frontend during preflight.
        self.candidate = "nexolab-protected-package-" + self.evidence.name + ".service"
        try:
            self.run(["systemd-run", "--unit", self.candidate, "--collect", "--service-type=exec",
                      "--property", f"User={owner.pw_name}", "--property", f"WorkingDirectory={self.release}",
                      "--property", "MemoryMax=768M", "--property", "MemorySwapMax=0", "--property", "TasksMax=64",
                      "--property", "NoNewPrivileges=yes", "--setenv", "NODE_ENV=production",
                      "--setenv", "NEXT_TELEMETRY_DISABLED=1", "--setenv", "NODE_OPTIONS=--max-old-space-size=384",
                      "--setenv", "NEXOLAB_EXTERNAL_HTTPS_STAGE=true",
                      "--setenv", f"NEXOLAB_SERVER_API_BASE_URL={self.api}",
                      self.node, str(self.release / "node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", "3102"])
            frontend.probe_frontend(3102, self.metadata["source_commit"], self.metadata["build_id"], host)
        finally:
            self.cleanup_candidate()

    def activate(self) -> None:
        if not self.enabled:
            return
        self.touched = True
        self.run(["systemctl", "stop", UNIT.name])
        self.run(["install", "-m", "0644", str(self.evidence / "external-unit-candidate.service"), str(UNIT)])
        self.run(["systemctl", "daemon-reload"])
        self.run(["systemctl", "start", UNIT.name])
        host = frontend.origin_host(self.metadata["origin"])
        frontend.probe_frontend(3100, self.metadata["source_commit"], self.metadata["build_id"], host)
        frontend.probe_gateway(host)
        (self.evidence / "external-verified.json").write_text(json.dumps(self.metadata))

    def rollback(self) -> None:
        if not self.touched:
            return
        self.run(["systemctl", "stop", UNIT.name])
        self.run(["install", "-m", "0644", str(self.evidence / "external-unit-before.service"), str(UNIT)])
        self.run(["systemctl", "daemon-reload"])
        self.run(["systemctl", "start", UNIT.name])
        frontend.probe_frontend(3100, self.original_identity["source_commit"], self.original_identity["build_id"], frontend.origin_host(self.metadata["origin"]))
        self.touched = False
