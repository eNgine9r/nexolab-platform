from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("protected_frontend", ROOT / "scripts/nexolab-protected-frontend.py")
frontend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontend)
ORIGIN = "https://monitor.example.test"
UNIT = """[Service]
User=nexolab
WorkingDirectory=/old
ExecStart=/node /old/next start --hostname 127.0.0.1 --port 3100
Environment=NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://monitor.example.test
Environment=NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://monitor.example.test/api/v1/telemetry/live
Environment=NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local
Environment=NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=org
Environment=NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE=true
Environment=NEXOLAB_EXTERNAL_HTTPS_STAGE=true
Environment=NEXOLAB_RUNTIME_IDENTITY_FILE=/old/identity.json
Environment=NEXOLAB_SERVER_API_BASE_URL=http://127.0.0.1:8082
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
MemoryMax=768M
MemorySwapMax=0
ReadWritePaths=/old/.next/cache
"""
NGINX = "server_name monitor.example.test; auth_request /_nexolab_external_auth; proxy_pass http://127.0.0.1:3100;"


class ProtectedFrontendTests(unittest.TestCase):
    def _dependency_handoff(self, operation, *, failed_start=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "external-unit-before.service").write_text(UNIT)
            (root / "external-unit-candidate.service").write_text(UNIT)
            (root / "external-active-before.txt").write_text("active\n")
            (root / "release/.next").mkdir(parents=True)
            (root / "release/.next/BUILD_ID").write_text("build")
            command = f"""source scripts/lib/protected-frontend-release.sh
AUDIT_DIR={root}
SCRIPT_DIR={ROOT}/scripts
EXTERNAL_FRONTEND_ORIGIN={ORIGIN}
EXTERNAL_FRONTEND_ENABLED=1
EXTERNAL_FRONTEND_TOUCHED=1
EXTERNAL_FRONTEND_GATEWAY_WAS_ACTIVE=1
EXTERNAL_FRONTEND_RELEASE_DIR={root}/release
gateway_active=1
log() {{ :; }}
sudo() {{
  printf '%s\\n' "$*" >> '{root}/calls'
  if [[ "$1" == timeout ]]; then shift 4; fi
  # Model the installed systemd Requires dependency: frontend stop stops NGINX.
  if [[ "$*" == 'systemctl stop nexolab-external-frontend.service' ]]; then gateway_active=0; fi
  if [[ "$*" == 'systemctl start nexolab-external-nginx.service' ]]; then
    [[ '{int(failed_start)}' == 0 ]] || return 1
    gateway_active=1
  fi
}}
python3() {{
  printf '%s\\n' "$*" >> '{root}/probes'
  [[ "$2" != gateway ]] || [[ "$gateway_active" == 1 ]]
}}
nexolab_external_frontend_{operation}
rc=$?
printf '%s %s %s\\n' "$rc" "$gateway_active" "$EXTERNAL_FRONTEND_TOUCHED"
"""
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, text=True, capture_output=True)
            return result.stdout.strip(), (root / "calls").read_text(), (root / "probes").read_text()

    def test_activation_restores_requires_dependent_gateway(self):
        state, calls, probes = self._dependency_handoff("activate")
        self.assertEqual(state.split()[:2], ["0", "1"])
        self.assertIn("systemctl start nexolab-external-nginx.service", calls)
        self.assertIn(" gateway --origin", probes)

    def test_rollback_restores_gateway_and_verifies_denial_before_success(self):
        state, calls, probes = self._dependency_handoff("rollback")
        self.assertEqual(state.split(), ["0", "1", "0"])
        self.assertIn("systemctl start nexolab-external-nginx.service", calls)
        self.assertIn(" gateway --origin", probes)
        state, _, _ = self._dependency_handoff("rollback", failed_start=True)
        self.assertEqual(state.split(), ["1", "0", "1"])

    def test_origin_and_service_reject_unsafe_variants(self):
        frontend.validate(UNIT, NGINX, ORIGIN, "org")
        for origin in ("http://monitor.example.test", ORIGIN + "/", ORIGIN + ":443", "https://user@monitor.example.test", ORIGIN + "\nInjected"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                frontend.origin_host(origin)
        for old, new in (("User=nexolab", "User=root"), ("MemoryMax=768M", "MemoryMax=infinity"),
                         ("--hostname 127.0.0.1", "--hostname 0.0.0.0"),
                         ("EXTERNAL_HTTPS_STAGE=true", "EXTERNAL_HTTPS_STAGE=false")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                frontend.validate(UNIT.replace(old, new), NGINX, ORIGIN, "org")
        with self.assertRaises(ValueError):
            frontend.validate(UNIT + "MemoryMax=infinity\n", NGINX, ORIGIN, "org")

    def test_render_preserves_security_and_moves_only_frontend_contract(self):
        rendered = frontend.render_unit(UNIT, "/releases/abc", "/node/bin/node", "http://127.0.0.1:8082")
        self.assertIn("WorkingDirectory=/releases/abc", rendered)
        self.assertIn("/releases/abc/.nexolab-runtime-identity.json", rendered)
        self.assertIn("MemoryMax=768M", rendered)
        self.assertIn("--hostname 127.0.0.1 --port 3100", rendered)
        self.assertIn("NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE=true", rendered)
        with self.assertRaises(ValueError):
            frontend.render_unit(UNIT, "/releases/a%h", "/node", "http://127.0.0.1:8082")

    def test_restart_readiness_retries_connection_refused_then_requires_exact_identity(self):
        responses = [ConnectionRefusedError(), (200, json.dumps({"source_commit": "source", "build_id": "build"}).encode()), (200, b"ok")]
        with patch.object(frontend, "request", side_effect=responses), patch.object(frontend.time, "sleep"):
            frontend.probe_frontend(3102, "source", "build", "monitor.example.test")
        with patch.object(frontend, "request", return_value=(200, b'{"source_commit":"wrong","build_id":"build"}')):
            with self.assertRaisesRegex(ValueError, "exact source/build"):
                frontend.probe_frontend(3102, "source", "build", "monitor.example.test", timeout=0)

    def test_gateway_rejects_unauthorized_success_even_with_working_login(self):
        with patch.object(frontend, "request", side_effect=[(401, b"")] * 4 + [(302, b"")]):
            frontend.probe_gateway("monitor.example.test")
        with patch.object(frontend, "request", return_value=(200, b"unexpected public content")):
            with self.assertRaisesRegex(ValueError, "anonymous"):
                frontend.probe_gateway("monitor.example.test")

    def test_gateway_startup_wait_is_bounded_and_security_failure_is_not_retried(self):
        with (patch.object(frontend, "request", side_effect=[ConnectionRefusedError()] + [(401, b"")] * 4 + [(302, b"")]),
              patch.object(frontend.time, "sleep") as wait):
            frontend.probe_gateway("monitor.example.test")
            self.assertEqual(wait.call_count, 1)
        with (patch.object(frontend, "request", side_effect=ConnectionRefusedError()),
              patch.object(frontend.time, "monotonic", side_effect=[0, 0, 15])):
            with self.assertRaisesRegex(ValueError, "loopback listener"):
                frontend.probe_gateway("monitor.example.test")
        with (patch.object(frontend, "request", return_value=(200, b"secret body")),
              patch.object(frontend.time, "sleep") as wait):
            with self.assertRaisesRegex(ValueError, "anonymous"):
                frontend.probe_gateway("monitor.example.test")
            wait.assert_not_called()

    def test_inactive_gateway_preflight_never_starts_it(self):
        with (patch.object(frontend.subprocess, "run", return_value=subprocess.CompletedProcess([], 3)) as run,
              patch.object(frontend, "probe_gateway") as probe):
            with self.assertRaisesRegex(ValueError, "must be active"):
                frontend.require_gateway_active("monitor.example.test")
            self.assertEqual(run.call_args.args[0], ["systemctl", "is-active", "--quiet", "nexolab-external-nginx.service"])
            probe.assert_not_called()

    def test_source_preflight_rejects_inactive_gateway_before_enabling_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "installed.service").write_text(UNIT)
            (root / "artifact").mkdir()
            (root / "artifact/frontend-source-sha.txt").write_text("source")
            lib = (ROOT / "scripts/lib/protected-frontend-release.sh").read_text()
            lib = lib.replace("local unit=/etc/systemd/system/nexolab-external-frontend.service", f"local unit={root}/installed.service")
            command = f"""{lib}
AUDIT_DIR={root}
SCRIPT_DIR={ROOT}/scripts
RUNTIME_MODE=lan
EXTERNAL_FRONTEND_ARTIFACT_INPUT={root}/artifact
EXTERNAL_FRONTEND_ORIGIN={ORIGIN}
CURRENT_HEAD=source
log() {{ :; }}
systemctl() {{ if [[ "$1" == is-active ]]; then echo active; fi; }}
python3() {{ [[ "$2" != gateway-active ]]; }}
nexolab_frontend_verify_profile() {{ return 0; }}
nexolab_external_frontend_preflight
printf '%s %s %s\\n' "$?" "$EXTERNAL_FRONTEND_ENABLED" "$EXTERNAL_FRONTEND_GATEWAY_WAS_ACTIVE"
"""
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.stdout.strip(), "1 0 0", result.stderr)

    def test_reviewed_gateway_tool_survives_historical_checkout_and_rejects_tampering(self):
        text = (ROOT / "scripts/deploy-current-head-raspberry-pi.sh").read_text()
        staging = text[text.index('EXTERNAL_FRONTEND_TOOL="$AUDIT_DIR/nexolab-protected-frontend.py"'):text.index('\nDEVICE_AGENT_STARTUP_GATE_HELPER=')]
        self.assertLess(text.index(staging), text.rindex('git switch --detach "$TARGET_HEAD"'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "audit").mkdir()
            (root / "scripts").mkdir()
            helper = root / "scripts/nexolab-protected-frontend.py"
            helper.write_bytes((ROOT / "scripts/nexolab-protected-frontend.py").read_bytes())
            command = f"""source scripts/lib/protected-frontend-release.sh
AUDIT_DIR={root}/audit
SCRIPT_DIR={root}/scripts
{staging}
printf 'raise SystemExit(99)\\n' > "$SCRIPT_DIR/nexolab-protected-frontend.py"
nexolab_external_frontend_tool --help || exit 1
chmod u+w "$EXTERNAL_FRONTEND_TOOL"
printf 'raise SystemExit(98)\\n' > "$EXTERNAL_FRONTEND_TOOL"
if nexolab_external_frontend_tool --help; then exit 2; fi
"""
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("gateway-active", result.stdout)

    def test_failed_pair_restores_previous_external_unit_and_active_state(self):
        # Execute the real rollback function using a disposable filesystem and a
        # recorded systemctl adapter; no production host/service is touched.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "external-unit-before.service").write_text(UNIT)
            (root / "external-active-before.txt").write_text("active\n")
            command = f"""source scripts/lib/protected-frontend-release.sh
AUDIT_DIR={root}
EXTERNAL_FRONTEND_TOUCHED=1
EXTERNAL_FRONTEND_GATEWAY_WAS_ACTIVE=1
log() {{ :; }}
python3() {{ printf '%s\\n' "$*" >> '{root}/probes'; }}
sudo() {{
  if [[ "$1" == install ]]; then cp "$4" '{root}/restored.service';
  else printf '%s\\n' "$*" >> '{root}/calls'; fi
}}
nexolab_external_frontend_rollback
test "$EXTERNAL_FRONTEND_TOUCHED" = 0
"""
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "restored.service").read_text(), UNIT)
            self.assertIn("systemctl start nexolab-external-frontend.service", (root / "calls").read_text())
            self.assertIn("external-identity-before.json", (root / "probes").read_text())

    def test_deploy_prepares_both_candidates_before_runtime_mutation(self):
        text = (ROOT / "scripts/deploy-current-head-raspberry-pi.sh").read_text()
        self.assertLess(text.index("nexolab_external_frontend_prepare ||"), text.index('log "RUNTIME MUTATION STARTED: central backend activation"'))
        self.assertIn('FRONTEND_CANDIDATE_PORT:-3101', text)
        self.assertIn('nexolab_external_frontend_activate', text)
        self.assertIn('nexolab_external_frontend_rollback', text)

    def test_lan_restore_is_attempted_when_protected_restore_fails(self):
        text = (ROOT / "scripts/deploy-current-head-raspberry-pi.sh").read_text()
        function = text[text.index("rollback_dashboard_release() {"):text.index('\nlog "Activating verified frontend release"')]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "unit-before").write_text("previous LAN unit")
            (root / "identity-before").write_text('{"source_commit":"old","build_id":"old-build"}')
            command = f"""{function}
DASHBOARD_UNIT_BACKUP={root}/unit-before
DASHBOARD_UNIT={root}/unit-active
DASHBOARD_RUNTIME_IDENTITY_BACKUP={root}/identity-before
DASHBOARD_RUNTIME_IDENTITY_FILE={root}/identity-active
SCRIPT_DIR={ROOT}/scripts
LAN_FRONTEND_TOUCHED=1
log() {{ :; }}
nexolab_external_frontend_rollback() {{ return 1; }}
python3() {{ return 0; }}
sudo() {{ if [[ "$1" == install ]]; then cp "$4" "$5"; fi; }}
rollback_dashboard_release
rc=$?
test "$rc" = 1 && test "$LAN_FRONTEND_TOUCHED" = 1
"""
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "unit-active").read_text(), "previous LAN unit")
            self.assertEqual((root / "identity-active").read_bytes(), (root / "identity-before").read_bytes())


if __name__ == "__main__":
    unittest.main()
