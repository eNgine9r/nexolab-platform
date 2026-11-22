"""#1631 off-device copy tests: synthetic bundles in temporary directories only.

No production host, real disk, network or hardware is touched. "Different disk" is
simulated with an injected device-identity probe so the suite runs on one disk.
unittest style so the Core CI ``unittest discover -p 'test_ci_*.py'`` runs it too.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
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


oc = _load("nexolab_dr_offdevice_copy", "nexolab-dr-offdevice-copy.py")
health = _load("nexolab_dr_readonly_health_1631", "nexolab-dr-readonly-health.py")
drs = oc.drs

KEY = bytes(range(100, 132))
COMMIT = "b" * 40
PI = oc.Volume("dev:8:2", "block:sda", False, "uuid-pi-root")
USB = oc.Volume("dev:8:17", "block:sdb", False, "uuid-usb-ssd")
POSIX = os.name == "posix"


def make_bundle(path: Path, payload: bytes = b"synthetic-postgres-dump" * 300, key: bytes = KEY) -> Path:
    header = drs.build_header(repository="eNgine9r/nexolab-platform", commit=COMMIT,
                              created_at="2026-11-22T00:00:00Z", key=key, chunk_size=4096,
                              nonce_prefix=drs.new_nonce_prefix())
    with path.open("wb") as output:
        writer = drs.EncryptedWriter(output, key, header)
        builder = drs.StreamBuilder(writer)
        builder.add_entry(path="postgresql/nexolab.dump", store="postgresql", content_format="pg_custom",
                          source=io.BytesIO(payload), max_bytes=10**9)
        builder.finish({"schema_version": 1, "kind": "nexolab-dr-stream-manifest", "issue": 1630})
        writer.close()
    return path


class Site:
    """Temporary 'Pi' (source tree, key, receipts) and 'USB SSD' (destination)."""

    def __init__(self, tmp: str, dest_volume: oc.Volume = USB, dest_inside_source: bool = False) -> None:
        self.root = Path(tmp).resolve()
        self.source = self.root / "pi" / "var-backups-nexolab-dr"
        self.source.mkdir(parents=True)
        self.dest = (self.source / "usb") if dest_inside_source else (self.root / "media" / "usb-ssd")
        self.dest.mkdir(parents=True)
        self.receipts = self.root / "pi" / "dr-evidence"
        self.key = self.root / "pi" / "etc-nexolab" / "dr-backup.key"
        self.key.parent.mkdir(parents=True)
        self.key.write_bytes(KEY)
        self.key.chmod(0o600)
        self.volumes = {Path(os.path.abspath(os.sep)): PI, self.root: PI, self.dest.resolve(): dest_volume}
        self.clock = iter(f"2026-11-22T0{i}:00:00Z" for i in range(10))

    def probe(self, path: Path) -> oc.Volume:
        path = Path(path).resolve()
        best = max((p for p in self.volumes if path == p or p in path.parents), key=lambda p: len(p.parts))
        return self.volumes[best]

    def enroll(self, kind: str = "dedicated_media") -> dict:
        return oc.enroll(self.dest, kind, "usb-ssd-a", probe=self.probe)

    def bundle(self, stamp: str = "20261122T010000Z", suffix: str = "a1b2c3", **kwargs) -> Path:
        return make_bundle(self.source / f"nexolab-dr-{stamp}-{suffix}.nxs", **kwargs)

    def copy(self, bundle: Path, **kwargs):
        kwargs.setdefault("probe", self.probe)
        kwargs.setdefault("free", lambda _path: 500 * oc.MiB)
        kwargs.setdefault("now", lambda: next(self.clock))
        return oc.copy_bundle(bundle, self.key, self.dest, self.receipts, **kwargs)

    def dest_names(self) -> set[str]:
        return {p.name for p in self.dest.iterdir()} - {oc.MARKER_NAME}


class OffDeviceCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.site = Site(self._tmp.name)
        self.site.enroll()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ------------------------------------------------------------- success + receipt

    def test_copy_writes_verified_bundle_and_exact_receipt(self):
        bundle = self.site.bundle()
        result = self.site.copy(bundle)
        self.assertEqual(result["status"], "COPIED_READBACK_VERIFIED")
        receipt = result["receipt"]
        self.assertEqual(list(receipt), list(oc.RECEIPT_FIELDS))
        self.assertEqual(set(receipt), {
            "schema_version", "kind", "bundle_name", "bundle_sha256", "bundle_bytes", "source_manifest_sha256",
            "destination_kind", "destination_identity_sha256", "source_disk_independent", "readback_sha256",
            "readback_bytes", "key_fingerprint_sha256", "copied_at", "copier", "free_after_bytes"})
        data = bundle.read_bytes()
        copied = self.site.dest / bundle.name
        self.assertEqual(copied.read_bytes(), data)
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["kind"], "nexolab-dr-custody-receipt")
        self.assertEqual(receipt["bundle_name"], bundle.name)
        self.assertEqual(receipt["bundle_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(receipt["bundle_bytes"], len(data))
        self.assertEqual((receipt["readback_sha256"], receipt["readback_bytes"]),
                         (receipt["bundle_sha256"], receipt["bundle_bytes"]))
        manifest = drs.verify_file(bundle, KEY).manifest
        self.assertEqual(receipt["source_manifest_sha256"], hashlib.sha256(drs.canonical_json(manifest)).hexdigest())
        self.assertEqual(receipt["destination_kind"], "dedicated_media")
        marker = oc.read_marker(self.site.dest)
        self.assertEqual(receipt["destination_identity_sha256"], oc.destination_identity_sha256(marker))
        self.assertTrue(receipt["source_disk_independent"])
        self.assertEqual(receipt["key_fingerprint_sha256"], hashlib.sha256(KEY).hexdigest())
        self.assertEqual(receipt["copied_at"], "2026-11-22T00:00:00Z")
        self.assertEqual(receipt["copier"], f"nexolab-dr-offdevice-copy.py/{oc.VERSION}")
        self.assertEqual(receipt["free_after_bytes"], 500 * oc.MiB)

        dest_receipt = self.site.dest / bundle.name.replace(".nxs", ".custody-receipt.json")
        local_receipt = self.site.receipts / dest_receipt.name
        self.assertEqual(dest_receipt.read_bytes(), drs.canonical_json(receipt))
        self.assertEqual(local_receipt.read_bytes(), dest_receipt.read_bytes())
        self.assertEqual(self.site.dest_names(), {bundle.name, dest_receipt.name})
        if POSIX:
            for path in (copied, dest_receipt, local_receipt, self.site.dest / oc.MARKER_NAME):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)

    def test_identity_hash_is_not_a_path(self):
        marker = oc.read_marker(self.site.dest)
        identity = oc.destination_identity_sha256(marker)
        for candidate in (str(self.site.dest), self.site.dest.as_posix(), "usb-ssd-a"):
            self.assertNotEqual(identity, hashlib.sha256(candidate.encode()).hexdigest())

    def test_leaf_a_source_receipt_is_cross_checked(self):
        bundle = self.site.bundle()
        data = bundle.read_bytes()
        source_receipt = self.site.source / bundle.name.replace(".nxs", ".receipt.json")
        good = {"kind": "nexolab-dr-backup-receipt", "key_fingerprint": drs.key_fingerprint(KEY),
                "bundle": {"file": bundle.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}
        source_receipt.write_text(json.dumps(dict(good, bundle=dict(good["bundle"], size=1))), encoding="utf-8")
        with self.assertRaisesRegex(oc.CopyFailed, "leaf-A"):
            self.site.copy(bundle, source_receipt=source_receipt)
        self.assertEqual(self.site.dest_names(), set())
        source_receipt.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(self.site.copy(bundle, source_receipt=source_receipt)["status"], "COPIED_READBACK_VERIFIED")

    # ------------------------------------------------------------- independence

    def _refused_site(self, volume: oc.Volume, message: str, inside: bool = False) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Site(tmp, dest_volume=volume, dest_inside_source=inside)
            site.enroll()
            bundle = site.bundle()
            with self.assertRaisesRegex(oc.Blocked, message):
                site.copy(bundle)
            self.assertEqual(site.dest_names(), set())
            self.assertFalse(site.receipts.exists() and any(site.receipts.iterdir()))

    def test_same_physical_disk_is_refused(self):
        self._refused_site(oc.Volume("dev:8:3", "block:sda", False, "uuid-other-partition"), "same physical disk")

    def test_same_filesystem_is_refused(self):
        self._refused_site(oc.Volume("dev:8:2", "block:sdz", False, "uuid-bind-mount"), "same file system")

    def test_destination_inside_source_tree_is_refused(self):
        self._refused_site(USB, "inside the source tree", inside=True)

    def test_unidentifiable_destination_device_is_refused(self):
        with self.assertRaisesRegex(oc.Blocked, "cannot be identified"):
            self._refused_site(oc.Volume("dev:0:44", "", False, "uuid-tmpfs"), "unused")  # enrolment refused
        bundle = self.site.bundle()
        self.site.volumes[self.site.dest.resolve()] = oc.Volume("dev:0:44", "", False, "uuid-usb-ssd")
        with self.assertRaisesRegex(oc.Blocked, "cannot be identified"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    def test_key_on_destination_disk_is_refused(self):
        bundle = self.site.bundle()
        self.site.volumes[self.site.key.parent.resolve()] = oc.Volume("dev:8:18", "block:sdb", False, "x")
        with self.assertRaisesRegex(oc.Blocked, "same physical disk"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    def test_unenrolled_or_cloned_marker_is_refused(self):
        bundle = self.site.bundle()
        (self.site.dest / oc.MARKER_NAME).unlink()
        with self.assertRaisesRegex(oc.Blocked, "not enrolled"):
            self.site.copy(bundle)
        self.site.enroll()
        self.site.volumes[self.site.dest.resolve()] = oc.Volume("dev:8:33", "block:sdc", False, "uuid-other-ssd")
        with self.assertRaisesRegex(oc.Blocked, "another volume"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    def test_marker_kind_must_match_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Site(tmp)
            with self.assertRaisesRegex(oc.Blocked, "not a network share"):
                site.enroll("independent_host")
            site.volumes[site.dest.resolve()] = oc.Volume("dev:0:61", "remote://pc/nexolab-dr", True,
                                                          "remote://pc/nexolab-dr")
            site.enroll("independent_host")
            self.assertEqual(site.copy(site.bundle())["receipt"]["destination_kind"], "independent_host")

    def test_enroll_never_overwrites_marker(self):
        before = (self.site.dest / oc.MARKER_NAME).read_bytes()
        with self.assertRaisesRegex(oc.Blocked, "already enrolled"):
            self.site.enroll()
        self.assertEqual((self.site.dest / oc.MARKER_NAME).read_bytes(), before)

    def test_receipts_dir_on_destination_is_refused(self):
        bundle = self.site.bundle()
        with self.assertRaisesRegex(oc.Blocked, "receipts directory"):
            oc.copy_bundle(bundle, self.site.key, self.site.dest, self.site.dest / "receipts",
                           probe=self.site.probe, free=lambda _p: 500 * oc.MiB)

    # ------------------------------------------------------------- key / tamper

    def test_missing_key_is_refused_before_copy(self):
        bundle = self.site.bundle()
        self.site.key.unlink()
        with self.assertRaisesRegex(oc.Blocked, "key"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    def test_invalid_key_length_is_refused(self):
        bundle = self.site.bundle()
        self.site.key.write_bytes(KEY[:31])
        with self.assertRaisesRegex(oc.Blocked, "32 raw bytes"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    @unittest.skipUnless(POSIX, "mode bits are POSIX-only")
    def test_world_readable_key_is_refused(self):
        bundle = self.site.bundle()
        self.site.key.chmod(0o644)
        with self.assertRaisesRegex(oc.Blocked, "0600"):
            self.site.copy(bundle)

    def test_wrong_key_is_refused_before_copy(self):
        bundle = self.site.bundle()
        self.site.key.write_bytes(bytes(32))
        with self.assertRaisesRegex(oc.CopyFailed, "verification"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    def test_tampered_bundle_is_refused_before_copy(self):
        bundle = self.site.bundle()
        data = bytearray(bundle.read_bytes())
        data[len(data) // 2] ^= 0x01
        bundle.write_bytes(bytes(data))
        with self.assertRaisesRegex(oc.CopyFailed, "nothing copied"):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    def test_truncated_bundle_is_refused_before_copy(self):
        bundle = self.site.bundle()
        bundle.write_bytes(bundle.read_bytes()[:-10])
        with self.assertRaises(oc.CopyFailed):
            self.site.copy(bundle)
        self.assertEqual(self.site.dest_names(), set())

    # ------------------------------------------------------------- copy failures

    def assert_nothing_accepted(self, bundle: Path) -> None:
        self.assertEqual(self.site.dest_names(), set(), "no partial, final bundle or receipt may remain")
        self.assertFalse(self.site.receipts.exists() and any(self.site.receipts.iterdir()))

    def test_readback_hash_mismatch_discards_copy(self):
        bundle = self.site.bundle()
        original = oc.hash_file

        def corrupting_readback(path: Path):
            data = bytearray(path.read_bytes())
            data[-1] ^= 0xFF  # media silently corrupted the written bytes
            path.write_bytes(bytes(data))
            return original(path)

        with mock.patch.object(oc, "hash_file", corrupting_readback):
            with self.assertRaisesRegex(oc.CopyFailed, "read-back"):
                self.site.copy(bundle)
        self.assert_nothing_accepted(bundle)

    def test_interrupted_copy_leaves_no_partial_or_final(self):
        bundle = self.site.bundle(payload=os.urandom(3 * oc.COPY_CHUNK))

        def interrupt(handle, data):
            handle.write(data[: len(data) // 2])
            raise KeyboardInterrupt  # SIGINT/SIGTERM mid-copy

        with mock.patch.object(oc, "_write_chunk", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.site.copy(bundle)
        self.assert_nothing_accepted(bundle)
        # A later run succeeds normally.
        self.assertEqual(self.site.copy(bundle)["status"], "COPIED_READBACK_VERIFIED")

    def test_short_write_is_rejected(self):
        bundle = self.site.bundle()
        with mock.patch.object(oc, "_write_chunk", lambda handle, data: handle.write(data[:-1])):
            with self.assertRaisesRegex(oc.CopyFailed, "short write"):
                self.site.copy(bundle)
        self.assert_nothing_accepted(bundle)

    def test_io_error_during_copy_removes_partial(self):
        bundle = self.site.bundle()

        def enospc(handle, data):
            raise OSError(28, "No space left on device")

        with mock.patch.object(oc, "_write_chunk", enospc):
            with self.assertRaises(OSError):
                self.site.copy(bundle)
        self.assert_nothing_accepted(bundle)

    def test_stale_partial_blocks_and_is_not_deleted(self):
        bundle = self.site.bundle()
        stale = self.site.dest / f".{bundle.name}.partial"
        stale.write_bytes(b"half")
        with self.assertRaisesRegex(oc.Blocked, "stale partial"):
            self.site.copy(bundle)
        self.assertEqual(stale.read_bytes(), b"half")
        self.assertFalse((self.site.dest / bundle.name).exists())

    def test_insufficient_destination_space_is_refused(self):
        bundle = self.site.bundle()
        with self.assertRaisesRegex(oc.Blocked, "free"):
            self.site.copy(bundle, free=lambda _p: 1024)
        self.assertEqual(self.site.dest_names(), set())

    # ------------------------------------------------------------- idempotency

    def test_rerun_is_idempotent(self):
        bundle = self.site.bundle()
        first = self.site.copy(bundle)["receipt"]
        copied = self.site.dest / bundle.name
        mtime = copied.stat().st_mtime_ns
        second = self.site.copy(bundle)
        self.assertEqual(second["status"], "ALREADY_PRESENT_VERIFIED")
        self.assertEqual(second["receipt"], first)
        self.assertEqual(copied.stat().st_mtime_ns, mtime)
        local = self.site.receipts / oc.receipt_name(bundle.name)
        local.unlink()
        self.assertEqual(self.site.copy(bundle)["receipt"], first)
        self.assertEqual(local.read_bytes(), drs.canonical_json(first))

    def test_rerun_after_crash_before_receipt_issues_receipt_from_fresh_readback(self):
        bundle = self.site.bundle()
        self.site.copy(bundle)
        (self.site.dest / oc.receipt_name(bundle.name)).unlink()
        result = self.site.copy(bundle)
        self.assertEqual(result["status"], "ALREADY_PRESENT_VERIFIED")
        oc.validate_custody_receipt(result["receipt"])
        self.assertTrue((self.site.dest / oc.receipt_name(bundle.name)).exists())

    def test_different_file_under_final_name_is_never_overwritten(self):
        bundle = self.site.bundle()
        impostor = self.site.dest / bundle.name
        impostor.write_bytes(b"not the bundle")
        with self.assertRaisesRegex(oc.CopyFailed, "refusing to overwrite"):
            self.site.copy(bundle)
        self.assertEqual(impostor.read_bytes(), b"not the bundle")

    # ------------------------------------------------------------- receipt contract

    def test_receipt_validator_rejects_contract_drift(self):
        receipt = self.site.copy(self.site.bundle())["receipt"]
        for mutate in (
            lambda r: r.update(extra=True),
            lambda r: r.pop("free_after_bytes"),
            lambda r: r.update(readback_sha256="0" * 64),
            lambda r: r.update(source_disk_independent=False),
            lambda r: r.update(destination_kind="cloud"),
            lambda r: r.update(copied_at="2026-11-22T00:00:00+00:00"),
            lambda r: r.update(bundle_bytes=True),
        ):
            broken = dict(receipt)
            mutate(broken)
            with self.assertRaises(oc.CopyFailed):
                oc.validate_custody_receipt(broken)

    # ------------------------------------------------------------- retention

    def _three_copies(self) -> list[Path]:
        bundles = [self.site.bundle(stamp=f"20261122T0{i}0000Z", suffix=f"00000{i}") for i in range(1, 4)]
        for bundle in bundles:
            self.site.copy(bundle)
        return bundles

    def test_retention_is_report_only_by_default(self):
        bundles = self._three_copies()
        report = oc.retention(self.site.dest, probe=self.site.probe)
        self.assertEqual(report["status"], "REPORT_ONLY")
        self.assertEqual(report["verified_kept"], [bundles[2].name, bundles[1].name])
        self.assertEqual(report["deletion_candidates"], [bundles[0].name])
        self.assertEqual(report["deleted"], [])
        self.assertTrue((self.site.dest / bundles[0].name).exists())

    def test_retention_apply_keeps_last_two_and_untouched_unverified(self):
        bundles = self._three_copies()
        stranger = self.site.dest / "nexolab-dr-20261121T000000Z-ffffff.nxs"
        stranger.write_bytes(b"unknown, no receipt")
        report = oc.retention(self.site.dest, apply=True, probe=self.site.probe)
        self.assertEqual(report["deleted"], [bundles[0].name])
        self.assertEqual(report["unverified_untouched"], [stranger.name])
        self.assertFalse((self.site.dest / bundles[0].name).exists())
        self.assertFalse((self.site.dest / oc.receipt_name(bundles[0].name)).exists())
        self.assertTrue(stranger.exists())
        for bundle in bundles[1:]:
            self.assertTrue((self.site.dest / bundle.name).exists())
        # Local receipts and the Pi-side bundles are never touched.
        self.assertTrue((self.site.receipts / oc.receipt_name(bundles[0].name)).exists())
        self.assertTrue(all(b.exists() for b in bundles))

    def test_retention_never_deletes_last_verified_bundle(self):
        bundles = self._three_copies()
        for bundle in bundles[1:]:  # the two newest copies get corrupted on the medium
            target = self.site.dest / bundle.name
            target.write_bytes(target.read_bytes()[:-1] + b"\x00")
        report = oc.retention(self.site.dest, apply=True, probe=self.site.probe)
        self.assertEqual(report["deleted"], [])
        self.assertEqual(report["verified_kept"], [bundles[0].name])
        self.assertEqual(sorted(report["unverified_untouched"]), sorted(b.name for b in bundles[1:]))
        self.assertTrue(all((self.site.dest / b.name).exists() for b in bundles))

    def test_retention_requires_keep_of_at_least_two(self):
        self._three_copies()
        for keep in (0, 1):
            with self.assertRaisesRegex(oc.Blocked, ">= 2"):
                oc.retention(self.site.dest, keep=keep, apply=True, probe=self.site.probe)
        self.assertEqual(len([n for n in self.site.dest_names() if n.endswith(".nxs")]), 3)

    def test_retention_refuses_destination_on_root_disk(self):
        self._three_copies()
        self.site.volumes[self.site.dest.resolve()] = oc.Volume("dev:8:4", "block:sda", False, "uuid-usb-ssd")
        with self.assertRaisesRegex(oc.Blocked, "not independent"):
            oc.retention(self.site.dest, apply=True, probe=self.site.probe)

    # ------------------------------------------------------------- no key material

    def test_no_key_material_in_outputs_receipts_or_destination(self):
        forbidden = [KEY, KEY.hex().encode(), base64.b64encode(KEY), KEY.hex().upper().encode()]
        outputs = []
        with mock.patch.object(oc, "probe_volume", self.site.probe), \
                mock.patch.object(oc, "disk_free", lambda _p: 500 * oc.MiB):
            good = self.site.bundle()
            bad = self.site.bundle(suffix="dddddd")
            bad.write_bytes(bad.read_bytes()[:-5])
            for argv in (
                ["copy", "--bundle", str(good), "--key-file", str(self.site.key), "--destination",
                 str(self.site.dest), "--receipts-dir", str(self.site.receipts)],
                ["copy", "--bundle", str(bad), "--key-file", str(self.site.key), "--destination",
                 str(self.site.dest), "--receipts-dir", str(self.site.receipts)],
                ["retention", "--destination", str(self.site.dest)],
                ["verify-destination", "--destination", str(self.site.dest)],
            ):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = oc.main(argv)
                outputs.append((code, out.getvalue() + err.getvalue()))
        self.assertEqual([code for code, _ in outputs], [0, 1, 0, 0])
        self.assertIn("COPIED_READBACK_VERIFIED", outputs[0][1])
        blobs = [text.encode() for _, text in outputs]
        for directory in (self.site.dest, self.site.receipts):
            blobs.extend(p.read_bytes() for p in directory.rglob("*") if p.is_file())
        self.assertNotIn(oc.MARKER_NAME, [p.name for p in self.site.receipts.iterdir()])
        self.assertFalse(any(p.read_bytes() == KEY for p in self.site.dest.rglob("*") if p.is_file()))
        for blob in blobs:
            for needle in forbidden:
                self.assertNotIn(needle, blob)

    def test_cli_blocked_exit_code(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(oc, "probe_volume", self.site.probe):
            code = oc.main(["copy", "--bundle", str(self.site.bundle()), "--key-file",
                            str(self.site.root / "missing.key"), "--destination", str(self.site.dest),
                            "--receipts-dir", str(self.site.receipts)])
        self.assertEqual(code, 78)
        self.assertEqual(json.loads(err.getvalue())["status"], "BLOCKED")

    # ------------------------------------------------------------- health integration

    def test_health_gate_needs_real_destination_readback(self):
        bundle = self.site.bundle()
        self.site.copy(bundle)

        def assess(verifier):
            return health.assess(None, None, 30 * health.GiB, structural_validator=lambda _doc: None,
                                 offdevice_verifier=verifier)

        self.assertEqual(assess(None)["gates"]["encrypted_off_device_copy"]["status"], "UNVERIFIED")
        ok = assess(lambda: oc.reverify_destination(self.site.dest, probe=self.site.probe))
        self.assertEqual(ok["gates"]["encrypted_off_device_copy"]["status"], "REPORTED_OK")
        self.assertEqual(ok["status"], "BLOCKED")
        self.assertEqual(ok["site_activation"], "NOT_AUTHORIZED")
        # A receipt whose bundle no longer re-hashes (claim only) keeps the gate closed.
        target = self.site.dest / bundle.name
        target.write_bytes(target.read_bytes()[:-1] + b"\x00")
        bad = assess(lambda: oc.reverify_destination(self.site.dest, probe=self.site.probe))
        self.assertEqual(bad["gates"]["encrypted_off_device_copy"]["status"], "BLOCKED")
        # A destination that cannot be read is not evidence either.
        missing = assess(health.offdevice_reverifier(self.site.root / "not-mounted"))
        self.assertEqual(missing["gates"]["encrypted_off_device_copy"]["status"], "BLOCKED")

    @unittest.skipIf(sys.platform.startswith("linux"), "non-Linux fail-closed probe")
    def test_default_probe_fails_closed_off_linux(self):
        with self.assertRaisesRegex(oc.Blocked, "Linux only"):
            oc.probe_volume(self.site.dest)


if __name__ == "__main__":
    unittest.main()
