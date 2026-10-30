"""NEXOLAB #1435: all Docker probes are mocked; no site or privileged actions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "nexolab-site-dr-preflight.py"
SPEC = importlib.util.spec_from_file_location("site_dr_preflight", PATH)
assert SPEC and SPEC.loader
dr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dr)

IMAGE = "sha256:" + "a" * 64
ID = "f" * 64
CREATED = "2026-10-14T09:23:17Z"


def valid_runner(*, mutate=None):
    services = {
        "nexolab-central": ["postgres", "minio", "mqtt", "telemetry-service"],
        "nexolab-edge": ["device-agent", "mqtt"],
    }
    volumes = {
        ("nexolab-central", "postgres"): [("volume", "nexolab-central-postgres-data", "/var/lib/postgresql/data")],
        ("nexolab-central", "minio"): [("volume", "nexolab-central-object-storage-versitygw-data", "/data")],
        ("nexolab-central", "mqtt"): [("volume", "nexolab-central-mqtt-data", "/mosquitto/data")],
        ("nexolab-central", "telemetry-service"): [("volume", "nexolab-central-telemetry-ingestion-data", "/app/data/telemetry-ingestion")],
        ("nexolab-edge", "device-agent"): [("volume", "nexolab-edge_edge-data", "/var/lib/nexolab")],
        ("nexolab-edge", "mqtt"): [("volume", "nexolab-edge_mqtt-data", "/mosquitto/data")],
    }
    if mutate:
        mutate(services, volumes)
    identity = {}
    for project, names in services.items():
        for i, name in enumerate(names):
            identity[f"{project}:{name}"] = f"{(i + 1 if project == 'nexolab-central' else i + 10):012x}"

    def run(args):
        if args[0] == "ps":
            project = args[3].split("=", 1)[1]
            return "\n".join(identity[f"{project}:{s}"] for s in services[project])
        if args[0] == "inspect" and "range .Mounts" not in args[2]:
            ident = args[-1]
            keys = [key for key, value in identity.items() if value == ident]
            if len(keys) != 1:
                raise dr.PreflightBlocked("unknown test identity")
            proj, service = keys[0].split(":", 1)
            return f"{ident:0>64}|{IMAGE}|{proj}|{service}|running"
        if args[0] == "inspect" and "range .Mounts" in args[2]:
            ident = args[-1]
            keys = [key for key, value in identity.items() if value == ident]
            if len(keys) != 1:
                raise dr.PreflightBlocked("ambiguous fixture")
            proj, service = keys[0].split(":", 1)
            return "\n".join("|".join(x) for x in volumes[(proj, service)])
        if args[:2] == ["volume", "inspect"]:
            return CREATED
        raise dr.PreflightBlocked("unapproved Docker command")

    return run


def authority(path: Path, *, status="verified", created=CREATED, image=IMAGE):
    obj = {
        "schema_version": 1,
        "kind": "nexolab-object-storage-migration",
        "status": status,
        "cutover_verified": True,
        "target_volume_created_at": created,
        "target_image_id": image,
    }
    path.write_text(json.dumps(obj), encoding="utf-8")


class SiteDRPreflightTests(unittest.TestCase):
    def test_readonly_probe_observes_all_eight_protected_assets(self):
        data = dr.probe_sources(valid_runner())
        self.assertEqual(set(data), set(dr.SOURCES))
        self.assertEqual(data["object-storage"]["source_volume"], "nexolab-central-object-storage-versitygw-data")
        self.assertEqual(data["mqtt-dynamic-security"]["compose_project"], "nexolab-central")
        self.assertEqual(data["edge-mqtt-persistence"]["compose_project"], "nexolab-edge")
        self.assertEqual(data["central-ingestion-spool"]["disposition"], "unclassified")
        self.assertEqual(data["local-auth-private-key"]["secret_mount_presence"], "unverified")
        self.assertEqual(data["postgresql"]["capture_status"], "unverified")

    def test_probe_runs_only_readonly_docker_argv(self):
        seen = []
        real = valid_runner()

        def audited(args):
            seen.append(args)
            return real(args)

        dr.probe_sources(audited)
        self.assertTrue(seen)
        self.assertTrue(all(args[0] in ("ps", "inspect") for args in seen))
        self.assertFalse(any("env" in str(args) for args in seen))
        self.assertFalse(any("-f" in args for args in seen))
        self.assertFalse(any("exec" in args for args in seen))

    def test_missing_critical_service_is_blocked(self):
        def mutate(services, _):
            services["nexolab-edge"].remove("device-agent")

        with self.assertRaisesRegex(dr.PreflightBlocked, "required Compose service missing"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_duplicate_service_fails_closed(self):
        def mutate(services, _):
            services["nexolab-central"].append("mqtt")

        with self.assertRaisesRegex(dr.PreflightBlocked, "duplicate"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_wrong_legacy_minio_volume_fails_closed(self):
        def mutate(_, volumes):
            volumes[("nexolab-central", "minio")] = [
                ("volume", "nexolab-central-object-storage-data", "/data")
            ]

        with self.assertRaisesRegex(dr.PreflightBlocked, "ambiguous protected volume"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_missing_edge_sqlite_volume_fails_closed(self):
        def mutate(_, volumes):
            volumes[("nexolab-edge", "device-agent")] = []

        with self.assertRaisesRegex(dr.PreflightBlocked, "ambiguous protected volume"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_wrong_edge_mqtt_volume_fails_closed(self):
        def mutate(_, volumes):
            volumes[("nexolab-edge", "mqtt")] = [
                ("volume", "nexolab-central-mqtt-data", "/mosquitto/data")
            ]

        with self.assertRaisesRegex(dr.PreflightBlocked, "ambiguous protected volume"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_no_named_volume_for_protected_store_fails(self):
        def mutate(_, volumes):
            volumes[("nexolab-central", "postgres")] = [("bind", "", "/var/lib/postgresql/data")]

        with self.assertRaisesRegex(dr.PreflightBlocked, "protected volume"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_unknown_ingestion_spool_volume_fails(self):
        def mutate(_, volumes):
            volumes[("nexolab-central", "telemetry-service")] = []

        with self.assertRaisesRegex(dr.PreflightBlocked, "protected volume"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_duplicate_mount_target_fails_closed(self):
        def mutate(_, volumes):
            volumes[("nexolab-central", "postgres")].append(
                ("bind", "", "/var/lib/postgresql/data")
            )

        with self.assertRaisesRegex(dr.PreflightBlocked, "duplicate mount"):
            dr.probe_sources(valid_runner(mutate=mutate))

    def test_migration_proof_must_match_exact_image_and_volume_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "authority.json"
            authority(p)
            receipt = dr.read_migration_authority(p, CREATED, "a" * 64)
            self.assertRegex(receipt, "^[0-9a-f]{64}$")
            with self.assertRaisesRegex(dr.PreflightBlocked, "creation identity"):
                dr.read_migration_authority(p, "wrong", "a" * 64)
            with self.assertRaisesRegex(dr.PreflightBlocked, "image authority"):
                dr.read_migration_authority(p, CREATED, "b" * 64)

    def test_migration_authority_rejected_before_cutover(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "authority.json"
            authority(p, status="pending")
            with self.assertRaisesRegex(dr.PreflightBlocked, "cutover not verified"):
                dr.read_migration_authority(p, CREATED, "a" * 64)

    def test_symlink_migration_authority_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "authority.json"
            target = Path(tmp) / "target.json"
            authority(target)
            p.symlink_to(target)
            with self.assertRaisesRegex(dr.PreflightBlocked, "unsafe"):
                dr.read_migration_authority(p, CREATED, "a" * 64)

    def test_symlink_backup_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real"
            target.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(target)
            with self.assertRaisesRegex(dr.PreflightBlocked, "real directory"):
                dr.protected_dir(link)

    def test_world_readable_backup_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup"
            path.mkdir(mode=0o755)
            with self.assertRaisesRegex(dr.PreflightBlocked, "root-owned"):
                dr.protected_dir(path)

    def test_reject_destination_with_same_root_filesystem(self):
        with patch.object(dr, "protected_dir", side_effect=[None, dr.PreflightBlocked("destination lacks distinct mounted filesystem")]):
            with self.assertRaisesRegex(dr.PreflightBlocked, "distinct mounted"):
                dr.capacity_check(Path("/unused/root"), Path("/unused/dest"))

    def test_reject_insufficient_working_headroom(self):
        with patch.object(dr, "protected_dir"), patch.object(dr.shutil, "disk_usage", side_effect=[
            type("Usage", (), {"free": 23 * dr.GiB})(),
            type("Usage", (), {"free": 18 * dr.GiB})(),
        ]):
            with self.assertRaisesRegex(dr.PreflightBlocked, "20 GiB"):
                dr.capacity_check(Path("/work"), Path("/backup"))

    def test_reject_insufficient_destination_capacity(self):
        with patch.object(dr, "protected_dir"), patch.object(dr.shutil, "disk_usage", side_effect=[
            type("Usage", (), {"free": 28 * dr.GiB})(),
            type("Usage", (), {"free": 15 * dr.GiB})(),
        ]):
            with self.assertRaisesRegex(dr.PreflightBlocked, "16 GiB"):
                dr.capacity_check(Path("/work"), Path("/backup"))

    def test_preflight_reports_unverified_not_false_backup_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            authority_path = Path(tmp) / "authority.json"
            authority(authority_path)
            with patch.object(dr, "capacity_check", return_value={"destination_key_custody": "unverified"}):
                receipt = dr.probe_site(Path("/work"), Path("/offhost"), authority_path, valid_runner())
            self.assertEqual(receipt["backup_capture"], "not_performed")
            self.assertEqual(receipt["isolated_restore"], "not_performed")
            self.assertEqual(receipt["site_activation"], "not_authorized")
            self.assertEqual(receipt["encrypted_off_device_copy"], "not_verified")
            self.assertTrue(all(a["restore_status"] == "unverified" for a in receipt["assets"].values()))
            self.assertNotIn("private.pem", json.dumps(receipt))

    def test_missing_migration_authority_blocks_site_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(dr, "capacity_check", return_value={}):
                with self.assertRaisesRegex(dr.PreflightBlocked, "missing or invalid"):
                    dr.probe_site(Path("/work"), Path("/dest"), Path(tmp) / "absent.json", valid_runner())

    def test_no_unsafe_docker_operations_in_source(self):
        source = PATH.read_text(encoding="utf-8")
        for forbidden in ("docker exec", "docker network connect", "docker compose down", "docker volume rm", "modbus write"):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
