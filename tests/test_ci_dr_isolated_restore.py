"""#1632 isolated restore tests: synthetic bundles in temporary directories, no Docker.

Docker is replaced by a recording fake, so these tests prove refusals, custody binding,
plaintext cleanup, receipt hashing, RPO/RTO arithmetic and verification diff detection
without touching any container, network or host. unittest style so the Core CI
``unittest discover -p 'test_ci_*.py'`` runs it too.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


ir = _load("nexolab_dr_isolated_restore", "nexolab-dr-isolated-restore.py")
v2 = _load("nexolab_dr_v2_validator_1632", "validate-site-dr-inventory-v2.py")
drs = ir.drs
oc = ir.offdevice

KEY = bytes(range(7, 39))
COMMIT = "c" * 40
CREATED = "2026-11-22T10:00:00Z"
ORG = "00000000-0000-0000-0000-000000001632"
ENTRIES = {
    "postgresql": ("postgresql/nexolab.dump", "pg_custom", b"PGDMP-synthetic" * 50),
    "object-storage": ("object-storage/objects.tar", "volume_tar", b"tar-objects" * 20),
    "mqtt-dynamic-security": ("mqtt/mosquitto-data.tar", "volume_tar", b"tar-mqtt" * 20),
    "edge-mqtt-persistence": ("edge-mqtt/mosquitto-data.tar", "volume_tar", b"tar-edge" * 20),
    "edge-sqlite-outbox": ("edge/outbox.sqlite", "sqlite", b"SQLite format 3\x00" * 8),
    "central-ingestion-spool": ("central/ingestion-spool.sqlite", "sqlite", b"SQLite format 3\x00" * 4),
    "local-auth-private-key": ("local-auth/private.pem", "pem", b"-----PRIVATE KEY MATERIAL-----"),
    "local-auth-public-key": ("local-auth/public.pem", "pem", b"-----BEGIN PUBLIC KEY-----"),
}


def build_bundle(directory: Path, *, key: bytes = KEY, unsafe_path: str | None = None) -> tuple[Path, dict]:
    name = "nexolab-dr-20261122T100000Z-abc123.nxs"
    path = directory / name
    header = drs.build_header(repository="eNgine9r/nexolab-platform", commit=COMMIT, created_at=CREATED, key=key,
                              chunk_size=4096, nonce_prefix=drs.new_nonce_prefix())
    stores = []
    with path.open("wb") as output:
        writer = drs.EncryptedWriter(output, key, header)
        builder = drs.StreamBuilder(writer)
        for store_id, (entry_path, fmt, data) in ENTRIES.items():
            target = unsafe_path if (unsafe_path and store_id == "postgresql") else entry_path
            if unsafe_path and store_id == "postgresql":
                with mock.patch.object(drs, "safe_entry_path", lambda value: value):
                    sink = builder.begin_entry(path=target, store=store_id, content_format=fmt, max_bytes=10**9)
            else:
                sink = builder.begin_entry(path=target, store=store_id, content_format=fmt, max_bytes=10**9)
            sink.write(data)
            entry = sink.close()
            stores.append({"id": store_id, "disposition": "capture", "method": "x", "consistency": "x",
                           "entry_path": entry.path, "format": fmt, "size": entry.size, "sha256": entry.sha256})
        manifest = {"schema_version": 1, "kind": "nexolab-dr-stream-manifest", "issue": 1630,
                    "created_at": CREATED, "commit": COMMIT, "stores": stores}
        builder.finish(manifest)
        writer.close()
    full_manifest = dict(manifest)
    full_manifest["entries"] = [{"path": s["entry_path"], "store": s["id"], "format": s["format"], "size": s["size"],
                                 "sha256": s["sha256"]} for s in stores]
    return path, full_manifest


def custody_for(bundle: Path, manifest: dict, *, key: bytes = KEY, **overrides) -> dict:
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    receipt = {
        "schema_version": 1, "kind": "nexolab-dr-custody-receipt", "bundle_name": bundle.name,
        "bundle_sha256": digest, "bundle_bytes": bundle.stat().st_size,
        "source_manifest_sha256": hashlib.sha256(drs.canonical_json(manifest)).hexdigest(),
        "destination_kind": "dedicated_media", "destination_identity_sha256": "d" * 64,
        "source_disk_independent": True, "readback_sha256": digest, "readback_bytes": bundle.stat().st_size,
        "key_fingerprint_sha256": hashlib.sha256(key).hexdigest(), "copied_at": "2026-11-22T10:05:00Z",
        "copier": oc.COPIER, "free_after_bytes": 10**10,
    }
    receipt.update(overrides)
    return receipt


def base_config(tmp: Path, bundle: Path, custody_path: Path, key_path: Path, **overrides) -> Path:
    password = tmp / "password"
    password.write_text("pw", encoding="utf-8")
    config = {
        "schema_version": 1, "kind": "nexolab-dr-isolated-restore", "mode": "rehearsal",
        "media": {"bundle": str(bundle), "custody_receipt": str(custody_path)},
        "key_file": str(key_path), "work_dir": str(tmp / "work"), "evidence_dir": str(tmp / "evidence"),
        "resource_prefix": "nx-dr-unit-test",
        "images": {"telemetry": "t:1", "postgres": "p:1", "object_storage": "o:1", "mqtt": "m:1"},
        "production_hosts": ["192.0.2.10"],
        "local_auth": {"username": "admin", "password_file": str(password), "organization_id": ORG},
    }
    config.update(overrides)
    path = tmp / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class FakeDocker:
    """Records every docker invocation; fails on the first verb in ``fail_on``."""

    def __init__(self, fail_on: tuple[str, ...] = ()) -> None:
        self.calls: list[list[str]] = []
        self.binary = "docker"
        self.fail_on = fail_on

    def __call__(self, *args, input_bytes=None, stdin=None, check=True, timeout=600):
        self.calls.append(list(args))
        verb = " ".join(args[:2])
        if any(verb.startswith(prefix) for prefix in self.fail_on):
            raise ir.RestoreFailed(f"fake failure on {verb}")
        if args[0] == "info":
            out = json.dumps({"ID": "engine", "Architecture": "x86_64", "KernelVersion": "6"})
        elif args[:2] == ("network", "inspect"):
            out = json.dumps([{"Internal": True}])
        elif args[0] == "inspect":
            out = json.dumps([{"HostConfig": {"PortBindings": {}}, "State": {"Running": True}}])
        elif args[:2] == ("image", "inspect"):
            out = json.dumps([{"Id": "sha256:" + "1" * 64, "Architecture": "amd64", "RepoDigests": []}])
        else:
            out = ""
        return subprocess.CompletedProcess(list(args), 0, out.encode(), b"")

    def json(self, *args):
        return json.loads(self(*args).stdout.decode())

    def mutating_calls(self) -> list[list[str]]:
        read_only = {("info",), ("ps",), ("volume", "ls"), ("network", "ls"), ("image", "inspect")}
        return [c for c in self.calls if (c[0],) not in read_only and tuple(c[:2]) not in read_only]


def isolated(*_args, **_kwargs):
    return False


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.bundle, self.manifest = build_bundle(self.media)
        self.key = self.tmp / "key"
        self.key.write_bytes(KEY)
        self.key.chmod(0o600)
        self.custody = custody_for(self.bundle, self.manifest)
        self.custody_path = self.media / oc.receipt_name(self.bundle.name)
        self.custody_path.write_bytes(drs.canonical_json(self.custody))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def restore(self, docker: FakeDocker | None = None, connect=isolated, resolve=lambda _h: [], **overrides):
        config = ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key, **overrides))
        return ir.Restore(config, docker=docker or FakeDocker(), environ={}, resolve=resolve, connect=connect)


class CustodyTests(Fixture):
    def test_valid_custody_binds_bundle_key_and_manifest(self) -> None:
        inputs = ir.verify_custody(bundle_path=self.bundle, custody=self.custody, key=KEY)
        self.assertEqual(inputs["bundle_sha256"], self.custody["bundle_sha256"])
        verified = drs.verify_file(self.bundle, KEY)
        self.assertEqual(ir.bind_source_manifest(self.custody, verified.manifest),
                         "in_stream_manifest_canonical_sha256")
        entries = ir.compare_stream_with_manifest(verified.entries, verified.manifest)
        self.assertEqual(set(entries), set(ENTRIES))

    def test_missing_receipt_field_is_refused(self) -> None:
        broken = dict(self.custody)
        del broken["readback_sha256"]
        with self.assertRaises(ir.Refused):
            ir.verify_custody(bundle_path=self.bundle, custody=broken, key=KEY)

    def test_unexpected_receipt_field_is_refused(self) -> None:
        with self.assertRaises(ir.Refused):
            ir.verify_custody(bundle_path=self.bundle, custody={**self.custody, "extra": 1}, key=KEY)

    def test_bundle_hash_mismatch_is_refused(self) -> None:
        tampered = bytearray(self.bundle.read_bytes())
        tampered[-1] ^= 1
        self.bundle.write_bytes(bytes(tampered))
        with self.assertRaisesRegex(ir.Refused, "does not match the custody receipt"):
            ir.verify_custody(bundle_path=self.bundle, custody=self.custody, key=KEY)

    def test_receipt_with_other_hash_is_refused(self) -> None:
        other = custody_for(self.bundle, self.manifest, bundle_sha256="0" * 64, readback_sha256="0" * 64)
        with self.assertRaisesRegex(ir.Refused, "hash/size"):
            ir.verify_custody(bundle_path=self.bundle, custody=other, key=KEY)

    def test_wrong_key_is_refused_before_decryption(self) -> None:
        with self.assertRaisesRegex(ir.Refused, "key file does not match"):
            ir.verify_custody(bundle_path=self.bundle, custody=self.custody, key=bytes(32))

    def test_wrong_key_fails_stream_authentication(self) -> None:
        with self.assertRaises(drs.StreamFailure):
            drs.verify_file(self.bundle, bytes(32))

    def test_bundle_name_mismatch_is_refused(self) -> None:
        renamed = self.media / "nexolab-dr-20261122T100000Z-ffffff.nxs"
        self.bundle.rename(renamed)
        with self.assertRaisesRegex(ir.Refused, "name"):
            ir.verify_custody(bundle_path=renamed, custody=self.custody, key=KEY)

    def test_manifest_binding_mismatch_is_refused(self) -> None:
        verified = drs.verify_file(self.bundle, KEY)
        with self.assertRaisesRegex(ir.Refused, "source_manifest_sha256"):
            ir.bind_source_manifest({**self.custody, "source_manifest_sha256": "e" * 64}, verified.manifest)

    def test_stream_entry_not_matching_manifest_is_refused(self) -> None:
        verified = drs.verify_file(self.bundle, KEY)
        manifest = json.loads(json.dumps(verified.manifest))
        manifest["stores"][0]["sha256"] = "f" * 64
        with self.assertRaises(ir.Refused):
            ir.compare_stream_with_manifest(verified.entries, manifest)

    def test_incomplete_store_list_is_refused(self) -> None:
        verified = drs.verify_file(self.bundle, KEY)
        manifest = json.loads(json.dumps(verified.manifest))
        manifest["stores"] = manifest["stores"][:-1]
        with self.assertRaisesRegex(ir.Refused, "eight stores"):
            ir.compare_stream_with_manifest(verified.entries, manifest)

    def test_optional_leaf_a_receipt_must_agree(self) -> None:
        verified = drs.verify_file(self.bundle, KEY)
        backup = {"schema_version": 1, "kind": "nexolab-dr-backup-receipt", "format": drs.FORMAT,
                  "created_at": CREATED, "key_fingerprint": drs.key_fingerprint(KEY),
                  "bundle": {"file": self.bundle.name, "size": self.custody["bundle_bytes"],
                             "sha256": self.custody["bundle_sha256"]},
                  "stores": [dict(s, duration_seconds=1.0) for s in verified.manifest["stores"]]}
        kwargs = {"bundle_name": self.bundle.name, "bundle_sha256": self.custody["bundle_sha256"],
                  "bundle_bytes": self.custody["bundle_bytes"], "key": KEY, "manifest": verified.manifest}
        ir.cross_check_backup_receipt(backup, **kwargs)
        backup["bundle"]["sha256"] = "0" * 64
        with self.assertRaises(ir.Refused):
            ir.cross_check_backup_receipt(backup, **kwargs)


class ExtractTests(Fixture):
    def test_path_traversal_in_bundle_fails_and_leaves_no_plaintext(self) -> None:
        evil, _ = build_bundle(self.tmp, unsafe_path="../escape.dump")
        staging = self.tmp / "work" / "plaintext"
        with self.assertRaises(ir.RestoreFailed):
            with ir.plaintext_session(evil, KEY, staging):
                self.fail("must not yield")
        self.assertFalse(staging.exists())
        self.assertFalse((self.tmp / "work" / "escape.dump").exists())

    def test_plaintext_removed_after_success_and_after_failure(self) -> None:
        staging = self.tmp / "plain-ok"
        with ir.plaintext_session(self.bundle, KEY, staging) as (directory, _):
            self.assertTrue((directory / "local-auth" / "private.pem").exists())
        self.assertFalse(staging.exists())
        staging = self.tmp / "plain-fail"
        with self.assertRaises(RuntimeError):
            with ir.plaintext_session(self.bundle, KEY, staging):
                raise RuntimeError("restore step failed")
        self.assertFalse(staging.exists())

    def test_existing_staging_directory_is_refused(self) -> None:
        staging = self.tmp / "exists"
        staging.mkdir()
        with self.assertRaises(ir.Refused):
            with ir.plaintext_session(self.bundle, KEY, staging):
                pass


class IsolationTests(Fixture):
    def test_production_endpoint_environment_is_detected(self) -> None:
        found = ir.check_environment({"NEXOLAB_API_URL": "x", "DATABASE_URL": "y", "PGHOST": "z", "HOME": "/root"})
        self.assertEqual(found, ["DATABASE_URL", "NEXOLAB_API_URL", "PGHOST"])

    def test_resolvable_or_reachable_production_is_not_isolated(self) -> None:
        resolved = ir.check_production_isolation(["nexolab-edge-01"], [22], resolve=lambda h: ["100.64.0.1"],
                                                 connect=isolated)
        self.assertFalse(resolved["isolated"])
        reachable = ir.check_production_isolation(["192.0.2.10"], [5432], resolve=lambda h: [],
                                                  connect=lambda a, p, t: p == 5432)
        self.assertFalse(reachable["isolated"])
        self.assertIn("5432", reachable["findings"][0])
        clean = ir.check_production_isolation(["nexolab-edge-01", "192.0.2.10"], [22], resolve=lambda h: [],
                                              connect=isolated)
        self.assertTrue(clean["isolated"])

    def test_reachable_production_refuses_before_any_docker_mutation(self) -> None:
        docker = FakeDocker()
        restore = self.restore(docker, connect=lambda a, p, t: True)
        with self.assertRaisesRegex(ir.Refused, "reachable"):
            restore.run()
        self.assertEqual(docker.mutating_calls(), [])
        self.assertEqual(restore.receipt["status"], "FAIL")
        self.assertFalse((self.tmp / "work").exists())

    def test_environment_endpoint_refuses_run(self) -> None:
        config = ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key))
        restore = ir.Restore(config, docker=FakeDocker(), environ={"NEXOLAB_MQTT_HOST": "edge"},
                             resolve=lambda h: [], connect=isolated)
        with self.assertRaisesRegex(ir.Refused, "NEXOLAB_MQTT_HOST"):
            restore.run()

    def test_custody_mismatch_refuses_before_any_docker_mutation(self) -> None:
        self.custody_path.write_bytes(drs.canonical_json(
            custody_for(self.bundle, self.manifest, bundle_sha256="0" * 64, readback_sha256="0" * 64)))
        docker = FakeDocker()
        with self.assertRaisesRegex(ir.Refused, "custody receipt"):
            self.restore(docker).run()
        self.assertEqual(docker.mutating_calls(), [])

    def test_missing_custody_receipt_refuses(self) -> None:
        self.custody_path.unlink()
        docker = FakeDocker()
        with self.assertRaisesRegex(ir.Refused, "custody receipt"):
            self.restore(docker).run()
        self.assertEqual(docker.mutating_calls(), [])

    def test_missing_key_refuses(self) -> None:
        self.key.unlink()
        with self.assertRaises(drs.StreamFailure):
            self.restore().run()

    def test_plaintext_is_removed_when_a_restore_step_fails(self) -> None:
        docker = FakeDocker(fail_on=("run -d",))
        restore = self.restore(docker)
        with self.assertRaises(ir.RestoreFailed):
            restore.run()
        self.assertFalse((self.tmp / "work" / "plaintext").exists())
        self.assertTrue(restore.receipt["plaintext_removed_after_failure"])
        self.assertFalse((self.tmp / "work" / "runtime-secrets").exists())
        created = [c for c in docker.calls if c[:2] == ["network", "create"]]
        self.assertEqual(created[0][1:3], ["create", "--internal"])

    def test_no_container_ever_publishes_ports_or_pulls(self) -> None:
        docker = FakeDocker(fail_on=("exec",))
        with self.assertRaises(ir.RestoreFailed):
            self.restore(docker).run()
        runs = [c for c in docker.calls if c[0] == "run"]
        self.assertTrue(runs)
        for call in runs:
            self.assertNotIn("-p", call)
            self.assertNotIn("--publish", call)
            self.assertIn("never", call)

    def test_configuration_rejects_connection_strings_and_production_names(self) -> None:
        with self.assertRaisesRegex(ir.Refused, "not accepted"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key,
                                       database_url="postgresql://edge-01/nexolab"))
        with self.assertRaisesRegex(ir.Refused, "not accepted"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key,
                                       production_hosts=["mqtt://edge-01:1883"]))
        with self.assertRaisesRegex(ir.Refused, "resource_prefix"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key,
                                       resource_prefix="nexolab-central"))

    def test_site_mode_requirements_and_no_waivers(self) -> None:
        with self.assertRaisesRegex(ir.Refused, "production_hosts"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key, mode="site",
                                       production_hosts=[]))
        with self.assertRaisesRegex(ir.Refused, "require_internet_disconnected"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key, mode="site",
                                       require_internet_disconnected=False))
        with self.assertRaisesRegex(ir.Refused, "waivers"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key, mode="site",
                                       rehearsal_waivers=["isolation.production_unreachable"],
                                       verification={"source_observation": str(self.tmp / "obs.json"),
                                                     "dashboards": [{"id": ORG, "from": CREATED, "to": CREATED}]}))
        with self.assertRaisesRegex(ir.Refused, "source observation"):
            ir.load_config(base_config(self.tmp, self.bundle, self.custody_path, self.key, mode="site"))

    def test_teardown_only_removes_labelled_prefixed_resources(self) -> None:
        class Lister(FakeDocker):
            def __call__(self, *args, **kwargs):
                self.calls.append(list(args))
                listing = args[0] in ("ps",) or args[:2] in (("volume", "ls"), ("network", "ls"))
                names = "nx-dr-unit-test-postgres\nnexolab-central-postgres-1\n" if listing else ""
                return subprocess.CompletedProcess(list(args), 0, names.encode(), b"")
        docker = Lister()
        removed = ir.teardown(docker, "nx-dr-unit-test")
        self.assertEqual(removed["containers"], ["nx-dr-unit-test-postgres"])
        self.assertFalse(any("nexolab-central-postgres-1" in c for c in docker.calls if "rm" in c))
        self.assertTrue(all(f"label={ir.LABEL}=nx-dr-unit-test" in c for c in docker.calls
                            if c[0] in ("ps",) or c[1:2] == ["ls"]))
        with self.assertRaises(ir.Refused):
            ir.teardown(docker, "nexolab-central")


class VerificationTests(unittest.TestCase):
    ARCHIVE = (
        "SET statement_timeout = 0;\n"
        "COPY public.telemetry_samples (id, event_id, node_id, captured_at, metric, equipment_id, channel_id) FROM stdin;\n"
        "1\te1\tedge-01\t2026-11-20 06:00:00+00\ttemperature\tSIM-1\tair\n"
        "2\te2\tedge-01\t2026-11-20 07:00:00.5+02\ttemperature\tSIM-1\tair\n"
        "3\te3\tedge-02\t2026-11-20 05:00:00+00\thumidity\tSIM-2\trh\n"
        "\\.\n"
        "COPY public.\"Odd Table\" (id) FROM stdin;\n"
        "\\.\n"
        "COPY public.live_dashboards (id, view_settings) FROM stdin;\n"
        "d1\t{\"range_kind\": \"custom\"}\n"
        "\\.\n"
    )

    def test_archive_row_counts_and_latest_per_channel(self) -> None:
        parsed = ir.parse_archive_data(io.StringIO(self.ARCHIVE))
        self.assertEqual(parsed["table_counts"], {"public.telemetry_samples": 3, "public.Odd Table": 0,
                                                  "public.live_dashboards": 1})
        self.assertEqual(parsed["latest_captured_at"]["edge-01|SIM-1|air|temperature"],
                         "2026-11-20T06:00:00.000000Z")
        self.assertEqual(parsed["latest_captured_at"]["edge-02|SIM-2|rh|humidity"], "2026-11-20T05:00:00.000000Z")

    def test_truncated_archive_fails(self) -> None:
        with self.assertRaises(ir.RestoreFailed):
            ir.parse_archive_data(io.StringIO("COPY public.t (id) FROM stdin;\n1\n"))

    def test_altered_row_count_is_detected_and_fails_status(self) -> None:
        archive = {"public.telemetry_samples": 5760, "public.live_dashboards": 1}
        restored = {"public.telemetry_samples": 5759, "public.live_dashboards": 1}
        diffs = ir.compare_counts(archive, restored)
        self.assertEqual(diffs, [{"table": "public.telemetry_samples", "archive": 5760, "restored": 5759}])
        self.assertEqual(ir.compare_counts(archive, {"public.telemetry_samples": 5760})[0]["restored"], None)
        checks = passing_checks()
        checks.items[[i["name"] for i in checks.items].index("postgresql.row_counts_equal_archive")]["passed"] = False
        self.assertEqual(ir.evaluate_status(checks, rehearsal=False), "FAIL")

    def test_latest_difference_is_detected(self) -> None:
        self.assertTrue(ir.compare_latest({"a": "2026-01-01T00:00:00.000000Z"}, {"a": "2025-12-31T00:00:00.000000Z"}))

    def test_status_requires_every_mandatory_check(self) -> None:
        self.assertEqual(ir.evaluate_status(passing_checks(), rehearsal=False), "PASS")
        self.assertEqual(ir.evaluate_status(passing_checks(), rehearsal=True), "REHEARSAL_PASS")
        partial = ir.Checks([i for i in passing_checks().items if i["name"] != "local_auth.login_with_restored_keys"])
        self.assertEqual(ir.evaluate_status(partial, rehearsal=False), "FAIL")
        listing_only = ir.Checks([{"name": "postgresql.restored", "passed": True, "detail": "pg_restore --list"}])
        self.assertEqual(ir.evaluate_status(listing_only, rehearsal=False), "FAIL")

    def test_waived_check_is_visible_and_never_site_pass(self) -> None:
        checks = ir.Checks(waivers=frozenset({"isolation.production_unreachable"}))
        for item in passing_checks().items:
            checks.add(item["name"], item["name"] != "isolation.production_unreachable")
        self.assertEqual(checks.waived(), ["isolation.production_unreachable"])
        self.assertEqual(ir.evaluate_status(checks, rehearsal=True), "REHEARSAL_PASS_WITH_WAIVERS")
        self.assertEqual(ir.evaluate_status(checks, rehearsal=False), "FAIL")

    def test_rpo_rto_and_objective_gaps(self) -> None:
        created = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)
        started = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
        ready = started + timedelta(seconds=754.5)
        result = ir.compute_rpo_rto(backup_created_at=created, restore_started_at=started, ready_at=ready,
                                    newest_data_at=created - timedelta(seconds=30),
                                    objectives={"software_rpo_seconds": 0, "software_restore_target_seconds": 600})
        self.assertEqual(result["rto_seconds"], 754.5)
        self.assertEqual(result["rpo_seconds"], (ready - created).total_seconds())
        self.assertEqual(result["gaps"]["rto_gap_seconds"], 154.5)
        self.assertFalse(result["gaps"]["rto_objective_met"])
        self.assertFalse(result["gaps"]["rpo_objective_met"])
        self.assertEqual(result["newest_restored_sample_age_seconds"], (ready - created).total_seconds() + 30)
        not_ready = ir.compute_rpo_rto(backup_created_at=created, restore_started_at=started, ready_at=None,
                                       newest_data_at=None, objectives={})
        self.assertIsNone(not_ready["rto_seconds"])

    def test_source_observation_growth_is_explained_but_excess_fails(self) -> None:
        backup = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
        observation = {"table_counts": {"public.telemetry_samples": 110, "public.security_audit_events": 4},
                       "latest_captured_at": {"c1": "2026-11-22T10:30:00.000000Z", "c2": "2026-11-22T09:00:00Z"}}
        ok = ir.compare_with_observation(observation, {"public.telemetry_samples": 100,
                                                       "public.security_audit_events": 4},
                                         {"c1": "2026-11-22T09:59:00.000000Z", "c2": "2026-11-22T09:00:00.000000Z"},
                                         backup)
        self.assertTrue(ok["passed"])
        self.assertEqual(len(ok["explained_by_consistency_boundary"]), 2)
        bad = ir.compare_with_observation(observation, {"public.telemetry_samples": 111,
                                                        "public.security_audit_events": 4},
                                          {"c2": "2026-11-22T08:00:00.000000Z"}, backup)
        self.assertFalse(bad["passed"])
        self.assertEqual(len(bad["failures"]), 2)

    def test_domain_mapping_reuses_existing_sql(self) -> None:
        mapping = ir.parse_domain_tables((ROOT / "scripts" / "disaster-recovery-domain-counts.sql").read_text())
        self.assertEqual(mapping["equipment_images"], "public.equipment_images")
        self.assertEqual(mapping["nodes"], "public.central_nodes")

    def test_timestamp_normalisation(self) -> None:
        for value in ("2026-11-20 08:00:00+02", "2026-11-20T06:00:00+00:00", "2026-11-20T06:00:00Z",
                      "2026-11-20 06:00:00.000000+00"):
            self.assertEqual(ir.normalize_timestamp(value), "2026-11-20T06:00:00.000000Z")


def passing_checks() -> "ir.Checks":
    checks = ir.Checks()
    for name in ir.REQUIRED_CHECKS:
        checks.add(name, True)
    return checks


def receipt_payload(evidence_class: str, status: str) -> dict:
    stores = {s: ir.store_verification_block(s, {"ok": True}, True) for s in ir.V2_STORES}
    pair = ir.store_verification_block("local-auth-keypair", {"pair": True}, True)
    stores["local-auth-private-key"] = stores["local-auth-public-key"] = pair
    return {"kind": ir.RECEIPT_KIND, "evidence_class": evidence_class, "status": status,
            "checks": passing_checks().items, "stores": stores,
            "target": {"identity_sha256": "a" * 64}, "inputs": {"destination_identity_sha256": "d" * 64}}


class ReceiptTests(unittest.TestCase):
    def test_receipt_hash_sidecar_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path, digest = ir.write_receipt(receipt_payload("LOCAL_REHEARSAL_NOT_SITE_EVIDENCE", "REHEARSAL_PASS"),
                                            Path(tmp))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            result = ir.verify_receipt_file(path)
            self.assertTrue(result["sidecar_matches"] and result["status_consistent"])
            data = json.loads(path.read_text())
            data["status"] = "PASS"
            path.write_text(json.dumps(data))
            result = ir.verify_receipt_file(path)
            self.assertFalse(result["sidecar_matches"])
            self.assertFalse(result["status_consistent"])

    def test_rehearsal_never_sets_isolated_restore_verified(self) -> None:
        fields = ir.v2_fields(receipt_payload("LOCAL_REHEARSAL_NOT_SITE_EVIDENCE", "REHEARSAL_PASS"), "b" * 64)
        self.assertFalse(fields["storage"]["isolated_restore_verified"])
        self.assertTrue(all(a["status"] == "unverified" for a in fields["assets_restore"].values()))
        self.assertIn("not site evidence", fields["note"])

    def test_site_pass_fields_match_the_v2_inventory_contract(self) -> None:
        fields = ir.v2_fields(receipt_payload("SITE_ISOLATED_RESTORE", "PASS"), "b" * 64)
        storage = fields["storage"]
        self.assertTrue(storage["isolated_restore_verified"])
        self.assertEqual(storage["restore_target_kind"], "isolated_host")
        self.assertNotEqual(storage["restore_target_identity_sha256"], storage["destination_identity_sha256"])
        self.assertTrue({"isolated_restore_verified", "restore_target_kind", "restore_target_identity_sha256",
                         "restore_receipt_sha256"} <= v2.STORAGE_FIELDS)
        for store, block in fields["assets_restore"].items():
            self.assertEqual(set(block), v2.RESTORE_FIELDS, store)
            self.assertEqual(block["status"], "verified")
        self.assertEqual(fields["assets_restore"]["local-auth-private-key"]["verification_sha256"],
                         fields["assets_restore"]["local-auth-public-key"]["verification_sha256"])

    def test_rehearsal_statement_is_explicit(self) -> None:
        self.assertIn("NOT site evidence", ir.REHEARSAL_STATEMENT)


if __name__ == "__main__":
    unittest.main()
