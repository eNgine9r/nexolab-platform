from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("protected_package", ROOT / "scripts/nexolab-protected-package.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)
ORIGIN = "https://monitor.example.test"
ORG = "00000000-0000-0000-0000-000000000001"
SOURCE = "a" * 40
PLATFORM = {"aarch64": "linux/arm64", "x86_64": "linux/amd64"}[platform.machine()]


def fixture(root: Path):
    artifact = root / "bundle/frontend-external"
    artifact.mkdir(parents=True)
    runtime = root / "runtime"
    chunk = runtime / ".next/static/chunks/app.js"
    chunk.parent.mkdir(parents=True)
    (runtime / ".next/BUILD_ID").write_text("new-build")
    contract = {"runtime_mode": "live", "api_base_url": ORIGIN, "websocket_url": "wss://monitor.example.test/api/v1/telemetry/live",
                "auth_provider": "local", "organization_id": ORG, "external_https_stage": "true"}
    chunk.write_text(json.dumps(list(contract.values())))
    next_bin = runtime / "node_modules/.bin/next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("#!/bin/sh\nexit 0\n")
    next_bin.chmod(0o755)
    (runtime / "public").mkdir()
    (runtime / "public/logo.svg").write_text("<svg/>")
    with tarfile.open(artifact / "frontend-runtime.tar.gz", "w:gz") as archive:
        for name in (".next", "node_modules", "public"):
            archive.add(runtime / name, arcname=name)
    metadata = {
        "package.json": "{}", "package-lock.json": "{}",
        "frontend-source-sha.txt": SOURCE, "frontend-platform.txt": PLATFORM,
        "frontend-runtime-contract.txt": "\n".join(f"{k}={v}" for k, v in contract.items()) + "\n",
        "frontend-node-version.txt": "22.23.1", "frontend-build-id.txt": "new-build",
        "frontend-public-contract.txt": "PASS", "frontend-native-files.txt": "",
        "frontend-runtime-files-sha256.txt": "\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(runtime)}" for p in runtime.rglob("*") if p.is_file()) + "\n",
    }
    for name, value in metadata.items():
        (artifact / name).write_text(value)
    (artifact / "frontend-package-sha256.txt").write_text("\n".join(f"{hashlib.sha256((artifact / n).read_bytes()).hexdigest()}  {n}" for n in ("package.json", "package-lock.json")) + "\n")
    (artifact / "frontend-artifact-sha256.txt").write_text("\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in sorted(artifact.iterdir()) if p.is_file()) + "\n")
    node = root / "bin/node"
    node.parent.mkdir()
    node.write_text("#!/bin/sh\nprintf 'v22.23.1\\n'\n")
    node.chmod(0o755)
    unit = root / "external.service"
    unit.write_text(f"""[Service]
User=nexolab
WorkingDirectory=/old
ExecStart={node} /old/next start --hostname 127.0.0.1 --port 3100
Environment=NEXT_PUBLIC_NEXOLAB_API_BASE_URL={ORIGIN}
Environment=NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://monitor.example.test/api/v1/telemetry/live
Environment=NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local
Environment=NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID={ORG}
Environment=NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE=true
Environment=NEXOLAB_EXTERNAL_HTTPS_STAGE=true
Environment=NEXOLAB_SERVER_API_BASE_URL=http://127.0.0.1:8082
Environment=NEXOLAB_RUNTIME_IDENTITY_FILE=/old/identity.json
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
MemoryMax=768M
MemorySwapMax=0
ReadWritePaths=/old/.next/cache
""")
    nginx = root / "nginx.conf"
    nginx.write_text("server_name monitor.example.test; auth_request /_nexolab_external_auth; proxy_pass http://127.0.0.1:3100; proxy_pass http://127.0.0.1:8082;")
    manifest = {"source_commit": SOURCE, "platform": PLATFORM, "dashboard": {"auth_provider": "local"}}
    manifest["external_frontend"] = package.artifact_metadata(root / "bundle", SOURCE, PLATFORM)
    return manifest, unit, nginx


class ProtectedPackageTests(unittest.TestCase):
    def test_metadata_binds_source_profile_and_entire_artifact_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, _, _ = fixture(root)
            self.assertEqual(package.verify_metadata(root / "bundle", manifest)["source_commit"], SOURCE)
            with self.assertRaisesRegex(ValueError, "source differs"):
                package.artifact_metadata(root / "bundle", "b" * 40, PLATFORM)
            (root / "bundle/frontend-external/frontend-runtime.tar.gz").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum differs"):
                package.verify_metadata(root / "bundle", manifest)

    def test_prepare_imports_offline_and_activation_failure_restores_original_unit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, unit, nginx = fixture(root)
            calls = []
            original = unit.read_text()
            real_run = subprocess.run

            def runner(args, **kwargs):
                calls.append(args)
                if args[0] == "bash":
                    return real_run(args, **kwargs)
                if args[0] == "install":
                    Path(args[-1]).write_bytes(Path(args[-2]).read_bytes())
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            with (patch.object(package, "UNIT", unit), patch.object(package, "NGINX", nginx),
                  patch.object(package, "RELEASES", root / "releases"),
                  patch.object(package.subprocess, "run", side_effect=runner),
                  patch.object(package.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_name="nexolab")),
                  patch.object(package.frontend, "request", return_value=(200, json.dumps({"source_commit": "b" * 40, "build_id": "old-build"}).encode())),
                  patch.object(package.frontend, "probe_frontend"), patch.object(package.frontend, "probe_gateway") as gateway):
                transaction = package.ProtectedPackageFrontend(root / "bundle", manifest, {"source_commit": "b" * 40}, root / "evidence/operation-1")
                transaction.prepare()
                self.assertTrue((transaction.release / "public/logo.svg").exists())
                self.assertTrue((transaction.release / "node_modules/.bin/next").exists())
                self.assertEqual(unit.read_text(), original)
                gateway.side_effect = ValueError("anonymous API unexpectedly accessible")
                with self.assertRaises(ValueError):
                    transaction.activate()
                self.assertTrue(transaction.touched)
                transaction.rollback()
                self.assertFalse(transaction.touched)
                self.assertEqual(unit.read_text(), original)
                self.assertFalse(any("npm" in args or "funnel" in args for args in calls))

    def test_mixed_current_source_and_protected_frontend_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, unit, nginx = fixture(root)
            with (patch.object(package, "UNIT", unit), patch.object(package, "NGINX", nginx),
                  patch.object(package.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")),
                  patch.object(package.frontend, "request", return_value=(200, b'{"source_commit":"wrong","build_id":"old"}'))):
                with self.assertRaisesRegex(ValueError, "current protected frontend"):
                    package.ProtectedPackageFrontend(root / "bundle", manifest, {"source_commit": SOURCE}, root / "evidence/operation-2")
                self.assertFalse((root / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
