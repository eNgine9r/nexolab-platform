from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "resolve-layered-device-agent-runtime.py"
SPEC = importlib.util.spec_from_file_location("layered_device_agent_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

FORMAL_IMAGE = "sha256:" + "6" * 64
CURRENT_IMAGE = "sha256:" + "8" * 64


def run(*args: str, cwd: Path) -> str:
    result = subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class LayeredDeviceAgentRuntimeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        run("git", "init", "-b", "main", cwd=self.repo)
        run("git", "config", "user.email", "test@nexolab.local", cwd=self.repo)
        run("git", "config", "user.name", "NEXOLAB Test", cwd=self.repo)
        self.formal = self.commit("formal")
        self.compatibility = self.commit("compatibility")
        self.target = self.commit("target")
        self.evidence = self.repo / "runtime" / "evidence" / "issue-test-layered"
        self.evidence.mkdir(parents=True)
        self.write_runtime_evidence()
        self.write_state()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, value: str) -> str:
        (self.repo / "fixture.txt").write_text(value + "\n", encoding="utf-8")
        run("git", "add", "fixture.txt", cwd=self.repo)
        run("git", "commit", "-m", value, cwd=self.repo)
        return run("git", "rev-parse", "HEAD", cwd=self.repo)

    def write_state(self, **overrides: str) -> None:
        project = self.repo / ".project"
        project.mkdir(exist_ok=True)
        baselines = {
            "deployed_product_sha": self.formal,
            "device_agent_compatibility_source_sha": self.compatibility,
            "device_agent_image_id": CURRENT_IMAGE,
            "device_agent_rollback_image_id": FORMAL_IMAGE,
            "device_agent_runtime_evidence": "runtime/evidence/issue-test-layered",
        }
        baselines.update(overrides)
        (project / "ACTIVE_SPRINT.json").write_text(
            json.dumps({"schema_version": 2, "baselines": baselines}) + "\n",
            encoding="utf-8",
        )

    def write_runtime_evidence(self, **overrides: str) -> None:
        facts = {
            "status": "PASS",
            "cutover_authorized_by_product_owner": "true",
            "compatibility_source": self.compatibility,
            "device_agent_image_id": CURRENT_IMAGE,
            "device_agent_previous_image_id": FORMAL_IMAGE,
            "modbus_write": "none",
            "hardware_write": "none",
            "persistent_data_deletion": "none",
            "named_volume_deletion": "none",
        }
        facts.update(overrides)
        final = self.evidence / "final-runtime.txt"
        final.write_text("".join(f"{key}={value}\n" for key, value in facts.items()), encoding="utf-8")
        marker = self.evidence / "proof.txt"
        marker.write_text("accepted\n", encoding="utf-8")
        rows = []
        for path in (final, marker):
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
        (self.evidence / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def resolve(self):
        return M.resolve(
            self.repo,
            expected_deployed_source=self.formal,
            expected_formal_image=FORMAL_IMAGE,
        )

    def test_accepts_checksum_bound_layered_runtime(self) -> None:
        result = self.resolve()
        self.assertEqual(result["compatibility_source"], self.compatibility)
        self.assertEqual(result["device_agent_image_id"], CURRENT_IMAGE)
        self.assertEqual(result["device_agent_previous_image_id"], FORMAL_IMAGE)
        self.assertEqual(result["runtime_evidence"], "runtime/evidence/issue-test-layered")

    def test_rejects_formal_image_mismatch(self) -> None:
        self.write_state(device_agent_rollback_image_id="sha256:" + "7" * 64)
        with self.assertRaisesRegex(ValueError, "rollback image"):
            self.resolve()

    def test_rejects_runtime_safety_mismatch(self) -> None:
        self.write_runtime_evidence(modbus_write="present")
        with self.assertRaisesRegex(ValueError, "modbus_write"):
            self.resolve()

    def test_rejects_checksum_mismatch(self) -> None:
        (self.evidence / "final-runtime.txt").write_text("status=PASS\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.resolve()

    def test_rejects_compatibility_source_outside_formal_lineage(self) -> None:
        run("git", "switch", "--orphan", "unrelated", cwd=self.repo)
        (self.repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
        run("git", "add", "unrelated.txt", cwd=self.repo)
        run("git", "commit", "-m", "unrelated", cwd=self.repo)
        unrelated = run("git", "rev-parse", "HEAD", cwd=self.repo)
        self.write_state(device_agent_compatibility_source_sha=unrelated)
        self.write_runtime_evidence(compatibility_source=unrelated)
        with self.assertRaisesRegex(ValueError, "not a descendant"):
            self.resolve()

    def test_rejects_partially_configured_state(self) -> None:
        project = self.repo / ".project"
        (project / "ACTIVE_SPRINT.json").write_text(
            json.dumps({"schema_version": 2, "baselines": {"deployed_product_sha": self.formal}}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "partially configured"):
            self.resolve()


if __name__ == "__main__":
    unittest.main()
