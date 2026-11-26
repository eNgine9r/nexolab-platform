"""Guarded protected-HTTPS frontend release tool (P0 charts consolidated release).

The tool is owner-run with sudo on the Raspberry Pi. These tests exercise its gates with a
synthetic artifact, a temporary release directory and a fake host (systemd and HTTP stubs).
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "docs" / "operations" / "https-frontend-release" / "nexolab-https-frontend-release.py"

SOURCE = "a" * 40
BUILD = "Build_ID-123456"
OLD = ("b" * 40, "OldBuild-1234")


def load():
    spec = importlib.util.spec_from_file_location("https_release", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_artifact(path: Path, *, https: bool = True, tamper: bool = False, extra_member=None) -> str:
    files = {
        ".next/BUILD_ID": f"{BUILD}\n".encode(),
        ".next/server/app.js": b"server",
        "node_modules/next/dist/bin/next": b"#!/usr/bin/env node\n",
        "public/logo.svg": b"<svg/>",
    }
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith("/next") else 0o600
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("node_modules/.bin/next")
        link.type = tarfile.SYMTYPE
        link.linkname = "../next/dist/bin/next"
        tar.addfile(link)
        if extra_member is not None:
            tar.addfile(extra_member)
    runtime_hashes = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items())
    members = {
        "frontend-runtime.tar.gz": tar_bytes.getvalue(),
        "frontend-runtime-files-sha256.txt": runtime_hashes.encode(),
        "frontend-source-sha.txt": f"{SOURCE}\n".encode(),
        "frontend-build-id.txt": f"{BUILD}\n".encode(),
        "frontend-public-contract.txt": f"status=PASS\nbuild_id={BUILD}\n".encode(),
        "frontend-runtime-contract.txt": (
            "runtime_mode=live\n"
            f"api_base_url={'https://edge.example.test' if https else 'same-origin'}\n"
            "auth_provider=local\n"
            f"external_https_stage={'true' if https else 'false'}\n"
        ).encode(),
    }
    checksums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in members.items())
    if tamper:
        members["frontend-build-id.txt"] = b"changed\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        archive.writestr("frontend-artifact-sha256.txt", checksums)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeHost:
    """systemd user unit and HTTP endpoints of the live service."""

    def __init__(self, module, *, new_starts: bool = True, public_status: int = 302):
        self.module = module
        self.live = OLD
        self.new_starts = new_starts
        self.public_status = public_status
        self.dropin = None
        self.calls = []
        self.log_lines = []

    def run(self, argv):
        self.calls.append(argv)
        out = ""
        if argv[:4] == ["systemctl", "--user", "-M", "nexolab@"]:
            if argv[4] == "show":
                out = (
                    "WorkingDirectory=/opt/nexolab-external/releases/old-release\n"
                    "ExecStart={ path=/usr/bin/node ; argv[]=/usr/bin/node /opt/nexolab-external/releases/old-release/"
                    "node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3105 ; ignore_errors=no }\n"
                    "Environment=NODE_ENV=production NEXOLAB_RUNTIME_IDENTITY_FILE=/old/identity.json\n"
                    f"DropInPaths=/home/nexolab/a.conf {self.dropin or ''}\n"
                )
            if argv[4] == "restart":
                exists = self.dropin is not None and Path(self.dropin).exists()
                self.live = (SOURCE, BUILD) if exists and self.new_starts else OLD if not exists else (None, None)
        return mock.Mock(returncode=0, stdout=out, stderr="")

    def http_get(self, url, timeout):
        if url.endswith("/api/runtime-identity"):
            source, build = self.live
            return (200, json.dumps({"source_commit": source, "build_id": build})) if source else (502, "")
        if url.startswith("https://"):
            return self.public_status, ""
        return 200, ""

    def as_host(self):
        clock = {"t": 0.0}

        def sleep(seconds):
            clock["t"] += seconds

        return self.module.Host(
            run=self.run,
            http_get=self.http_get,
            free_bytes=lambda path: 40 * 1024**3,
            sleep=sleep,
            now=lambda: clock["t"],
            log=self.log_lines.append,
        )


class ArtifactVerification(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.dir = tempfile.TemporaryDirectory()
        self.zip = Path(self.dir.name) / "artifact.zip"

    def tearDown(self):
        self.dir.cleanup()

    def test_accepts_the_exact_protected_https_artifact(self):
        digest = build_artifact(self.zip)
        contract = self.module.verify_artifact(self.zip, self.module.Expectation(digest, SOURCE, BUILD))
        self.assertEqual(contract["runtime.external_https_stage"], "true")

    def test_refuses_wrong_digest_lan_build_and_tampered_members(self):
        digest = build_artifact(self.zip)
        with self.assertRaisesRegex(self.module.ReleaseError, "ZIP SHA-256"):
            self.module.verify_artifact(self.zip, self.module.Expectation("0" * 64, SOURCE, BUILD))
        digest = build_artifact(self.zip, https=False)
        with self.assertRaisesRegex(self.module.ReleaseError, "external_https_stage"):
            self.module.verify_artifact(self.zip, self.module.Expectation(digest, SOURCE, BUILD))
        digest = build_artifact(self.zip, tamper=True)
        with self.assertRaisesRegex(self.module.ReleaseError, "internal checksum"):
            self.module.verify_artifact(self.zip, self.module.Expectation(digest, SOURCE, BUILD))

    def test_member_safety(self):
        def member(name, link=None):
            info = tarfile.TarInfo(name)
            if link is not None:
                info.type = tarfile.SYMTYPE
                info.linkname = link
            return info

        self.assertTrue(self.module.safe_member(member("node_modules/.bin/next", "../next/dist/bin/next")))
        self.assertFalse(self.module.safe_member(member("/etc/passwd")))
        self.assertFalse(self.module.safe_member(member("a/../../escape")))
        self.assertFalse(self.module.safe_member(member("a/link", "../../outside")))
        self.assertFalse(self.module.safe_member(member("a/link", "/etc/shadow")))


class ExtractionAndUnit(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.dir = tempfile.TemporaryDirectory()
        self.releases = Path(self.dir.name) / "releases"
        self.releases.mkdir()
        self.zip = Path(self.dir.name) / "artifact.zip"
        self.digest = build_artifact(self.zip)
        self.module.RELEASES_DIR = self.releases

    def tearDown(self):
        self.dir.cleanup()

    def test_extracts_verified_files_readable_by_the_service_and_never_overwrites(self):
        host = FakeHost(self.module).as_host()
        release = self.module.release_directory(SOURCE, BUILD)
        self.module.extract_runtime(self.zip, release, host)
        self.assertEqual((release / ".next" / "BUILD_ID").read_text().strip(), BUILD)
        self.assertEqual(os.stat(release / "public" / "logo.svg").st_mode & 0o777, 0o644)
        self.assertEqual(os.stat(release / "node_modules/next/dist/bin/next").st_mode & 0o777, 0o755)
        self.assertTrue((release / "node_modules" / ".bin" / "next").is_symlink())
        identity = self.module.write_identity(release, SOURCE, BUILD)
        self.assertEqual(json.loads(identity.read_text())["identity_source"], "offline_image_manifest")
        with self.assertRaisesRegex(self.module.ReleaseError, "never overwritten"):
            self.module.extract_runtime(self.zip, release, host)

    def test_existing_release_is_verified_file_by_file(self):
        host = FakeHost(self.module).as_host()
        release = self.module.release_directory(SOURCE, BUILD)
        self.module.extract_runtime(self.zip, release, host)
        self.assertGreater(self.module.verify_release_files(self.zip, release), 0)
        (release / ".next" / "server" / "app.js").write_bytes(b"modified")
        with self.assertRaisesRegex(self.module.ReleaseError, "does not match the artifact"):
            self.module.verify_release_files(self.zip, release)

    def test_refuses_extraction_below_the_protected_free_space(self):
        host = FakeHost(self.module).as_host()
        host.free_bytes = lambda path: 20 * 1024**3 + 10
        with self.assertRaisesRegex(self.module.ReleaseError, "20 GiB"):
            self.module.extract_runtime(self.zip, self.module.release_directory(SOURCE, BUILD), host)
        self.assertEqual(list(self.releases.iterdir()), [])

    def test_renders_a_dropin_that_only_moves_the_release_and_keeps_the_port(self):
        argv = self.module.execstart_argv(
            "{ path=/n ; argv[]=/n /opt/r/old/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3105 ; x=y }"
        )
        dropin = self.module.render_dropin(argv, "/opt/r/old", Path("/opt/r/new"), 3105)
        self.assertIn("WorkingDirectory=/opt/r/new\n", dropin)
        self.assertIn("ExecStart=\nExecStart=/n /opt/r/new/node_modules/next/dist/bin/next start", dropin)
        self.assertIn("--port 3105", dropin)
        self.assertIn("NEXOLAB_RUNTIME_IDENTITY_FILE=/opt/r/new/.nexolab-runtime-identity.json", dropin)
        self.assertTrue(self.module.DROPIN_PREFIX > "99-release-")


class Execute(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.module.RELEASES_DIR = base / "releases"
        self.module.RELEASES_DIR.mkdir()
        self.module.STATE_DIR = base / "state"
        self.zip = base / "artifact.zip"
        self.digest = build_artifact(self.zip)
        self.dropin = base / "home" / "unit.d" / "999-https-release-aaaaaaaaaaaa.conf"
        self.patches = [
            mock.patch.object(self.module, "dropin_path", lambda source: self.dropin),
            mock.patch.object(self.module.os, "chown", lambda *args: None),
            mock.patch.object(
                self.module.pwd, "getpwnam", lambda name: mock.Mock(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(base / "home"))
            ),
        ]
        for patch in self.patches:
            patch.start()
        release = self.module.release_directory(SOURCE, BUILD)
        self.module.extract_runtime(self.zip, release, FakeHost(self.module).as_host())
        (release / ".nexolab-https-prepared").write_text(f"{self.digest}\n")

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def expectation(self):
        return self.module.Expectation(self.digest, SOURCE, BUILD)

    def test_switches_and_verifies_identity_routes_and_oauth_gate(self):
        fake = FakeHost(self.module)
        fake.dropin = str(self.dropin)
        self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        self.assertEqual(fake.live, (SOURCE, BUILD))
        self.assertTrue(self.dropin.is_file())
        self.assertTrue(any(line.startswith("HTTPS_FRONTEND_GREEN") for line in fake.log_lines))
        state = json.loads((self.module.STATE_DIR / "state.json").read_text())
        self.assertEqual(state["previous"], list(OLD))

    def test_failed_start_rolls_back_and_verifies_the_previous_identity(self):
        fake = FakeHost(self.module, new_starts=False)
        fake.dropin = str(self.dropin)
        with self.assertRaises(self.module.ReleaseError):
            self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        self.assertFalse(self.dropin.exists())
        self.assertEqual(fake.live, OLD)
        self.assertIn("HTTPS_FRONTEND_ROLLED_BACK_VERIFIED", fake.log_lines)

    def test_open_public_gate_is_a_failure_and_rolls_back(self):
        fake = FakeHost(self.module, public_status=200)
        fake.dropin = str(self.dropin)
        with self.assertRaisesRegex(self.module.ReleaseError, "OAuth"):
            self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        self.assertEqual(fake.live, OLD)

    def test_unexpected_live_identity_changes_nothing(self):
        fake = FakeHost(self.module)
        fake.live = ("c" * 40, "Other-12345")
        with self.assertRaisesRegex(self.module.ReleaseError, "nothing changed"):
            self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        self.assertFalse(self.dropin.exists())
        self.assertFalse(any("restart" in call for call in fake.calls))

    def test_refuses_a_second_execute_over_an_installed_dropin(self):
        fake = FakeHost(self.module)
        fake.dropin = str(self.dropin)
        self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        installed = self.dropin.read_text()
        restarts = sum(1 for call in fake.calls if "restart" in call)
        with self.assertRaisesRegex(self.module.ReleaseError, "already installed"):
            self.module.phase_execute(self.zip, self.expectation(), (SOURCE, BUILD), fake.as_host())
        self.assertEqual(self.dropin.read_text(), installed)
        self.assertEqual(sum(1 for call in fake.calls if "restart" in call), restarts)
        self.assertTrue(self.module.phase_rollback(fake.as_host()))
        self.assertEqual(fake.live, OLD)

    def test_a_systemctl_timeout_during_activation_rolls_back(self):
        fake = FakeHost(self.module)
        fake.dropin = str(self.dropin)
        original = fake.run

        def run(argv):
            if "restart" in argv and Path(self.dropin).exists():
                raise self.module.subprocess.TimeoutExpired(argv, 180)
            return original(argv)

        host = fake.as_host()
        host.run = run
        with self.assertRaisesRegex(self.module.ReleaseError, "activation failed"):
            self.module.phase_execute(self.zip, self.expectation(), OLD, host)
        self.assertFalse(self.dropin.exists())
        self.assertEqual(fake.live, OLD)
        self.assertIn("HTTPS_FRONTEND_ROLLED_BACK_VERIFIED", fake.log_lines)
        # A failed attempt never becomes the recorded installed release.
        self.assertFalse((self.module.STATE_DIR / "state.json").exists())

    def test_a_failed_state_write_rolls_back_instead_of_stranding_the_release(self):
        fake = FakeHost(self.module)
        fake.dropin = str(self.dropin)
        with mock.patch.object(self.module, "write_state", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(self.module.ReleaseError, "activation failed"):
                self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        self.assertFalse(self.dropin.exists())
        self.assertEqual(fake.live, OLD)
        self.assertIn("HTTPS_FRONTEND_ROLLED_BACK_VERIFIED", fake.log_lines)

    def test_refuses_another_release_while_one_is_installed(self):
        fake = FakeHost(self.module)
        fake.dropin = str(self.dropin)
        self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        other = self.dropin.with_name("999-https-release-cccccccccccc.conf")
        with mock.patch.object(self.module, "dropin_path", lambda source: other):
            with self.assertRaisesRegex(self.module.ReleaseError, "already installed"):
                self.module.phase_execute(self.zip, self.expectation(), (SOURCE, BUILD), fake.as_host())
        self.assertFalse(other.exists())
        state = json.loads((self.module.STATE_DIR / "state.json").read_text())
        self.assertEqual(state["dropin"], str(self.dropin))

    def test_rollback_command_uses_the_recorded_state(self):
        fake = FakeHost(self.module)
        fake.dropin = str(self.dropin)
        self.module.phase_execute(self.zip, self.expectation(), OLD, fake.as_host())
        self.assertTrue(self.module.phase_rollback(fake.as_host()))
        self.assertEqual(fake.live, OLD)


if __name__ == "__main__":
    unittest.main()
