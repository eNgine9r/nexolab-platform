"""#1630 object-metadata fix: user.* extended attributes through backup and restore.

VersityGW's posix backend keeps object metadata (ETag, Content-Type, checksums, bucket ACL)
in ``user.*`` extended attributes. These tests prove, with synthetic files in temporary
directories (no Docker, no production), that the leaf-A directory snapshot and
``nexolab-volume-archive.py`` capture and re-apply them, that only the ``user.`` namespace
is ever touched, that size caps fail closed, that a destination without xattr support never
silently succeeds, that archives written before the fix still extract exactly as before,
that path/symlink protections are unchanged, and that the isolated restore reports
``metadata_fidelity`` OK only for a faithful restore.

Tests that need real xattrs skip on file systems/platforms without ``user.*`` support
(Linux CI runners have it). unittest style so Core CI ``unittest discover -p 'test_ci_*.py'``
runs it.
"""
from __future__ import annotations

import errno
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bk = _load("nexolab_dr_scheduled_backup_xattrs", "nexolab-dr-scheduled-backup.py")
vat = bk.vat
drs = bk.drs
ir = _load("nexolab_dr_isolated_restore_xattrs", "nexolab-dr-isolated-restore.py")

KEY = bytes(range(32))
COMMIT = "e" * 40
GiB = 1024**3
ETAG = b'"5d41402abc4b2a76b9719d911017c592"'
BINARY = b"\x00\xff\n=bin\xfe\x00"
SECRET_VALUE = b"user-metadata-marker-must-not-leak"


def xattrs_supported(directory: Path) -> bool:
    if not hasattr(os, "setxattr"):
        return False
    probe = directory / ".xattr-probe"
    probe.write_bytes(b"")
    try:
        os.setxattr(probe, "user.nexolab-probe", b"1")
        return os.getxattr(probe, "user.nexolab-probe") == b"1"
    except OSError:
        return False
    finally:
        probe.unlink()


def no_ownership(path: Path, member: tarfile.TarInfo) -> None:
    os.chmod(path, member.mode & 0o777)


class TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Extraction as a non-root user cannot chown; ownership itself is covered elsewhere.
        patches = [mock.patch.object(vat, "apply_ownership", no_ownership),
                   mock.patch.object(vat, "apply_root_metadata", lambda destination, metadata: None)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def require_xattrs(self) -> None:
        if not xattrs_supported(self.tmp):
            self.skipTest("file system/platform without user.* xattr support")

    def object_tree(self) -> Path:
        """A VersityGW-like tree: bucket directory with ACL/ownership xattrs, objects with metadata."""
        root = self.tmp / "objects"
        bucket = root / "nexolab-equipment-images"
        (bucket / "equipment" / "SIM-01").mkdir(parents=True)
        (root / ".vgwlocks").mkdir()
        image = bucket / "equipment" / "SIM-01" / "a.png"
        image.write_bytes(b"\x89PNG synthetic")
        plain = bucket / "no-metadata.bin"
        plain.write_bytes(b"plain")
        os.setxattr(bucket, "user.acl", b'{"Owner":"synthetic","Grantees":[]}')
        os.setxattr(bucket, "user.ownership", b"BucketOwnerEnforced")
        os.setxattr(image, "user.etag", ETAG)
        os.setxattr(image, "user.content-type", b"image/png")
        os.setxattr(image, "user.X-Amz-Meta-note", SECRET_VALUE)
        os.setxattr(image, "user.binary", BINARY)
        return root


def all_user_xattrs(root: Path) -> dict[str, dict[str, bytes]]:
    result = {".": vat.read_user_xattrs(root)}
    for path in sorted(root.rglob("*")):
        result[path.relative_to(root).as_posix()] = vat.read_user_xattrs(path)
    return result


def legacy_tar(path: Path, files: dict[str, bytes], *, member_pax: dict[str, dict[str, str]] | None = None,
               global_extra: dict[str, str] | None = None) -> None:
    """A volume tar exactly as written before the fix (schema 1 root metadata, no xattr records)."""
    headers = {"NEXOLAB.volume.schema": "1", "NEXOLAB.volume.root.mode": "0755",
               "NEXOLAB.volume.root.uid": str(os.getuid() if hasattr(os, "getuid") else 0),
               "NEXOLAB.volume.root.gid": str(os.getgid() if hasattr(os, "getgid") else 0)}
    headers.update(global_extra or {})
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT, pax_headers=headers, encoding="utf-8") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), 0o644
            info.pax_headers = dict((member_pax or {}).get(name, {}))
            archive.addfile(info, io.BytesIO(content))


class VolumeArchiveXattrTests(TmpCase):
    def test_round_trip_restores_every_user_xattr_byte_exact(self) -> None:
        self.require_xattrs()
        source = self.object_tree()
        os.setxattr(source, "user.root-marker", b"root")
        archive = self.tmp / "objects.tar"
        summary = vat.create_archive(source, archive)
        self.assertEqual(summary, {"scheme": "user-v1", "entries": 3, "attributes": 7,
                                   "bytes": summary["bytes"]})
        destination = self.tmp / "restore"
        report = vat.extract_archive(archive, destination)
        self.assertEqual(all_user_xattrs(destination), all_user_xattrs(source))
        image = destination / "nexolab-equipment-images" / "equipment" / "SIM-01" / "a.png"
        self.assertEqual(os.getxattr(image, "user.etag"), ETAG)
        self.assertEqual(os.getxattr(image, "user.binary"), BINARY)
        self.assertEqual(report["xattrs"], {"scheme": "user-v1", "entries": 3, "attributes": 7, "applied": 7,
                                            "dropped": 0, "dropped_entries": 0})

    def test_archive_stays_deterministic_with_xattrs(self) -> None:
        self.require_xattrs()
        source = self.object_tree()
        vat.create_archive(source, self.tmp / "one.tar")
        vat.create_archive(source, self.tmp / "two.tar")
        self.assertEqual((self.tmp / "one.tar").read_bytes(), (self.tmp / "two.tar").read_bytes())

    def test_records_are_gnu_tar_compatible_schily_xattrs(self) -> None:
        self.require_xattrs()
        source = self.object_tree()
        archive = self.tmp / "objects.tar"
        vat.create_archive(source, archive)
        with tarfile.open(archive, encoding="utf-8", errors="surrogateescape") as handle:
            self.assertEqual(handle.pax_headers["NEXOLAB.volume.xattrs"], "user-v1")
            member = handle.getmember("nexolab-equipment-images/equipment/SIM-01/a.png")
            self.assertEqual(member.pax_headers["SCHILY.xattr.user.etag"], ETAG.decode())
        tar = shutil.which("tar")
        if tar is None or b"--xattrs" not in subprocess.run([tar, "--help"], capture_output=True).stdout:
            self.skipTest("GNU tar with --xattrs is not available")
        target = self.tmp / "gnu"
        target.mkdir()
        subprocess.run([tar, "--xattrs", "--xattrs-include=user.*", "-xf", str(archive), "-C", str(target)],
                       check=True, capture_output=True)
        image = target / "nexolab-equipment-images" / "equipment" / "SIM-01" / "a.png"
        self.assertEqual(os.getxattr(image, "user.content-type"), b"image/png")
        self.assertEqual(os.getxattr(image, "user.binary"), BINARY)

    def test_only_user_namespace_is_read(self) -> None:
        path = self.tmp / "file"
        path.write_bytes(b"x")
        names = ["security.selinux", "trusted.overlay.opaque", "system.posix_acl_access", "user.etag"]
        read: list[str] = []

        def fake_get(_path, name, follow_symlinks=True):
            read.append(name)
            return b"value"
        with mock.patch.object(vat.os, "listxattr", lambda *_a, **_k: names, create=True), \
                mock.patch.object(vat.os, "getxattr", fake_get, create=True):
            self.assertEqual(vat.read_user_xattrs(path), {"user.etag": b"value"})
        self.assertEqual(read, ["user.etag"])

    def test_filesystem_without_xattr_support_reads_as_empty(self) -> None:
        path = self.tmp / "file"
        path.write_bytes(b"x")

        def unsupported(*_args, **_kwargs):
            raise OSError(errno.ENOTSUP, "not supported")
        with mock.patch.object(vat.os, "listxattr", unsupported, create=True):
            self.assertEqual(vat.read_user_xattrs(path), {})

    def test_capture_caps_fail_closed(self) -> None:
        path = self.tmp / "file"
        path.write_bytes(b"x")
        cases = [
            ("MAX_XATTR_VALUE_BYTES", 4, {"user.a": b"12345"}, "value exceeds"),
            ("MAX_XATTRS_PER_ENTRY", 1, {"user.a": b"1", "user.b": b"2"}, "too many"),
            ("MAX_XATTR_BYTES_PER_ENTRY", 10, {"user.a": b"123456"}, "per entry"),
        ]
        for constant, value, xattrs, message in cases:
            with self.subTest(constant=constant), mock.patch.object(vat, constant, value), \
                    mock.patch.object(vat.os, "listxattr", lambda *_a, **_k: list(xattrs), create=True), \
                    mock.patch.object(vat.os, "getxattr", lambda _p, n, follow_symlinks=True: xattrs[n],
                                      create=True):
                with self.assertRaisesRegex(vat.VolumeArchiveFailure, message):
                    vat.read_user_xattrs(path)
        budget = vat.XattrBudget()
        with mock.patch.object(vat, "MAX_XATTR_BYTES_TOTAL", 20):
            budget.add({"user.a": b"1234"}, "one")
            with self.assertRaisesRegex(vat.VolumeArchiveFailure, "archive cap"):
                budget.add({"user.b": b"12345678"}, "two")

    def test_invalid_names_are_refused(self) -> None:
        for name in ("security.selinux", "trusted.x", "user.", "user.a=b", "user.a\nb", "user." + "x" * 300):
            with self.subTest(name=name[:20]), self.assertRaises(vat.VolumeArchiveFailure):
                vat._validate_xattr_name(name)

    def test_extract_without_xattr_support_fails_closed_and_leaves_nothing(self) -> None:
        archive = self.tmp / "objects.tar"
        legacy_tar(archive, {"bucket/a.png": b"png"},
                   member_pax={"bucket/a.png": {"SCHILY.xattr.user.etag": ETAG.decode()}},
                   global_extra={"NEXOLAB.volume.xattrs": "user-v1"})
        destination = self.tmp / "restore"

        def unsupported(*_args, **_kwargs):
            raise OSError(errno.EOPNOTSUPP, "Operation not supported")
        with mock.patch.object(vat.os, "setxattr", unsupported, create=True):
            with self.assertRaisesRegex(vat.VolumeArchiveFailure, "would be lost"):
                vat.extract_archive(archive, destination)
            self.assertEqual(list(destination.iterdir()), [])
            report = vat.extract_archive(archive, destination, allow_xattr_loss=True)
        self.assertEqual(report["xattrs"]["dropped"], 1)
        self.assertEqual(report["xattrs"]["applied"], 0)
        self.assertIn("cannot store user extended attributes", report["xattrs"]["loss_reason"])
        self.assertEqual((destination / "bucket" / "a.png").read_bytes(), b"png")

    def test_extract_on_platform_without_setxattr_is_not_silent(self) -> None:
        archive = self.tmp / "objects.tar"
        legacy_tar(archive, {"a": b"1"}, member_pax={"a": {"SCHILY.xattr.user.etag": "x"}},
                   global_extra={"NEXOLAB.volume.xattrs": "user-v1"})
        with mock.patch.object(vat, "os", wraps=os) as fake_os:
            del fake_os.setxattr
            with self.assertRaisesRegex(vat.VolumeArchiveFailure, "no extended attribute support"):
                vat.extract_archive(archive, self.tmp / "restore")

    def test_pre_fix_archive_extracts_exactly_as_before(self) -> None:
        archive = self.tmp / "legacy.tar"
        legacy_tar(archive, {"bucket/a.png": b"png", "bucket/b.png": b"png2"})
        destination = self.tmp / "restore"
        with mock.patch.object(vat.os, "setxattr", side_effect=AssertionError("must not be called"), create=True):
            report = vat.extract_archive(archive, destination)
        self.assertEqual(report["xattrs"], {"scheme": "none", "entries": 0, "attributes": 0, "applied": 0,
                                            "dropped": 0, "dropped_entries": 0})
        self.assertEqual((destination / "bucket" / "b.png").read_bytes(), b"png2")

    def test_crafted_archives_are_refused(self) -> None:
        declared = {"NEXOLAB.volume.xattrs": "user-v1"}
        cases = {
            "security namespace": ({"a": {"SCHILY.xattr.security.capability": "x"}}, declared, "user. namespace"),
            "trusted namespace": ({"a": {"SCHILY.xattr.trusted.overlay": "x"}}, declared, "user. namespace"),
            "undeclared records": ({"a": {"SCHILY.xattr.user.etag": "x"}}, {}, "without declaring"),
            "libarchive records": ({"a": {"LIBARCHIVE.xattr.user.etag": "eA=="}}, declared, "unsupported metadata"),
            "acl records": ({"a": {"SCHILY.acl.access": "user::rw-"}}, declared, "unsupported metadata"),
            "global records": ({}, {**declared, "SCHILY.xattr.user.etag": "x"}, "global header"),
            "unknown scheme": ({}, {"NEXOLAB.volume.xattrs": "user-v2"}, "scheme is unsupported"),
            "oversized value": ({"a": {"SCHILY.xattr.user.big": "x" * (vat.MAX_XATTR_VALUE_BYTES + 1)}}, declared,
                                "value exceeds"),
            "undeclared root records": ({}, {"NEXOLAB.volume.root.xattr.user.a": "x"}, "without declaring"),
        }
        for label, (member_pax, global_extra, message) in cases.items():
            with self.subTest(label=label):
                archive = self.tmp / f"{label.replace(' ', '-')}.tar"
                legacy_tar(archive, {"a": b"1"}, member_pax=member_pax, global_extra=global_extra)
                destination = self.tmp / f"restore-{label.replace(' ', '-')}"
                with self.assertRaisesRegex(vat.VolumeArchiveFailure, message):
                    vat.extract_archive(archive, destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_traversal_and_symlink_protections_are_unchanged_with_xattrs(self) -> None:
        declared = {"NEXOLAB.volume.xattrs": "user-v1"}
        archive = self.tmp / "traversal.tar"
        legacy_tar(archive, {"../escape": b"x"}, member_pax={"../escape": {"SCHILY.xattr.user.etag": "x"}},
                   global_extra=declared)
        destination = self.tmp / "restore"
        with self.assertRaisesRegex(vat.VolumeArchiveFailure, "unsafe"):
            vat.extract_archive(archive, destination)
        self.assertFalse((self.tmp / "escape").exists())
        link_archive = self.tmp / "link.tar"
        with tarfile.open(link_archive, "w", format=tarfile.PAX_FORMAT, pax_headers=declared) as handle:
            link = tarfile.TarInfo("a.png")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
            link.pax_headers = {"SCHILY.xattr.user.etag": "x"}
            handle.addfile(link)
        with self.assertRaisesRegex(vat.VolumeArchiveFailure, "file or directory"):
            vat.extract_archive(link_archive, self.tmp / "restore-link")

    def test_unknown_volume_keys_are_still_refused(self) -> None:
        """The unknown-NEXOLAB.volume.*-key rule is kept: it is also what makes extractors from before
        the fix refuse a new archive instead of silently extracting it without its metadata."""
        archive = self.tmp / "objects.tar"
        legacy_tar(archive, {"a": b"1"}, global_extra={"NEXOLAB.volume.xattrs": "user-v1",
                                                       "NEXOLAB.volume.unknown": "1"})
        with self.assertRaisesRegex(vat.VolumeArchiveFailure, "unsupported keys"):
            vat.extract_archive(archive, self.tmp / "restore")

    def test_cli_reports_counts_and_warns_on_loss_without_values(self) -> None:
        archive = self.tmp / "objects.tar"
        legacy_tar(archive, {"a": b"1"}, member_pax={"a": {"SCHILY.xattr.user.note": SECRET_VALUE.decode()}},
                   global_extra={"NEXOLAB.volume.xattrs": "user-v1"})
        stdout, stderr = io.StringIO(), io.StringIO()

        def unsupported(*_args, **_kwargs):
            raise OSError(errno.ENOTSUP, "not supported")
        argv = ["nexolab-volume-archive.py", "extract", "--archive", str(archive), "--destination",
                str(self.tmp / "restore"), "--allow-xattr-loss"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(vat.os, "setxattr", unsupported, create=True), \
                mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(vat.main(), 0)
        report = json.loads(stdout.getvalue().strip().splitlines()[-1])
        self.assertEqual(report["xattrs"]["dropped"], 1)
        self.assertIn("NOT restored", stderr.getvalue())
        self.assertNotIn(SECRET_VALUE.decode(), stdout.getvalue() + stderr.getvalue())


class LeafACaptureTests(TmpCase):
    def config(self, objects: Path) -> object:
        other = self.tmp / "other"
        (other / "mqtt").mkdir(parents=True)
        (other / "mqtt" / "dynamic-security.json").write_text("{}")
        (other / "edge-mqtt").mkdir()
        (other / "edge-mqtt" / "db").write_bytes(b"p")
        (other / "keys").mkdir()
        (other / "keys" / "private.pem").write_bytes(b"k")
        (other / "keys" / "public.pem").write_bytes(b"p")
        import sqlite3
        for name in ("outbox.sqlite", "spool.sqlite"):
            connection = sqlite3.connect(other / name)
            connection.execute("CREATE TABLE t (x)")
            connection.commit()
            connection.close()
        key = self.tmp / "dr.key"
        key.write_bytes(KEY)
        key.chmod(0o600)

        def store(store_id, method, entry, path=None, fmt="volume_tar", **extra):
            item = {"id": store_id, "method": method, "format": fmt, "entry_path": entry, "max_bytes": 1024**2}
            if path is not None:
                item["path"] = str(path)
            item.update(extra)
            return item
        raw = {
            "schema_version": 1, "kind": "nexolab-dr-scheduled-backup", "repository": "eNgine9r/nexolab-platform",
            "source_commit": COMMIT, "output_dir": str(self.tmp / "out"), "key_file": str(key),
            "lock_file": str(self.tmp / "lock"), "reserve_free_bytes": 20 * GiB, "max_backup_bytes": 16 * 1024**2,
            "stores": [
                store("postgresql", "docker_exec_stream", "postgresql/nexolab.dump", fmt="pg_custom",
                      argv=["docker", "exec", "pg", "pg_dump", "-U", "n", "-d", "n", "-Fc"]),
                store("object-storage", "directory_snapshot", "object-storage/objects.tar", objects),
                store("mqtt-dynamic-security", "directory_snapshot", "mqtt/data.tar", other / "mqtt"),
                store("edge-mqtt-persistence", "directory_snapshot", "edge-mqtt/data.tar", other / "edge-mqtt"),
                store("edge-sqlite-outbox", "sqlite_online", "edge/outbox.sqlite", other / "outbox.sqlite",
                      fmt="sqlite"),
                store("central-ingestion-spool", "sqlite_online", "central/spool.sqlite", other / "spool.sqlite",
                      fmt="sqlite"),
                store("local-auth-private-key", "file_snapshot", "local-auth/private.pem",
                      other / "keys" / "private.pem", fmt="pem"),
                store("local-auth-public-key", "file_snapshot", "local-auth/public.pem",
                      other / "keys" / "public.pem", fmt="pem"),
            ],
        }
        path = self.tmp / "config.json"
        path.write_text(json.dumps(raw))
        return bk.load_config(path)

    @staticmethod
    def capture(store, sink):
        if store.method == "docker_exec_stream":
            sink.write(b"PGDMP synthetic")
            return None
        return bk.capture_store(store, sink)

    def test_backup_bundle_to_isolated_extract_preserves_object_metadata(self) -> None:
        self.require_xattrs()
        objects = self.object_tree()
        before = all_user_xattrs(objects)
        receipt = bk.run_backup(self.config(objects), free=lambda _p: 500 * GiB, capture=self.capture)
        self.assertEqual(all_user_xattrs(objects), before, "capture must not modify the source")
        store = next(s for s in receipt["stores"] if s["id"] == "object-storage")
        self.assertEqual(store["xattrs"], {"scheme": "user-v1", "entries": 2, "attributes": 6,
                                           "bytes": store["xattrs"]["bytes"]})
        self.assertNotIn("xattrs", next(s for s in receipt["stores"] if s["id"] == "local-auth-public-key"))
        receipt_text = (self.tmp / "out" / f"{Path(receipt['bundle']['file']).stem}.receipt.json").read_text()
        self.assertNotIn(SECRET_VALUE.decode(), receipt_text)
        self.assertNotIn("user.etag", receipt_text)
        bundle = self.tmp / "out" / receipt["bundle"]["file"]
        self.assertNotIn(SECRET_VALUE, bundle.read_bytes())
        verified = drs.verify_file(bundle, KEY)
        manifest_store = next(s for s in verified.manifest["stores"] if s["id"] == "object-storage")
        self.assertEqual(manifest_store["xattrs"], store["xattrs"])
        plaintext = self.tmp / "plaintext"
        drs.extract_file(bundle, KEY, plaintext)
        restored = self.tmp / "restored-objects"
        report = vat.extract_archive(plaintext / "object-storage" / "objects.tar", restored)
        self.assertEqual(all_user_xattrs(restored), before)
        self.assertEqual(report["xattrs"]["applied"], 6)

    def test_xattr_only_change_during_capture_fails_the_snapshot(self) -> None:
        self.require_xattrs()
        objects = self.object_tree()
        image = objects / "nexolab-equipment-images" / "equipment" / "SIM-01" / "a.png"
        original = tarfile.TarFile.addfile
        calls = {"n": 0}

        def mutate(archive, info, fileobj=None, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:  # VersityGW rewriting metadata via setxattr: size and mtime unchanged
                os.setxattr(image, "user.content-type", b"image/jpeg")
            return original(archive, info, fileobj, **kwargs)
        mtime = image.stat().st_mtime_ns
        with mock.patch.object(tarfile.TarFile, "addfile", mutate):
            with self.assertRaisesRegex(bk.CaptureFailed, "changed during capture"):
                bk.capture_directory(objects, io.BytesIO())
        self.assertEqual(image.stat().st_mtime_ns, mtime)

    def test_capture_cap_violation_is_a_capture_failure_not_a_crash(self) -> None:
        self.require_xattrs()
        objects = self.object_tree()
        with mock.patch.object(vat, "MAX_XATTR_VALUE_BYTES", 8):
            with self.assertRaisesRegex(bk.CaptureFailed, "value exceeds"):
                bk.capture_directory(objects, io.BytesIO())

    def test_tree_without_xattrs_still_captures(self) -> None:
        objects = self.tmp / "plain"
        (objects / "bucket").mkdir(parents=True)
        (objects / "bucket" / "a").write_bytes(b"1")
        summary = bk.capture_directory(objects, io.BytesIO())
        self.assertEqual(summary, {"scheme": "user-v1", "entries": 0, "attributes": 0, "bytes": 0})


class IsolatedRestoreMetadataTests(unittest.TestCase):
    DB = {"equipment/SIM-01/a.png": {"etag": '"abc"', "media_type": "image/png"}}
    OBSERVED = {"equipment/SIM-01/a.png": {"key": "equipment/SIM-01/a.png", "etag": '"abc"',
                                           "content_type": "image/png"}}

    @staticmethod
    def head(etag='"abc"', content_type="image/png", status=200):
        return [{"key": "equipment/SIM-01/a.png", "status": status, "etag": etag, "content_type": content_type}]

    def test_ok_only_when_database_and_source_observation_match(self) -> None:
        result = ir.evaluate_object_metadata(self.DB, self.head(), self.OBSERVED)
        self.assertEqual(result["metadata_fidelity"], "OK")
        self.assertEqual(result["metadata_basis"], ["database", "source_observation"])

    def test_missing_etag_or_content_type_is_degraded(self) -> None:
        for head in (self.head(etag=None), self.head(content_type=None), self.head(content_type="binary/octet-stream"),
                     self.head(etag='"other"'), self.head(status=404)):
            with self.subTest(head=head):
                result = ir.evaluate_object_metadata(self.DB, head, self.OBSERVED)
                self.assertEqual(result["metadata_fidelity"], "DEGRADED")
                self.assertEqual(result["degraded_objects"], 1)

    def test_source_observation_mismatch_is_degraded(self) -> None:
        observed = {k: dict(v, etag='"source-differs"') for k, v in self.OBSERVED.items()}
        self.assertEqual(ir.evaluate_object_metadata(self.DB, self.head(), observed)["metadata_fidelity"], "DEGRADED")

    def test_without_source_observation_it_is_never_ok(self) -> None:
        result = ir.evaluate_object_metadata(self.DB, self.head(), None)
        self.assertEqual(result["metadata_fidelity"], "UNVERIFIED_NO_SOURCE_OBSERVATION")

    def test_receipt_block_has_counts_only(self) -> None:
        result = ir.evaluate_object_metadata(self.DB, self.head(), self.OBSERVED)
        text = json.dumps(result)
        self.assertNotIn("SIM-01", text)
        self.assertNotIn("abc", text)

    def test_observation_objects_are_validated(self) -> None:
        self.assertIsNone(ir.observation_objects(None))
        self.assertIsNone(ir.observation_objects({"kind": "x"}))
        self.assertEqual(set(ir.observation_objects({"objects": list(self.OBSERVED.values())})), set(self.OBSERVED))
        with self.assertRaises(ir.Refused):
            ir.observation_objects({"objects": [{"etag": "x"}]})

    def test_xattr_loss_is_allowed_only_in_rehearsal_and_always_reported(self) -> None:
        for mode, allowed in (("rehearsal", True), ("site", False)):
            with self.subTest(mode=mode):
                restore = ir.Restore.__new__(ir.Restore)
                restore.config = mock.Mock(rehearsal=mode == "rehearsal")
                restore.warnings = []
                ops: list[dict] = []

                def helper(volume, op, plaintext=None):
                    ops.append(op)
                    return {"ok": True, "xattrs": {"scheme": "user-v1", "dropped": 2, "loss_reason": "ENOTSUP"}}
                restore.helper = helper
                report = restore.extract_tar("nx-dr-x-object-storage-data", "object-storage/objects.tar", Path("/p"))
                self.assertEqual(ops[0]["allow_xattr_loss"], allowed)
                self.assertEqual(report["dropped"], 2)
                self.assertTrue(any("could not be restored" in w for w in restore.warnings))

    def test_helper_passes_the_loss_flag_to_the_extract_cli(self) -> None:
        self.assertIn('argv.append("--allow-xattr-loss")', ir.HELPER)
        self.assertIn('if op.get("allow_xattr_loss")', ir.HELPER)


if __name__ == "__main__":
    unittest.main()
