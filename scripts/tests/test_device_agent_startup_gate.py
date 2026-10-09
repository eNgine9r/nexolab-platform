from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/device-agent-startup-gate.py"
IMAGE = "sha256:" + "a" * 64


def helper():
    spec = importlib.util.spec_from_file_location("startup_gate", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model():
    return {"services": {"device-agent": {
        "image": IMAGE,
        "entrypoint": ["/usr/bin/python3"],
        "command": ["/app/dual_bus_main.py"],
        "environment": {"SECRET": "do-not-record"},
        "volumes": [{"source": "edge-data", "target": "/var/lib/nexolab"}],
    }}}


def metadata():
    return {"Id": IMAGE, "Os": "linux", "Architecture": "arm64", "Config": {
        "User": "nonroot", "WorkingDir": "/app", "Entrypoint": None,
        "Cmd": ["/usr/local/bin/python3", "/app/adaptive_main.py"],
    }}


class StartupGateTests(unittest.TestCase):
    def test_hardware_overlay_supplies_interpreter_when_image_has_no_entrypoint(self):
        text = (ROOT / "infrastructure/compose/compose.hardware.yaml").read_text()
        self.assertIn('entrypoint: ["/usr/bin/python3"]', text)
        self.assertIn('command: ["/app/dual_bus_main.py"]', text)

    def test_accepts_exact_image_without_optional_oci_labels(self):
        gate = helper()
        for entrypoint in (None, ["/usr/bin/python3.13"]):
            image = metadata()
            image["Config"]["Entrypoint"] = entrypoint
            evidence = gate.validate_contract(model(), image, IMAGE, "linux/arm64")
            self.assertEqual(evidence["image_id"], IMAGE)
            self.assertNotIn("do-not-record", json.dumps(evidence))
            self.assertNotIn("volumes", evidence)

    def test_bare_script_and_unexpected_composition_rejected(self):
        gate = helper()
        for field, value in (("entrypoint", None), ("entrypoint", []),
                             ("entrypoint", ["/bin/sh"]), ("command", ["dual_bus_main.py"]),
                             ("command", ["/app/adaptive_main.py"]),
                             ("command", "/app/dual_bus_main.py"),
                             ("working_dir", "/other"), ("user", "root"), ("user", "1000")):
            with self.subTest(field=field, value=value):
                config = model()
                config["services"]["device-agent"][field] = value
                with self.assertRaises(gate.StartupGateError):
                    gate.validate_contract(config, metadata(), IMAGE, "linux/arm64")

    def test_wrong_image_platform_and_image_identity_are_rejected(self):
        gate = helper()
        cases = []
        bad = metadata(); bad["Id"] = "sha256:" + "b" * 64; cases.append(bad)
        bad = metadata(); bad["Architecture"] = "amd64"; cases.append(bad)
        bad = metadata(); bad["Os"] = "windows"; cases.append(bad)
        bad = metadata(); bad["Config"]["User"] = ""; cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(gate.StartupGateError):
                gate.validate_contract(model(), bad, IMAGE, "linux/arm64")
        config = model(); config["services"]["device-agent"]["image"] = "mutable:tag"
        with self.assertRaises(gate.StartupGateError):
            gate.validate_contract(config, metadata(), IMAGE, "linux/arm64")

    def test_probe_is_bounded_and_isolated_from_site_devices_and_data(self):
        gate = helper()
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")
        with patch.object(gate.subprocess, "run", side_effect=run):
            gate.probe_image(IMAGE)
        command, options = calls[0]
        for arg in ("--network=none", "--read-only", "--pull=never", "--cap-drop=ALL",
                    "--security-opt=no-new-privileges", "--memory=128m", "--pids-limit=32"):
            self.assertIn(arg, command)
        self.assertEqual(command[command.index("--entrypoint") + 1], "/usr/bin/python3")
        self.assertIn(IMAGE, command)
        self.assertNotIn("-v", command)
        self.assertNotIn("--mount", command)
        self.assertNotIn("--device", command)
        self.assertLessEqual(options["timeout"], 30)

    def test_missing_interpreter_script_or_import_fails_without_raw_diagnostics(self):
        gate = helper()
        failure = subprocess.CompletedProcess([], 1, "SECRET", "SECRET missing script")
        with patch.object(gate.subprocess, "run", return_value=failure):
            with self.assertRaises(gate.StartupGateError) as error:
                gate.probe_image(IMAGE)
        self.assertNotIn("SECRET", str(error.exception))

    def test_timed_out_probe_removes_only_its_own_named_container(self):
        gate = helper()
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[1] == "run":
                raise subprocess.TimeoutExpired(command, 30)
            return subprocess.CompletedProcess(command, 0, "", "")
        with patch.object(gate.subprocess, "run", side_effect=run):
            with self.assertRaises(gate.StartupGateError):
                gate.probe_image(IMAGE)
        name = calls[0][calls[0].index("--name") + 1]
        self.assertTrue(name.startswith("nexolab-agent-startup-"))
        self.assertEqual(calls[-1], ["docker", "rm", "--force", name])

    def test_historical_checkout_retains_corrected_overlay_and_staged_helper(self):
        gate = helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.email", "fixture@nexolab.local")
            git("config", "user.name", "Fixture")
            (root / "compose.hardware.yaml").write_text('services:\n  device-agent:\n    command: ["dual_bus_main.py"]\n')
            git("add", "."); git("commit", "-qm", "historical")
            old = git("rev-parse", "HEAD")
            (root / "startup.py").write_bytes(HELPER.read_bytes())
            git("add", "."); git("commit", "-qm", "control")
            audit = root / "runtime"; audit.mkdir()
            staged = audit / "startup.py"; staged.write_bytes(HELPER.read_bytes())
            overlay = audit / "compose.startup.json"
            gate.write_overlay(overlay, IMAGE)
            git("switch", "--detach", old)
            self.assertFalse((root / "startup.py").exists())
            self.assertTrue(staged.is_file())
            service = json.loads(overlay.read_text())["services"]["device-agent"]
            self.assertEqual(service, {
                "image": IMAGE, "entrypoint": ["/usr/bin/python3"], "command": ["/app/dual_bus_main.py"]})
            result = subprocess.run(["python3", str(staged), "--help"], capture_output=True)
            self.assertEqual(result.returncode, 0)

    def test_deployer_stages_and_probes_before_quiesce_and_activation(self):
        text = (ROOT / "scripts/deploy-current-head-raspberry-pi.sh").read_text()
        stage = text.index('DEVICE_AGENT_STARTUP_GATE_HELPER="$AUDIT_DIR/')
        checkout = text.index('git switch --detach "$TARGET_HEAD"', stage)
        gate = text.index('python3 "$DEVICE_AGENT_STARTUP_GATE_HELPER" check', checkout)
        quiesce = text.index("\nquiesce_edge_device_agent_for_cutover\n", gate)
        mutation = text.index("\nwrite_durable_runtime_mutation_marker\n", quiesce)
        self.assertLess(stage, checkout)
        self.assertLess(checkout, gate)
        self.assertLess(gate, quiesce)
        self.assertLess(quiesce, mutation)
        self.assertIn('EDGE_COMPOSE_ARGS+=( -f "$DEVICE_AGENT_STARTUP_OVERLAY" )', text)

    def test_offline_installer_checks_hardware_before_any_compose_up(self):
        text = (ROOT / "scripts/install-offline-bundle.sh").read_text()
        gate = text.index('python3 "$SCRIPT_DIR/device-agent-startup-gate.py" check')
        central = text.index('"${CENTRAL[@]}" up -d')
        edge = text.index('"${EDGE[@]}" up -d')
        self.assertLess(gate, central)
        self.assertLess(gate, edge)
        self.assertIn("--preflight-only", text)

    def test_package_gate_is_digest_bound_in_inventory(self):
        spec = importlib.util.spec_from_file_location("verifier", ROOT / "scripts/verify-offline-bundle.py")
        assert spec and spec.loader
        verifier = importlib.util.module_from_spec(spec); spec.loader.exec_module(verifier)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "evidence").mkdir()
            (root / "evidence/provenance.json").write_text(json.dumps({"tooling_capabilities": ["hardware-startup-gate"]}))
            with self.assertRaisesRegex(SystemExit, "not digest-bound"):
                verifier.verify_backup_policy_inventory(root, set())
            verifier.verify_backup_policy_inventory(root, {"scripts/device-agent-startup-gate.py"})

    def test_offline_installer_executes_gate_before_activation_and_preserves_overlay(self):
        for probe_fails, preflight_only in ((True, False), (False, True), (False, False)):
            with self.subTest(probe_fails=probe_fails, preflight_only=preflight_only), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                scripts = root / "bundle/scripts"
                (scripts / "lib").mkdir(parents=True)
                for name in ("install-offline-bundle.sh", "device-agent-startup-gate.py", "lib/deployment-lock.sh"):
                    shutil.copyfile(ROOT / "scripts" / name, scripts / name)
                verifier = scripts / "verify-offline-bundle.py"
                verifier.write_text(
                    'import sys\n'
                    'if "--emit-shell-env" in sys.argv:\n'
                    ' for key in ["DASHBOARD", "TELEMETRY", "DEVICE_AGENT", "MQTT", "POSTGRES", "OBJECT_STORAGE"]:\n'
                    '  print("export OFFLINE_"+key+"_IMAGE=fixture:"+key)\n'
                )
                smoke = scripts / "offline-bundle-smoke.sh"
                smoke.write_text("#!/bin/sh\nexit 0\n"); smoke.chmod(0o755)
                (root / "bundle/manifest.json").write_text(json.dumps({
                    "platform": "linux/arm64", "dashboard": {"origin": "http://127.0.0.1:3000"}
                }))
                central = root / "central.env"
                central.write_text("CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000\nCENTRAL_RESOURCE_PREFIX=fixture\n")
                edge = root / "edge.env"
                edge.write_text("RS485_HOST_DEVICE=/dev/serial/by-id/fixture\n")
                binary = root / "bin"; binary.mkdir()
                calls = root / "calls.jsonl"
                docker = binary / "docker"
                docker.write_text(
                    "#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
                    "a=sys.argv[1:]\n"
                    "with open(os.environ['CALLS'],'a') as out: out.write(json.dumps(a)+'\\n')\n"
                    "if a[:2]==['volume','inspect']: raise SystemExit(1)\n"
                    f"if a[:2]==['image','inspect']:\n print({IMAGE!r} if '--format' in a else json.dumps([{metadata()!r}]))\n"
                    "if a[0]=='compose' and '--format' in a:\n"
                    " overlay=Path(a[-4])\n"
                    " # Last -f path precedes config --format json.\n"
                    " print(overlay.read_text())\n"
                    "if a[0]=='run' and os.environ['PROBE_FAIL']=='1': raise SystemExit(42)\n"
                )
                docker.chmod(0o755)
                command = ["bash", str(scripts / "install-offline-bundle.sh"),
                           "--central-env", str(central), "--edge-env", str(edge),
                           "--runtime-mode", "lan", "--hardware"]
                if preflight_only:
                    command.append("--preflight-only")
                result = subprocess.run(command, capture_output=True, text=True, timeout=10, env={
                    **os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                    "CALLS": str(calls), "PROBE_FAIL": str(int(probe_fails)),
                    "XDG_RUNTIME_DIR": str(root), "NEXOLAB_STARTUP_EVIDENCE_ROOT": str(root / "evidence"),
                })
                self.assertEqual(result.returncode == 0, not probe_fails, result.stderr)
                recorded = [json.loads(line) for line in calls.read_text().splitlines()]
                probes = [i for i, command in enumerate(recorded) if command[0] == "run"]
                activations = [i for i, command in enumerate(recorded) if command[0] == "compose" and "up" in command]
                self.assertEqual(len(probes), 1)
                if probe_fails or preflight_only:
                    self.assertFalse(activations)
                else:
                    self.assertEqual(len(activations), 2)
                    self.assertLess(probes[0], activations[0])
                overlays = list((root / "evidence").glob("*/compose.startup.json"))
                self.assertEqual(len(overlays), 1)
                self.assertEqual(json.loads(overlays[0].read_text())["services"]["device-agent"]["image"], IMAGE)


if __name__ == "__main__":
    unittest.main()
