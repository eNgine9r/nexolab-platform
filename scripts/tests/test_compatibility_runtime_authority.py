from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "compatibility_runtime_authority.py"
SPEC = importlib.util.spec_from_file_location("compatibility_runtime_authority", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


class CompatibilityRuntimeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "test@nexolab.local")
        self._git("config", "user.name", "NEXOLAB Test")
        self._git("remote", "add", "origin", "git@github.com:eNgine9r/nexolab-platform.git")
        (self.repo / "fixture.txt").write_text("base\n")
        self._git("add", "fixture.txt")
        self._git("commit", "-m", "base")
        self.base = self._git("rev-parse", "HEAD")
        (self.repo / "fixture.txt").write_text("compatibility\n")
        self._git("commit", "-am", "compatibility")
        self.compatibility = self._git("rev-parse", "HEAD")

        self.da_image = "sha256:" + "a" * 64
        self.telemetry_image = "sha256:" + "b" * 64
        self.formal_image = "sha256:" + "c" * 64
        self.formal = self.repo / "runtime" / "deployments" / "20260904T000000Z"
        self.formal.mkdir(parents=True)
        (self.formal / "summary.txt").write_text("DEPLOYMENT PASSED\n")
        (self.formal / "final-state.txt").write_text(
            f"commit={self.base}\ndeployed_device_agent_image_id={self.formal_image}\n"
        )

        self.acceptance = self.repo / "runtime" / "evidence" / "issue-1044"
        self.acceptance.mkdir(parents=True)
        self.release = self.repo / "runtime" / "frontend-releases" / f"{self.compatibility}-release"
        (self.release / ".next").mkdir(parents=True)
        (self.release / ".next" / "BUILD_ID").write_text("build-1044\n")
        acceptance = {
            "schema_version": 1,
            "compatibility_source": self.compatibility,
            "base_deployed_source": self.base,
            "device_agent": {"candidate_image": self.da_image, "configured_logical_targets": 53},
            "telemetry_service": {"candidate_image": self.telemetry_image},
            "frontend": {"active_release": str(self.release), "build_id": "build-1044"},
            "invariants": {
                "modbus_writes": "none",
                "hardware_writes": "none",
                "production_akcc25_polling": "disabled",
            },
        }
        (self.acceptance / "acceptance.json").write_text(json.dumps(acceptance) + "\n")
        (self.acceptance / "proof.txt").write_text("accepted\n")
        rows = []
        for name in ("acceptance.json", "proof.txt"):
            digest = hashlib.sha256((self.acceptance / name).read_bytes()).hexdigest()
            rows.append(f"{digest}  {self.acceptance / name}")
        (self.acceptance / "SHA256SUMS").write_text("\n".join(rows) + "\n")

        self.rollback = self.repo / "runtime" / "evidence" / "issue-1050"
        self.rollback.mkdir(parents=True)
        (self.rollback / "rollback-authority.txt").write_text(
            f"approved_from={self.compatibility}\n"
            f"device_agent_image={self.da_image}\n"
            f"telemetry_image={self.telemetry_image}\n"
            f"frontend_release={self.release}\n"
            "frontend_build_id=build-1044\n"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, *args: str) -> str:
        import subprocess
        result = subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)
        return result.stdout.strip()

    def _context(self):
        def fake_unique(project: str, service: str) -> str:
            return "1" * 64 if service == "device-agent" else "2" * 64

        def fake_image(container: str) -> str:
            return self.da_image if container == "1" * 64 else self.telemetry_image

        def fake_http(url: str):
            if url == AUTH.DEVICE_AGENT_URL:
                return {
                    "status": "ok",
                    "mqtt_connected": True,
                    "queue_depth": 0,
                    "configured_logical_targets": 53,
                    "bus_workers": {"expected": 2, "active": 2},
                }
            return {"status": "ready"}

        def fake_published_url(_container: str, port: int, path: str) -> str:
            return AUTH.DEVICE_AGENT_URL if port == 8081 else f"http://telemetry.test:{port}{path}"

        with (
            mock.patch.object(AUTH, "unique_container", side_effect=fake_unique),
            mock.patch.object(AUTH, "container_image", side_effect=fake_image),
            mock.patch.object(AUTH, "published_http_url", side_effect=fake_published_url),
            mock.patch.object(AUTH, "http_json", side_effect=fake_http),
            mock.patch.object(AUTH, "dashboard_working_directory", return_value=self.release),
        ):
            return AUTH.build_context(
                self.repo,
                self.acceptance,
                self.rollback,
                self.compatibility,
                self.base,
            )

    def test_build_context_binds_live_runtime_to_checksumed_acceptance(self) -> None:
        context = self._context()
        self.assertEqual(context["device_agent_image_id"], self.da_image)
        self.assertEqual(context["telemetry_image_id"], self.telemetry_image)
        self.assertEqual(context["formal_base_source"], self.base)
        self.assertEqual(context["device_health"]["configured_logical_targets"], 53)

    def test_published_authority_revalidates_immutable_evidence_hashes(self) -> None:
        context = self._context()
        directory = self.repo / "runtime" / "deployments" / "20260916T120000Z"
        directory.mkdir()
        result = AUTH.make_result(context, directory.name)
        (directory / AUTH.RESULT_NAME).write_text(json.dumps(result) + "\n")
        loaded = AUTH.load_published_authority(self.repo, directory)
        self.assertEqual(loaded["compatibility_source"], self.compatibility)
        self.assertEqual(loaded["device_agent_image_id"], self.da_image)

    def test_tampered_acceptance_fails_closed_after_publication(self) -> None:
        context = self._context()
        directory = self.repo / "runtime" / "deployments" / "20260916T120000Z"
        directory.mkdir()
        result = AUTH.make_result(context, directory.name)
        (directory / AUTH.RESULT_NAME).write_text(json.dumps(result) + "\n")
        (self.acceptance / "proof.txt").write_text("tampered\n")
        with self.assertRaisesRegex(AUTH.AuthorityFailure, "checksum mismatch"):
            AUTH.load_published_authority(self.repo, directory)

    def test_wrong_live_device_agent_image_fails_closed(self) -> None:
        with (
            mock.patch.object(AUTH, "unique_container", side_effect=["1" * 64, "2" * 64]),
            mock.patch.object(AUTH, "container_image", side_effect=["sha256:" + "d" * 64, self.telemetry_image]),
        ):
            with self.assertRaisesRegex(AUTH.AuthorityFailure, "live container image"):
                AUTH.build_context(
                    self.repo,
                    self.acceptance,
                    self.rollback,
                    self.compatibility,
                    self.base,
                )

    def test_compatibility_source_must_be_direct_child_of_formal_base(self) -> None:
        (self.repo / "fixture.txt").write_text("later\n")
        self._git("commit", "-am", "later")
        later = self._git("rev-parse", "HEAD")
        with self.assertRaisesRegex(AUTH.AuthorityFailure, "sole parent"):
            AUTH.build_context(
                self.repo,
                self.acceptance,
                self.rollback,
                later,
                self.base,
            )


if __name__ == "__main__":
    unittest.main()
