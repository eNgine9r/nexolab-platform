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
        self.runtime_evidence = self.repo / "runtime" / "evidence" / "issue-test-layered-runtime"
        self.pre_cutover = self.repo / "runtime" / "evidence" / "issue-test-layered-precutover"
        self.runtime_evidence.mkdir(parents=True)
        self.pre_cutover.mkdir(parents=True)
        self.write_pre_cutover_evidence()
        self.write_runtime_evidence()
        self.write_state()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, value: str) -> str:
        (self.repo / "fixture.txt").write_text(value + "\n", encoding="utf-8")
        run("git", "add", "fixture.txt", cwd=self.repo)
        run("git", "commit", "-m", value, cwd=self.repo)
        return run("git", "rev-parse", "HEAD", cwd=self.repo)

    @staticmethod
    def write_manifest(directory: Path, names: tuple[str, ...]) -> None:
        rows = []
        for name in names:
            path = directory / name
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
        (directory / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def write_state(self, **overrides: str) -> None:
        project = self.repo / ".project"
        project.mkdir(exist_ok=True)
        baselines = {
            "deployed_product_sha": self.formal,
            "device_agent_compatibility_source_sha": self.compatibility,
            "device_agent_compatibility_parent_sha": "1" * 40,
            "device_agent_image_id": CURRENT_IMAGE,
            "device_agent_rollback_image_id": FORMAL_IMAGE,
            "device_agent_runtime_evidence": str(self.runtime_evidence.relative_to(self.repo)),
            "device_agent_pre_cutover_evidence": str(self.pre_cutover.relative_to(self.repo)),
        }
        baselines.update(overrides)
        (project / "ACTIVE_SPRINT.json").write_text(
            json.dumps({"schema_version": 2, "baselines": baselines}) + "\n",
            encoding="utf-8",
        )

    def write_pre_cutover_evidence(
        self,
        *,
        compatibility_source: str | None = None,
        formal_source: str | None = None,
        candidate_image: str = CURRENT_IMAGE,
        rollback_image: str = FORMAL_IMAGE,
        release_ci: str = "PASS",
    ) -> None:
        compatibility_source = compatibility_source or self.compatibility
        formal_source = formal_source or self.formal
        parent = "1" * 40
        (self.pre_cutover / "source-lineage.txt").write_text(
            "\n".join(
                (
                    "status=PASS",
                    f"formal_deployed_product_sha={formal_source}",
                    f"candidate_compatibility_source_sha={compatibility_source}",
                    f"candidate_parent_sha={parent}",
                    "package_manifest_identity=PASS",
                    "accepted_identity_mismatches=0",
                    f"release_ci={release_ci}",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (self.pre_cutover / "candidate-device-agent.txt").write_text(
            "\n".join(
                (
                    "status=PASS",
                    f"source_sha={compatibility_source}",
                    f"image_id={candidate_image}",
                    "platform=linux/arm64",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (self.pre_cutover / "rollback-authority.txt").write_text(
            "\n".join(
                (
                    "status=READY",
                    f"current_device_agent_image_id={rollback_image}",
                    "active_env_mutated=false",
                    "dashboard_mutated=false",
                    "device_agent_mutated=false",
                    "telemetry_mutated=false",
                    "postgres_mutated=false",
                    "mqtt_mutated=false",
                    "modbus_write=none",
                    "hardware_write=none",
                    "persistent_data_deletion=none",
                    "named_volume_deletion=none",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        self.write_manifest(
            self.pre_cutover,
            ("source-lineage.txt", "candidate-device-agent.txt", "rollback-authority.txt"),
        )

    def write_runtime_evidence(
        self,
        *,
        compatibility_source: str | None = None,
        current_image: str = CURRENT_IMAGE,
        previous_image: str = FORMAL_IMAGE,
        **overrides: str,
    ) -> None:
        compatibility_source = compatibility_source or self.compatibility
        facts = {
            "status": "PASS",
            "cutover_authorized_by_product_owner": "true",
            "compatibility_source": compatibility_source,
            "device_agent_image_id": current_image,
            "device_agent_previous_image_id": previous_image,
            "modbus_write": "none",
            "hardware_write": "none",
            "persistent_data_deletion": "none",
            "named_volume_deletion": "none",
        }
        facts.update(overrides)
        (self.runtime_evidence / "final-runtime.txt").write_text(
            "".join(f"{key}={value}\n" for key, value in facts.items()),
            encoding="utf-8",
        )
        (self.runtime_evidence / "proof.txt").write_text("accepted\n", encoding="utf-8")
        self.write_manifest(self.runtime_evidence, ("final-runtime.txt", "proof.txt"))

    def resolve(self, authoritative_image: str = FORMAL_IMAGE):
        return M.resolve(
            self.repo,
            expected_deployed_source=self.formal,
            expected_formal_image=authoritative_image,
        )

    def test_accepts_checksum_bound_layered_runtime(self) -> None:
        result = self.resolve()
        self.assertEqual(result["compatibility_source"], self.compatibility)
        self.assertEqual(result["device_agent_image_id"], CURRENT_IMAGE)
        self.assertEqual(result["device_agent_previous_image_id"], FORMAL_IMAGE)
        self.assertEqual(result["formal_device_agent_image_id"], FORMAL_IMAGE)
        self.assertEqual(result["runtime_evidence"], str(self.runtime_evidence.relative_to(self.repo)))
        self.assertEqual(result["pre_cutover_evidence"], str(self.pre_cutover.relative_to(self.repo)))

    def test_accepts_offline_compatibility_identity_without_git_object(self) -> None:
        offline_source = "7" * 40
        self.write_state(device_agent_compatibility_source_sha=offline_source)
        self.write_pre_cutover_evidence(compatibility_source=offline_source)
        self.write_runtime_evidence(compatibility_source=offline_source)
        self.assertNotEqual(
            subprocess.run(
                ["git", "-C", str(self.repo), "cat-file", "-e", f"{offline_source}^{{commit}}"],
                check=False,
            ).returncode,
            0,
        )
        result = self.resolve()
        self.assertEqual(result["compatibility_source"], offline_source)

    def test_accepts_verified_layered_image_as_restored_current_authority(self) -> None:
        result = self.resolve(CURRENT_IMAGE)
        self.assertEqual(result["device_agent_image_id"], CURRENT_IMAGE)
        self.assertEqual(result["formal_device_agent_image_id"], FORMAL_IMAGE)

    def test_rejects_unknown_current_image_authority(self) -> None:
        with self.assertRaisesRegex(ValueError, "neither formal rollback nor verified layered runtime"):
            self.resolve("sha256:" + "7" * 64)

    def test_rejects_state_rollback_image_mismatch(self) -> None:
        self.write_state(device_agent_rollback_image_id="sha256:" + "7" * 64)
        with self.assertRaisesRegex(ValueError, "neither formal rollback nor verified layered runtime"):
            self.resolve()

    def test_rejects_runtime_safety_mismatch(self) -> None:
        self.write_runtime_evidence(modbus_write="present")
        with self.assertRaisesRegex(ValueError, "modbus_write"):
            self.resolve()

    def test_rejects_runtime_checksum_mismatch(self) -> None:
        (self.runtime_evidence / "final-runtime.txt").write_text("status=PASS\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.resolve()

    def test_rejects_pre_cutover_checksum_mismatch(self) -> None:
        (self.pre_cutover / "source-lineage.txt").write_text("status=PASS\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.resolve()

    def test_rejects_pre_cutover_lineage_mismatch(self) -> None:
        self.write_pre_cutover_evidence(formal_source="2" * 40)
        with self.assertRaisesRegex(ValueError, "formal_deployed_product_sha"):
            self.resolve()

    def test_rejects_pre_cutover_release_ci_failure(self) -> None:
        self.write_pre_cutover_evidence(release_ci="FAIL")
        with self.assertRaisesRegex(ValueError, "release_ci"):
            self.resolve()

    def test_rejects_pre_cutover_candidate_parent_mismatch(self) -> None:
        self.write_state(device_agent_compatibility_parent_sha="2" * 40)
        with self.assertRaisesRegex(ValueError, "candidate_parent_sha"):
            self.resolve()

    def test_absent_layered_baseline_allows_formal_runtime_only(self) -> None:
        project = self.repo / ".project"
        (project / "ACTIVE_SPRINT.json").write_text(
            json.dumps({"schema_version": 2, "baselines": {"deployed_product_sha": self.formal}}) + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(self.resolve())

    def test_rejects_partially_configured_layered_state(self) -> None:
        project = self.repo / ".project"
        (project / "ACTIVE_SPRINT.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "baselines": {
                        "deployed_product_sha": self.formal,
                        "device_agent_image_id": CURRENT_IMAGE,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "partially configured"):
            self.resolve()


if __name__ == "__main__":
    unittest.main()
