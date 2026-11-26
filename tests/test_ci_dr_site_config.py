"""#1786 (#1428 DR-A): site DR config renderer resolves every CONFIRM- value from docker inspect, fails closed."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "nexolab-dr-site-config.py"
TEMPLATE = ROOT / "infrastructure" / "systemd" / "nexolab-dr-backup.example.json"
BACKUP = ROOT / "scripts" / "nexolab-dr-scheduled-backup.py"

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("dr_site_config", TOOL)
site = importlib.util.module_from_spec(spec)
sys.modules["dr_site_config"] = site
spec.loader.exec_module(site)


def container(name: str, mounts: list[tuple[str, str, str]], env: list[str] | None = None, workdir: str = "/") -> dict:
    return {"Name": "/" + name, "Config": {"Env": env or [], "WorkingDir": workdir},
            "Mounts": [{"Type": kind, "Source": source, "Destination": dest, "RW": True} for kind, source, dest in mounts]}


class SiteConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.vol = {}
        for name in ("versitygw", "central-mqtt", "edge-mqtt", "edge-data", "spool"):
            path = root / "volumes" / name / "_data"
            path.mkdir(parents=True)
            self.vol[name] = path
        (self.vol["versitygw"] / "bucket").mkdir()
        (self.vol["versitygw"] / "bucket" / "obj").write_bytes(b"x" * 100)
        (self.vol["edge-data"] / "edge.db").write_bytes(b"sqlite" * 10)
        (self.vol["spool"] / "spool.db").write_bytes(b"sqlite")
        self.containers = {
            "nexolab-central-postgres-1": container("nexolab-central-postgres-1", [],
                                                    ["POSTGRES_USER=nexolab", "POSTGRES_DB=nexolab", "POSTGRES_PASSWORD=s3cret"]),
            "nexolab-central-minio-1": container("nexolab-central-minio-1", [("volume", str(self.vol["versitygw"]), "/data")]),
            "nexolab-central-mqtt-1": container("nexolab-central-mqtt-1", [
                ("volume", str(self.vol["central-mqtt"]), "/mosquitto/data"),
                ("bind", "/srv/mosquitto.conf", "/mosquitto/config/mosquitto.conf")]),
            "nexolab-edge-mqtt-1": container("nexolab-edge-mqtt-1", [("volume", str(self.vol["edge-mqtt"]), "/mosquitto/data")]),
            "nexolab-edge-device-agent-1": container("nexolab-edge-device-agent-1", [
                ("volume", str(self.vol["edge-data"]), "/var/lib/nexolab")], ["DEVICE_MODE=modbus"]),
            "nexolab-central-telemetry-service-1": container("nexolab-central-telemetry-service-1", [
                ("volume", str(self.vol["spool"]), "/app/data/telemetry-ingestion"),
                ("bind", "/home/x/private.pem", "/run/secrets/nexolab_local_auth_private_key"),
                ("bind", "/home/x/public.pem", "/run/secrets/nexolab_local_auth_public_key")],
                ["AUTH_LOCAL_PRIVATE_KEY_FILE=/run/secrets/nexolab_local_auth_private_key"], "/app"),
        }
        self.template = json.loads(TEMPLATE.read_text())

    def render(self):
        return site.render(self.template, self.containers, Path("/usr/local/lib/nexolab-dr"))

    def test_every_confirm_value_is_resolved_from_the_live_mounts(self) -> None:
        config, report = self.render()
        text = json.dumps(config)
        self.assertNotIn("CONFIRM-", text)
        self.assertNotIn("_comment", config)
        stores = {s["id"]: s for s in config["stores"]}
        self.assertEqual(stores["object-storage"]["path"], str(self.vol["versitygw"]))
        self.assertEqual(stores["edge-sqlite-outbox"]["path"], str(self.vol["edge-data"] / "edge.db"))
        self.assertEqual(stores["central-ingestion-spool"]["path"], str(self.vol["spool"] / "spool.db"))
        self.assertEqual(stores["local-auth-private-key"]["argv"],
                         ["docker", "exec", "nexolab-central-telemetry-service-1", "cat",
                          "/run/secrets/nexolab_local_auth_private_key"])
        self.assertEqual(stores["local-auth-public-key"]["argv"][-1], "/run/secrets/nexolab_local_auth_public_key")
        pg = stores["postgresql"]["argv"]
        self.assertEqual(pg[pg.index("-U") + 1], "nexolab")
        self.assertEqual(pg[pg.index("-d") + 1], "nexolab")
        self.assertEqual(config["source_commit_file"], "/usr/local/lib/nexolab-dr/SOURCE_COMMIT")
        self.assertNotIn("s3cret", text)  # no environment value other than the PostgreSQL identifiers
        sizes = {e["id"]: e.get("bytes") for e in report}
        self.assertEqual(sizes["object-storage"], 100)

    @unittest.skipUnless(importlib.util.find_spec("cryptography"), "backup tool needs cryptography")
    def test_rendered_config_passes_the_backup_tool_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "SOURCE_COMMIT").write_text("a" * 40 + "\n")
            config, _ = site.render(self.template, self.containers, Path(temp))
            path = Path(temp) / "dr-backup.json"
            path.write_text(json.dumps(config))
            os.chmod(path, 0o600)
            spec = importlib.util.spec_from_file_location("dr_backup", BACKUP)
            backup = importlib.util.module_from_spec(spec)
            sys.modules["dr_backup"] = backup
            spec.loader.exec_module(backup)
            loaded = backup.load_config(path)  # full validation incl. pg_dump / docker exec allow-lists
            self.assertEqual(len(loaded.stores), 8)

    def test_relative_spool_path_resolves_against_the_working_directory(self) -> None:
        self.containers["nexolab-central-telemetry-service-1"]["Config"]["Env"].append(
            "INGESTION_SPOOL_PATH=data/telemetry-ingestion/spool.db")
        config, _ = self.render()
        stores = {s["id"]: s for s in config["stores"]}
        self.assertEqual(stores["central-ingestion-spool"]["path"], str(self.vol["spool"] / "spool.db"))

    def test_fails_closed(self) -> None:
        cases = []
        missing = dict(self.containers)
        del missing["nexolab-central-minio-1"]
        cases.append(missing)
        no_mount = json.loads(json.dumps(self.containers))
        no_mount["nexolab-edge-mqtt-1"]["Mounts"] = []
        cases.append(no_mount)
        outside = json.loads(json.dumps(self.containers))
        outside["nexolab-edge-device-agent-1"]["Config"]["Env"] = ["DATABASE_PATH=/tmp/edge.db"]
        cases.append(outside)
        two_keys = json.loads(json.dumps(self.containers))
        two_keys["nexolab-central-telemetry-service-1"]["Mounts"].append(
            {"Type": "bind", "Source": "/x", "Destination": "/run/secrets/other_local_auth_private_key", "RW": False})
        cases.append(two_keys)
        bad_ident = json.loads(json.dumps(self.containers))
        bad_ident["nexolab-central-postgres-1"]["Config"]["Env"] = ["POSTGRES_USER=x;rm"]
        cases.append(bad_ident)
        for containers in cases:
            with self.assertRaises(site.Blocked):
                site.render(self.template, containers, Path("/usr/local/lib/nexolab-dr"))
        (self.vol["spool"] / "spool.db").unlink()
        with self.assertRaises(site.Blocked):
            self.render()

    def test_store_over_cap_blocks(self) -> None:
        with self.assertRaises(site.Blocked):
            site.render(self.template, self.containers, Path("/x"), size_of=lambda _p: 10**12)

    def test_cli_report_only_and_exclusive_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            inspect = Path(temp) / "inspect.json"
            inspect.write_text(json.dumps(list(self.containers.values())))
            out = Path(temp) / "dr-backup.json"
            base = [sys.executable, "-I", "-B", str(TOOL), "--template", str(TEMPLATE), "--inspect-json", str(inspect)]
            report = subprocess.run(base, capture_output=True, text=True, timeout=60)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("DR_SITE_CONFIG_RESOLVED", report.stdout)
            self.assertFalse(out.exists())
            written = subprocess.run(base + ["--output", str(out)], capture_output=True, text=True, timeout=60)
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")
            again = subprocess.run(base + ["--output", str(out)], capture_output=True, text=True, timeout=60)
            self.assertEqual(again.returncode, 78)
            self.assertIn("OUTPUT_EXISTS", again.stderr)

    def test_only_docker_inspect_is_used(self) -> None:
        source = TOOL.read_text()
        code = source.split('"""', 2)[2]
        # The only command it runs is `docker inspect`; `docker exec ... cat` appears only as config DATA
        # for the backup tool's allow-listed key capture.
        self.assertEqual(re.findall(r"subprocess\.\w+\((\[[^\]]*)", code), ['["docker", "inspect", "--type", "container", "--", *names'])
        for forbidden in ("shell=True", "os.system", "unlink", "rmtree", "Popen"):
            self.assertNotIn(forbidden, code)


import re  # noqa: E402  (used by the static test above)

if __name__ == "__main__":
    unittest.main()
