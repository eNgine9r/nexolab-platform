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


def build_artifact(
    path: Path, *, https: bool = True, tamper: bool = False, extra_member=None, source: str = SOURCE, build: str = BUILD
) -> str:
    files = {
        ".next/BUILD_ID": f"{build}\n".encode(),
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
        "frontend-source-sha.txt": f"{source}\n".encode(),
        "frontend-build-id.txt": f"{build}\n".encode(),
        "frontend-public-contract.txt": f"status=PASS\nbuild_id={build}\n".encode(),
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


C_SOURCE = "0" * 40  # sorts BEFORE "a…" and "b…": adverse lexical order for hash-named drop-ins
C_BUILD = "Build_C-123456"
BASE_RELEASE = "/opt/nexolab-external/releases/old-release"


class FakeSystemd:
    """The user unit as systemd sees it: drop-ins applied in lexical order, the last one wins, and
    DropInPaths/effective values change only on daemon-reload. The live identity is the identity
    file of the effective WorkingDirectory release (OLD for the base unit)."""

    def __init__(self, module, unit_dir: Path):
        self.module = module
        self.unit_dir = unit_dir
        self.loaded: list[Path] = []
        self.live = OLD
        self.fail_start: set[str] = set()
        self.public_status = 302
        self.calls: list[list[str]] = []
        self.log_lines: list[str] = []
        self.restart_hook = None

    def effective(self):
        working, execstart = BASE_RELEASE, (
            f"/usr/bin/node {BASE_RELEASE}/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3105"
        )
        for path in self.loaded:
            for line in path.read_text().splitlines():
                if line.startswith("WorkingDirectory="):
                    working = line.split("=", 1)[1]
                elif line.startswith("ExecStart=") and line != "ExecStart=":
                    execstart = line.split("=", 1)[1]
        return working, execstart

    def run(self, argv):
        self.calls.append(argv)
        out = ""
        if argv[:4] == ["systemctl", "--user", "-M", "nexolab@"]:
            command = argv[4]
            if command == "daemon-reload":
                self.loaded = sorted(self.unit_dir.glob("*.conf")) if self.unit_dir.is_dir() else []
            elif command == "show":
                working, execstart = self.effective()
                paths = " ".join(map(str, self.loaded))
                out = (
                    f"WorkingDirectory={working}\n"
                    f"ExecStart={{ path=/usr/bin/node ; argv[]={execstart} ; ignore_errors=no }}\n"
                    "Environment=NODE_ENV=production\n"
                    f"DropInPaths={paths}\n"
                )
            elif command == "restart":
                if self.restart_hook:
                    self.restart_hook()
                working, _ = self.effective()
                if working == BASE_RELEASE:
                    self.live = OLD
                else:
                    identity = json.loads((Path(working) / ".nexolab-runtime-identity.json").read_text())
                    source, build = identity["source_commit"], identity["build_id"]
                    self.live = (None, None) if source in self.fail_start else (source, build)
        return mock.Mock(returncode=0, stdout=out, stderr="")

    def http_get(self, url, timeout):
        if url.endswith("/api/runtime-identity"):
            source, build = self.live
            return (200, json.dumps({"source_commit": source, "build_id": build})) if source else (502, "")
        if url.startswith("https://"):
            return self.public_status, ""
        return 200, ""

    def host(self, free=40 * 1024**3):
        clock = {"t": 0.0}

        def sleep(seconds):
            clock["t"] += seconds

        return self.module.Host(
            run=self.run,
            http_get=self.http_get,
            free_bytes=lambda path: free,
            sleep=sleep,
            now=lambda: clock["t"],
            log=self.log_lines.append,
        )


class ConsecutiveReleases(unittest.TestCase):
    """#1863: guarded A -> B -> C upgrades with rollback to the immediate predecessor."""

    def setUp(self):
        self.module = load()
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.home = base / "home"
        self.unit_dir = self.home / ".config" / "systemd" / "user" / f"{self.module.UNIT}.d"
        self.unit_dir.mkdir(parents=True)  # the user unit's drop-in directory exists on the host
        # A historic, unrelated release drop-in sorted with the others (as on the host).
        (self.unit_dir / "99-release-old.conf").write_text("# historic drop-in\n[Service]\n")
        self.module.RELEASES_DIR = base / "releases"
        self.module.RELEASES_DIR.mkdir()
        self.module.STATE_DIR = base / "state"
        self.patches = [
            mock.patch.object(self.module.os, "chown", lambda *args: None),
            mock.patch.object(
                self.module.pwd,
                "getpwnam",
                lambda name: mock.Mock(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(self.home)),
            ),
        ]
        for patch in self.patches:
            patch.start()
        self.systemd = FakeSystemd(self.module, self.unit_dir)
        self.b = self.prepare(base / "b.zip", SOURCE, BUILD)
        self.c = self.prepare(base / "c.zip", C_SOURCE, C_BUILD)

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def prepare(self, zip_path, source, build):
        digest = build_artifact(zip_path, source=source, build=build)
        release = self.module.release_directory(source, build)
        self.module.extract_runtime(zip_path, release, self.systemd.host())
        self.module.write_identity(release, source, build)
        (release / ".nexolab-https-prepared").write_text(f"{digest}\n")
        return zip_path, self.module.Expectation(digest, source, build)

    def execute(self, release, current, **host):
        zip_path, expected = release
        return self.module.phase_execute(zip_path, expected, current, self.systemd.host(**host))

    def state(self):
        return json.loads((self.module.STATE_DIR / "state.json").read_text())

    def managed(self):
        return sorted(path.name for path in self.unit_dir.glob("999-https-release*.conf"))

    def test_a_to_b_to_c_and_rollback_to_each_immediate_predecessor(self):
        self.execute(self.b, OLD)
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))
        self.assertEqual(self.managed(), ["999-https-release.conf"])
        self.assertEqual([(e["source"], e["build"]) for e in self.state()["stack"]], [OLD, (SOURCE, BUILD), (C_SOURCE, C_BUILD)])
        # C -> B (not to the base A), then B -> A.
        self.assertTrue(self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD)))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertTrue(self.module.phase_rollback(self.systemd.host()))
        self.assertEqual(self.systemd.live, OLD)
        self.assertEqual(self.managed(), [])
        with self.assertRaisesRegex(self.module.ReleaseError, "no recorded predecessor"):
            self.module.phase_rollback(self.systemd.host())

    def test_upgrades_over_a_v1_hash_named_dropin_with_adverse_lexical_order(self):
        # Production on 2026-11-27: v1 left 999-https-release-<b12>.conf and a v1 state.
        legacy = self.unit_dir / f"999-https-release-{SOURCE[:12]}.conf"
        release_b = self.module.release_directory(SOURCE, BUILD)
        working, execstart = self.systemd.effective()
        legacy.write_text(self.module.render_dropin(execstart.split(), working, release_b, 3105))
        legacy_bytes = legacy.read_text()
        self.module.STATE_DIR.mkdir()
        (self.module.STATE_DIR / "state.json").write_text(
            json.dumps({"dropin": str(legacy), "previous": list(OLD), "release": str(release_b), "target": [SOURCE, BUILD]})
        )
        self.systemd.run(["systemctl", "--user", "-M", "nexolab@", "daemon-reload"])
        self.systemd.run(["systemctl", "--user", "-M", "nexolab@", "restart", self.module.UNIT])
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        # The read-only plan reports the migrated stack and changes nothing.
        before = sorted(path.name for path in self.unit_dir.iterdir())
        self.module.phase_plan(self.c[0], self.c[1], self.systemd.host())
        stack_line = next(line for line in self.systemd.log_lines if line.startswith("HTTPS_FRONTEND_STACK"))
        self.assertIn(f"{OLD[0][:12]}/{OLD[1]} -> {SOURCE[:12]}/{BUILD}", stack_line)
        self.assertEqual(sorted(path.name for path in self.unit_dir.iterdir()), before)
        # C's hash ("000…") sorts before B's: a hash-named C drop-in would LOSE to B's. The fixed name
        # replaces B's file instead, so C is effective.
        self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))
        self.assertEqual(self.managed(), ["999-https-release.conf"])
        # Rollback restores B's v1 drop-in byte for byte, at its own path.
        self.assertTrue(self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD)))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertEqual(legacy.read_text(), legacy_bytes)
        self.assertEqual(self.managed(), [legacy.name])

    def test_failed_start_of_c_restores_b_exactly_and_keeps_the_stack(self):
        self.execute(self.b, OLD)
        before_bytes = (self.unit_dir / "999-https-release.conf").read_text()
        before_state = self.state()
        self.systemd.fail_start.add(C_SOURCE)
        with self.assertRaises(self.module.ReleaseError):
            self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertEqual((self.unit_dir / "999-https-release.conf").read_text(), before_bytes)
        self.assertEqual(self.state(), before_state)
        self.assertFalse(self.module.transition_file().exists())
        self.assertTrue(any("ROLLED_BACK_VERIFIED" in line for line in self.systemd.log_lines))

    def test_open_public_gate_and_failed_state_write_restore_the_predecessor(self):
        self.execute(self.b, OLD)
        self.systemd.public_status = 200
        with self.assertRaisesRegex(self.module.ReleaseError, "OAuth"):
            self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        # The restore cannot repair an OAuth outage; it is named instead of hidden.
        self.assertTrue(any("OAUTH_GATE_NOT_VERIFIED" in line for line in self.systemd.log_lines))
        self.systemd.public_status = 302
        with mock.patch.object(self.module, "write_state", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(self.module.ReleaseError, "activation failed"):
                self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertEqual(len(self.state()["stack"]), 2)

    def test_interrupted_switch_is_recovered_and_blocks_other_operations(self):
        self.execute(self.b, OLD)

        def power_loss():
            raise KeyboardInterrupt  # not caught by the tool: the process dies mid-switch

        self.systemd.restart_hook = power_loss
        with self.assertRaises(KeyboardInterrupt):
            self.execute(self.c, (SOURCE, BUILD))
        self.systemd.restart_hook = None
        self.assertTrue(self.module.transition_file().exists())
        with self.assertRaisesRegex(self.module.ReleaseError, "run `recover`"):
            self.execute(self.c, (SOURCE, BUILD))
        with self.assertRaisesRegex(self.module.ReleaseError, "run `recover`"):
            self.module.phase_rollback(self.systemd.host())
        self.assertTrue(self.module.phase_recover(self.systemd.host()))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertFalse(self.module.transition_file().exists())
        self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))

    def crash_after_state_write(self):
        """Power loss after the stack was written but before transition.json was removed."""
        real = self.module.write_state

        def write_then_die(state):
            real(state)
            raise KeyboardInterrupt

        with mock.patch.object(self.module, "write_state", write_then_die):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(self.c, (SOURCE, BUILD))
        self.assertTrue(self.module.transition_file().exists())

    def test_recover_confirms_a_switch_that_completed_before_the_interruption(self):
        self.execute(self.b, OLD)
        self.crash_after_state_write()
        self.assertTrue(self.module.phase_recover(self.systemd.host()))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))
        self.assertFalse(self.module.transition_file().exists())
        self.assertEqual(len(self.state()["stack"]), 3)

    def test_recover_restores_the_stack_when_the_new_release_is_not_up_after_reboot(self):
        # Review P1-2: the stack said C, but after the reboot C does not start.
        self.execute(self.b, OLD)
        self.crash_after_state_write()
        self.systemd.fail_start.add(C_SOURCE)
        self.systemd.run(["systemctl", "--user", "-M", "nexolab@", "restart", self.module.UNIT])
        self.assertEqual(self.systemd.live, (None, None))
        self.assertTrue(self.module.phase_recover(self.systemd.host()))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertEqual([(e["source"], e["build"]) for e in self.state()["stack"]], [OLD, (SOURCE, BUILD)])
        self.assertFalse(self.module.transition_file().exists())
        # Consistent again: the next upgrade works.
        self.systemd.fail_start.clear()
        self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))

    def test_interrupted_rollback_is_recovered_to_the_release_it_started_from(self):
        self.execute(self.b, OLD)
        self.execute(self.c, (SOURCE, BUILD))

        def power_loss():
            raise KeyboardInterrupt

        self.systemd.restart_hook = power_loss
        with self.assertRaises(KeyboardInterrupt):
            self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD))
        self.systemd.restart_hook = None
        self.assertTrue(self.module.phase_recover(self.systemd.host()))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))
        self.assertEqual(len(self.state()["stack"]), 3)
        self.assertTrue(self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD)))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))

    def test_nothing_to_recover_has_its_own_marker(self):
        self.assertTrue(self.module.phase_recover(self.systemd.host()))
        self.assertIn("HTTPS_FRONTEND_NOTHING_TO_RECOVER", self.systemd.log_lines)

    def test_a_later_unmanaged_dropin_is_refused_before_any_change(self):
        # Review P1-3: e.g. `systemctl edit` writes override.conf, which sorts after 999-*.
        self.execute(self.b, OLD)
        (self.unit_dir / "override.conf").write_text("[Service]\nEnvironment=X=1\n")
        self.systemd.run(["systemctl", "--user", "-M", "nexolab@", "daemon-reload"])
        restarts = sum(1 for call in self.systemd.calls if "restart" in call)
        with self.assertRaisesRegex(self.module.ReleaseError, "does not apply .* last.*nothing changed"):
            self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(sum(1 for call in self.systemd.calls if "restart" in call), restarts)
        self.assertFalse(self.module.transition_file().exists())
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))

    def test_dropins_are_root_owned_and_symlinks_are_refused(self):
        with mock.patch.object(self.module.os, "chown") as chown:
            self.execute(self.b, OLD)
        # Review P1-1: nothing under the service account's home is chowned to it.
        self.assertFalse(any(str(self.home) in str(call.args[0]) for call in chown.call_args_list))
        self.assertEqual((self.unit_dir / "999-https-release.conf").stat().st_mode & 0o777, 0o644)
        target = Path(self.dir.name) / "elsewhere"
        target.mkdir()
        moved = self.unit_dir.with_name("moved.d")
        self.unit_dir.rename(moved)
        self.unit_dir.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(self.module.ReleaseError, "not a plain directory"):
            self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(list(target.iterdir()), [])

    def test_a_fifo_or_directory_in_place_of_the_dropin_is_refused_without_hanging(self):
        self.execute(self.b, OLD)
        managed = self.unit_dir / "999-https-release.conf"
        managed.unlink()
        os.mkfifo(managed)
        with self.assertRaisesRegex(self.module.ReleaseError, "not a regular file"):
            self.execute(self.c, (SOURCE, BUILD))
        managed.unlink()
        managed.mkdir()
        with self.assertRaisesRegex(self.module.ReleaseError, "not a regular file|cannot read"):
            self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))

    def test_rollback_works_during_an_oauth_outage_and_says_so(self):
        self.execute(self.b, OLD)
        self.execute(self.c, (SOURCE, BUILD))
        self.systemd.public_status = 502
        self.assertTrue(self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD)))
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        self.assertTrue(any("OAUTH_GATE_NOT_VERIFIED" in line for line in self.systemd.log_lines))

    def test_a_tampered_lower_stack_entry_is_refused(self):
        self.execute(self.b, OLD)
        self.execute(self.c, (SOURCE, BUILD))
        state = self.state()
        state["stack"][1]["dropin_text"] += "ExecStartPre=/bin/sh -c id\n"
        (self.module.STATE_DIR / "state.json").write_text(json.dumps(state))
        with self.assertRaisesRegex(self.module.ReleaseError, "does not match its hash"):
            self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD))
        state["stack"][1]["dropin"] = "/etc/systemd/system/evil.conf"
        state["stack"][1]["dropin_sha256"] = self.module.text_sha256(state["stack"][1]["dropin_text"])
        (self.module.STATE_DIR / "state.json").write_text(json.dumps(state))
        with self.assertRaisesRegex(self.module.ReleaseError, "not a managed drop-in"):
            self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))

    def test_refuses_unexpected_tampered_or_unrecorded_state(self):
        # Unrecorded managed drop-in, no state.
        stray = self.unit_dir / "999-https-release-ffffffffffff.conf"
        stray.write_text("[Service]\n")
        with self.assertRaisesRegex(self.module.ReleaseError, "unrecorded managed drop-in"):
            self.execute(self.b, OLD)
        stray.unlink()
        self.execute(self.b, OLD)
        # Tampered managed drop-in.
        managed = self.unit_dir / "999-https-release.conf"
        original = managed.read_text()
        managed.write_text(original + "# edited\n")
        with self.assertRaisesRegex(self.module.ReleaseError, "modified outside this tool"):
            self.execute(self.c, (SOURCE, BUILD))
        managed.write_text(original)
        # An extra managed drop-in next to the recorded one.
        stray.write_text("[Service]\n")
        with self.assertRaisesRegex(self.module.ReleaseError, "managed drop-ins"):
            self.execute(self.c, (SOURCE, BUILD))
        stray.unlink()
        # Wrong expected current identity: nothing changes, no restart.
        restarts = sum(1 for call in self.systemd.calls if "restart" in call)
        with self.assertRaisesRegex(self.module.ReleaseError, "nothing changed"):
            self.execute(self.c, OLD)
        with self.assertRaisesRegex(self.module.ReleaseError, "nothing changed"):
            self.module.phase_rollback(self.systemd.host(), (C_SOURCE, C_BUILD))
        self.assertEqual(sum(1 for call in self.systemd.calls if "restart" in call), restarts)
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))

    def test_disk_reserve_tampered_artifact_and_concurrency_are_refused(self):
        with self.assertRaisesRegex(self.module.ReleaseError, "20 GiB"):
            self.execute(self.b, OLD, free=10 * 1024**3)
        zip_path, expected = self.b
        with self.assertRaises(self.module.ReleaseError):
            self.module.phase_execute(
                zip_path, self.module.Expectation("0" * 64, expected.source, expected.build), OLD, self.systemd.host()
            )
        release = self.module.release_directory(SOURCE, BUILD)
        app = release / ".next" / "server" / "app.js"
        app.write_bytes(b"modified")
        with self.assertRaisesRegex(self.module.ReleaseError, "does not match the artifact"):
            self.execute(self.b, OLD)
        app.write_bytes(b"server")
        with self.module.StateLock():
            with self.assertRaisesRegex(self.module.ReleaseError, "another release operation"):
                self.execute(self.b, OLD)
        self.assertEqual(self.managed(), [])
        self.assertFalse(any("restart" in call for call in self.systemd.calls))

    def test_a_systemctl_timeout_restores_and_the_v1_refusal_is_gone(self):
        self.execute(self.b, OLD)
        original = self.systemd.run

        def run(argv):
            if "restart" in argv and C_SOURCE[:12] in self.systemd.effective()[0]:
                raise self.module.subprocess.TimeoutExpired(argv, 180)
            return original(argv)

        host = self.systemd.host()
        host.run = run
        with self.assertRaisesRegex(self.module.ReleaseError, "activation failed"):
            self.module.phase_execute(self.c[0], self.c[1], (SOURCE, BUILD), host)
        self.assertEqual(self.systemd.live, (SOURCE, BUILD))
        # The 2026-11-27 refusal ("already installed; run rollback first") no longer happens.
        self.execute(self.c, (SOURCE, BUILD))
        self.assertEqual(self.systemd.live, (C_SOURCE, C_BUILD))


if __name__ == "__main__":
    unittest.main()
