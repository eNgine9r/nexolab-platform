from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-adopt-source-deployment.py"
SPEC = importlib.util.spec_from_file_location("nexolab_adopter_forward_recovery", SCRIPT)
assert SPEC and SPEC.loader
adopter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adopter)

PRIOR = "a" * 40
TARGET = "b" * 40
IMAGE = "sha256:" + "c" * 64


class ForwardRecoveryAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.deployments = self.repo / "runtime" / "deployments"
        prior = self.deployments / "20260901T000000Z"
        prior.mkdir(parents=True)
        (prior / "summary.txt").write_text("DEPLOYMENT PASSED\n", encoding="utf-8")
        (prior / "final-state.txt").write_text(f"commit={PRIOR}\n", encoding="utf-8")
        self.forward = self.deployments / "20260901T010000Z"
        self.forward.mkdir()
        (self.forward / "summary.txt").write_text(
            "RUNTIME MUTATION STARTED: central backend activation\n",
            encoding="utf-8",
        )
        (self.forward / "runtime-mutation-started").write_text("started\n", encoding="utf-8")
        (self.forward / "forward-recovery-result.json").write_text("{}\n", encoding="utf-8")
        self.original = adopter.forward_recovery.load_published_authority
        adopter.forward_recovery.load_published_authority = lambda repo, evidence: {
            "previous_source": PRIOR,
            "target_source": TARGET,
            "runtime_activated_at": "2026-09-01T01:00:00Z",
            "runtime_mode": "lan",
            "dashboard": "http://172.18.48.66:3000",
            "api": "http://172.18.48.66:8082",
            "auth_mode": "jwt",
            "local_auth_overlay": True,
            "dashboard_auth_provider": "local",
            "control_origin_main": TARGET,
            "device_agent_image_id": IMAGE,
        }

    def tearDown(self) -> None:
        adopter.forward_recovery.load_published_authority = self.original
        self.temp.cleanup()

    def test_forward_record_becomes_latest_authority(self) -> None:
        directory, source = adopter.authoritative_source_deployment(self.repo)
        self.assertEqual(directory, self.forward.resolve())
        self.assertEqual(source, TARGET)

    def test_forward_record_synthesizes_adoption_facts(self) -> None:
        directory, facts = adopter.deployment_evidence(self.repo, self.forward)
        self.assertEqual(directory, self.forward.resolve())
        self.assertEqual(facts["commit"], TARGET)
        self.assertEqual(facts["expected_deployed_source"], PRIOR)
        self.assertEqual(facts["requested_source_ref"], TARGET)
        self.assertEqual(facts["local_auth_overlay"], "true")

    def test_later_unresolved_mutation_blocks_forward_authority(self) -> None:
        later = self.deployments / "20260901T020000Z"
        later.mkdir()
        (later / "summary.txt").write_text(
            "RUNTIME MUTATION STARTED: central backend activation\n",
            encoding="utf-8",
        )
        (later / "runtime-mutation-started").write_text("started\n", encoding="utf-8")
        with self.assertRaisesRegex(
            adopter.AdoptionFailure,
            "newer deployment attempt crossed runtime mutation boundary",
        ):
            adopter.authoritative_source_deployment(self.repo)


if __name__ == "__main__":
    unittest.main()
