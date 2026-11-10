from __future__ import annotations

import importlib.util
from pathlib import Path
import hashlib
import json
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "nexolab-1560-bluegreen-handoff.py"
SPEC = importlib.util.spec_from_file_location("nexolab_1560_handoff", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

ORIGINAL_NGINX = """http {
  map $http_upgrade $connection_upgrade { default upgrade; }
  server {
    location /a { auth_request /_nexolab_external_auth; proxy_pass http://127.0.0.1:3100; }
    location /b { auth_request /_nexolab_external_auth; proxy_pass http://127.0.0.1:3100; }
    location /api { auth_request /_nexolab_external_auth; proxy_pass http://172.18.48.66:8082; }
  }
}
"""
ORIGINAL_SERVICE = """[Unit]
Description=NEXOLAB separate HTTPS frontend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nexolab
Group=nexolab
WorkingDirectory=/opt/old/release
Environment=NODE_ENV=production
Environment=NEXOLAB_RUNTIME_IDENTITY_FILE=/opt/old/identity.json
ExecStart=/usr/bin/node /opt/old/release/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/opt/old/release/.next/cache
PrivateTmp=yes
Restart=on-failure
"""


class BluegreenHandoffContracts(unittest.TestCase):
    def test_nginx_keeps_oauth_and_api_routes(self):
        value = module.generate_nginx(ORIGINAL_NGINX)
        self.assertEqual(value.count("auth_request /_nexolab_external_auth;"), 3)
        self.assertEqual(value.count("proxy_pass http://nexolab_1560_bluegreen;"), 2)
        self.assertIn("server 127.0.0.1:3100 backup;", value)
        self.assertIn("server 127.0.0.1:3104 max_fails=1 fail_timeout=5s;", value)
        self.assertIn("proxy_pass http://172.18.48.66:8082;", value)

    def test_nginx_fails_closed_on_existing_or_unknown_topology(self):
        for value in (
            ORIGINAL_NGINX.replace("auth_request /_nexolab_external_auth;", "", 1),
            ORIGINAL_NGINX.replace("proxy_pass http://127.0.0.1:3100;", "proxy_pass http://127.0.0.1:3111;", 1),
            ORIGINAL_NGINX.replace("http {\n", "http {\n    upstream nexolab_1560_bluegreen {}\n", 1),
        ):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                module.generate_nginx(value)

    def test_service_isolated_and_hardened(self):
        rendered = module.generate_service(ORIGINAL_SERVICE)
        self.assertIn("ExecStart=/home/nexolab/.nvm/versions/node/v22.23.1/bin/node ", rendered)
        self.assertIn("--hostname 127.0.0.1 --port 3104", rendered)
        self.assertIn("Before=nexolab-external-nginx.service", rendered)
        self.assertIn("ProtectSystem=strict", rendered)
        self.assertIn("NoNewPrivileges=yes", rendered)
        self.assertIn("WantedBy=multi-user.target", rendered)
        self.assertIn(f"WorkingDirectory={module.RELEASE}", rendered)
        self.assertIn(f"ReadWritePaths={module.RELEASE / '.next/cache'}", rendered)
        self.assertNotIn("ExecStart=/usr/bin/node /opt/old", rendered)

    def test_service_rejects_modified_template(self):
        with self.assertRaises(ValueError):
            module.generate_service(ORIGINAL_SERVICE.replace("ProtectSystem=strict", "ProtectSystem=no"))
        with self.assertRaises(ValueError):
            module.generate_service(ORIGINAL_SERVICE.replace("ExecStart=", "ExecAnother=", 1))

    def test_resume_reuses_exact_original_gateway_and_saved_two_location_update(self):
        original = ORIGINAL_NGINX.encode()
        updated = module.generate_nginx(ORIGINAL_NGINX).encode()
        original_hash = hashlib.sha256(original).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "frontend-build-id.txt").write_text("TEST-BUILD")
            report = {
                "nginx_sha256": original_hash,
                "target_source": module.SOURCE,
                "target_build": "TEST-BUILD",
            }
            with mock.patch.object(module, "STAGE", root):
                module.validate_resume_config(original, updated, original, report, original_hash)

    def test_resume_rejects_altered_nginx_journal_or_active_gateway(self):
        original = ORIGINAL_NGINX.encode()
        updated = module.generate_nginx(ORIGINAL_NGINX).encode()
        original_hash = hashlib.sha256(original).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "frontend-build-id.txt").write_text("TEST-BUILD")
            report = {
                "nginx_sha256": original_hash,
                "target_source": module.SOURCE,
                "target_build": "TEST-BUILD",
            }
            cases = [
                (original, updated, b"unexpected proxy", report, original_hash),
                (original, b"malicious update", original, report, original_hash),
                (original, updated, original, {**report, "target_source": "f" * 40}, original_hash),
                (original, updated, original, {**report, "target_build": "wrong-build"}, original_hash),
                (original, updated, original, report, "0" * 64),
            ]
            with mock.patch.object(module, "STAGE", root):
                for case in cases:
                    with self.subTest(case=case[2][:20]), self.assertRaises(RuntimeError):
                        module.validate_resume_config(*case)

    def test_identity_schema_rejects_unrecognized_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stage = base / "staging"
            runtime = base / "release"
            stage.mkdir()
            (runtime / ".next").mkdir(parents=True)
            (stage / "frontend-build-id.txt").write_text("TEST-BUILD")
            (runtime / ".next" / "BUILD_ID").write_text("TEST-BUILD")
            identity_file = runtime / ".nexolab-runtime-identity.json"
            identity = {
                "schema_version": "nexolab-runtime-identity-v1",
                "service": "dashboard",
                "source_commit": module.SOURCE,
                "build_id": "TEST-BUILD",
                "identity_source": "invalid_offdevice_provenance",
            }
            with mock.patch.object(module, "STAGE", stage):
                identity_file.write_text(json.dumps(identity))
                with self.assertRaisesRegex(RuntimeError, "Unsupported runtime identity"):
                    module.verify_runtime(runtime)
                identity["identity_source"] = "offline_image_manifest"
                identity_file.write_text(json.dumps(identity))
                with mock.patch.object(
                    module.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)
                ) as fake_hash_check:
                    module.verify_runtime(runtime)
                    fake_hash_check.assert_called_once()

    def test_paths_are_fixed_and_no_acquisition_mutation(self):
        self.assertEqual(module.NEW_PORT, 3104)
        self.assertEqual(module.OLD_PORT, 3100)
        self.assertEqual(module.SOURCE, "08f1c8a4ed9212c25697d338583845bed5218ee5")
        self.assertTrue(str(module.RELEASE).startswith("/opt/nexolab-external/releases/"))
        self.assertFalse("docker" in MODULE_PATH.read_text().split("def install()")[1].split("def main()")[0])


if __name__ == "__main__":
    unittest.main()
