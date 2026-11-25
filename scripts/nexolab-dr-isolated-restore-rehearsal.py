#!/usr/bin/env python3
"""#1632 local end-to-end rehearsal of the isolated restore (opt-in, Docker required).

Builds a SYNTHETIC "production" (PostgreSQL 16 at Alembic head with telemetry samples, a Saved
Dashboard with view_settings, a local-auth account and keys, an equipment image in VersityGW,
Mosquitto Dynamic Security, edge SQLite outbox, ingestion spool, edge MQTT persistence), runs the
existing leaf-A orchestrator ``nexolab-dr-scheduled-backup.py`` against it inside a Linux
container, copies the bundle to a second directory with the real leaf-C ``copy_bundle`` (only the
device-identity probe is simulated: a PC has one disk), then runs ``nexolab-dr-isolated-restore.py``
in ``mode=rehearsal`` (plus two negative restores) and tears everything down. Every Docker resource it creates carries an ``nx-dr-`` prefix and a run label; nothing else
is touched.

This is a REHEARSAL on a development machine. It is NOT site evidence for #1632/#1428.

Usage:
  python scripts/nexolab-dr-isolated-restore-rehearsal.py --workspace <new empty dir> \
      --telemetry-image nx-dr/telemetry:rehearsal --object-storage-image nx-dr/object-storage:rehearsal \
      --mqtt-image nx-dr/mqtt:rehearsal
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
ORG = "00000000-0000-0000-0000-000000001632"
USERNAME = "rehearsal-admin"
BUCKET = "nexolab-equipment-images"
WINDOW = ("2026-11-20T06:00:00Z", "2026-11-20T18:00:00Z")
BACKUP_RUNNER_DOCKERFILE = (
    "FROM docker:27.5.1-cli\n"
    "RUN apk add --no-cache python3 py3-cryptography\n"
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


restore_tool = _load("nexolab_dr_isolated_restore", "nexolab-dr-isolated-restore.py")


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}", flush=True)


def docker(*args: str, input_bytes: bytes | None = None, check: bool = True,
           timeout: float = 1800) -> subprocess.CompletedProcess:
    result = subprocess.run(["docker", *args], input=input_bytes, capture_output=True, timeout=timeout, check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"docker {' '.join(args[:3])} failed ({result.returncode}): "
                         f"{result.stderr.decode('utf-8', 'replace')[-800:]}")
    return result


SAMPLES_SQL = """
INSERT INTO telemetry_samples (event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload, raw_payload_retained)
SELECT (md5('nx-dr-rehearsal-' || c.channel_id || '-' || i)::uuid)::text, c.node_id,
  timestamptz '2026-11-20 00:00:00+00' + make_interval(mins => i), c.metric,
  round((c.base + sin(i / 30.0) * c.amp)::numeric, 3)::float8, c.unit, 'valid', 'dr-rehearsal',
  c.equipment_id, c.channel_id, NULL, (c.base * 10)::int, 0, json_build_object('i', i), true
FROM generate_series(0, 1439) AS i
CROSS JOIN (VALUES
  ('edge-01', 'SIM-DR-01', 'ambient-temperature', 'temperature', 'degC', 4.0, 1.5),
  ('edge-01', 'SIM-DR-01', 'evaporator-temperature', 'temperature', 'degC', -18.0, 2.0),
  ('edge-01', 'SIM-DR-02', 'active-power', 'active_power', 'W', 850.0, 120.0),
  ('edge-02', 'SIM-DR-03', 'room-humidity', 'relative_humidity', '%', 55.0, 6.0)
) AS c(node_id, equipment_id, channel_id, metric, unit, base, amp);

INSERT INTO telemetry_latest (sample_id, event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, stale_after_seconds, received_at)
SELECT DISTINCT ON (node_id, equipment_id, channel_id, metric) id, event_id, node_id, captured_at, metric, value,
  unit, quality, source, equipment_id, channel_id, alarm, raw_value, raw_status, NULL, received_at
FROM telemetry_samples ORDER BY node_id, equipment_id, channel_id, metric, captured_at DESC, id DESC;

INSERT INTO central_nodes (id, organization_id, node_id, display_name, created_by, created_at, updated_at)
VALUES ('16320000-0000-0000-0000-0000000000e1', '%(org)s', 'edge-01', 'Rehearsal edge 01', 'dr-rehearsal', now(), now()),
       ('16320000-0000-0000-0000-0000000000e2', '%(org)s', 'edge-02', 'Rehearsal edge 02', 'dr-rehearsal', now(), now());

INSERT INTO security_audit_events (id, organization_id, actor_subject, actor_roles, action, entity_type,
  entity_id, after_snapshot, reason, request_id, source_ip, user_agent)
VALUES ('16320000-0000-0000-0000-000000000001', '%(org)s', 'dr-rehearsal', '["administrator"]'::json,
  'backup.seed', 'disaster_recovery', 'nexolab-dr-stream-v1', '{"rehearsal":true}'::json,
  'Seed isolated restore rehearsal', 'dr-rehearsal-001', '127.0.0.1', 'nexolab-dr-rehearsal');
""".replace("%(org)s", ORG)

SOURCE_API = r'''
import io, json, sys, uuid, urllib.error, urllib.request
from PIL import Image
cfg = json.loads(sys.stdin.read())
base = "http://127.0.0.1:8082"
def call(path, token=None, payload=None, body=None, content_type=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-Organization-ID"] = cfg["organization_id"]
    data = None
    if payload is not None:
        data = json.dumps(payload).encode(); headers["Content-Type"] = "application/json"
    if body is not None:
        data = body; headers["Content-Type"] = content_type
    request = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{path}: HTTP {error.code}: {error.read()[:600]!r}")
tokens = call("/api/v1/auth/local/login", payload={"username": cfg["username"], "password": cfg["password"]})
token = tokens["access_token"]
dashboard = call("/api/v1/live-dashboards", token=token, payload={
    "name": "DR rehearsal cold room", "description": "#1632 rehearsal saved dashboard",
    "refresh_seconds": 5, "time_window": "24h",
    "items": [
        {"node_id": "edge-01", "equipment_id": "SIM-DR-01", "channel_id": "ambient-temperature", "metric": "temperature", "visualization": "line", "color": "#1F77B4"},
        {"node_id": "edge-01", "equipment_id": "SIM-DR-01", "channel_id": "evaporator-temperature", "metric": "temperature", "visualization": "area"},
        {"node_id": "edge-01", "equipment_id": "SIM-DR-02", "channel_id": "active-power", "metric": "active_power", "visualization": "line"},
    ],
    "view_settings": {"schema_version": 1, "range_kind": "custom", "range_from": cfg["window"][0],
                      "range_to": cfg["window"][1], "hidden_items": [], "density": 500},
})
canvas = Image.new("RGB", (32, 24), (12, 90, 160))
buffer = io.BytesIO(); canvas.save(buffer, format="PNG"); png = buffer.getvalue()
boundary = "nxdr" + uuid.uuid4().hex
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"cold-room.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{boundary}--\r\n".encode()
image = call("/api/v1/equipment/SIM-DR-01/images", token=token, body=body,
             content_type=f"multipart/form-data; boundary={boundary}")
call("/api/v1/auth/local/logout", payload={"refresh_token": tokens["refresh_token"]})
print(json.dumps({"dashboard_id": dashboard["id"], "image_id": image["id"], "dashboard_items": len(dashboard["items"])}))
'''

SEED_FILES = r'''
import json, os, sqlite3, sys
kind = sys.argv[1]
if kind == "outbox":
    con = sqlite3.connect("/target/outbox.sqlite")
    con.execute("CREATE TABLE outbox (id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, payload TEXT NOT NULL, sent INTEGER NOT NULL)")
    con.executemany("INSERT INTO outbox (event_id, payload, sent) VALUES (?, ?, ?)",
                    [(f"evt-{i:05d}", json.dumps({"i": i}), int(i % 3 == 0)) for i in range(250)])
    con.commit(); con.close()
elif kind == "spool":
    con = sqlite3.connect("/target/spool.db")
    con.execute("CREATE TABLE spool (id INTEGER PRIMARY KEY, received_at TEXT NOT NULL, payload BLOB NOT NULL)")
    con.executemany("INSERT INTO spool (received_at, payload) VALUES (?, ?)",
                    [(f"2026-11-21T00:00:{i:02d}Z", os.urandom(64)) for i in range(40)])
    con.commit(); con.close()
    os.chown("/target/spool.db", 10001, 10001)
elif kind == "edge-mqtt":
    os.makedirs("/target/clients", exist_ok=True)
    with open("/target/mosquitto.db", "wb") as f:
        f.write(b"MOSQUITTO-SYNTHETIC-PERSISTENCE" + os.urandom(4096))
    with open("/target/clients/edge-01.state", "w") as f:
        f.write("queued=17\n")
    os.chown("/target", 1883, 1883)
elif kind == "secrets":
    for name in ("mqtt-admin-password", "ingestion-password", "edge-01-password"):
        with open(f"/target/{name}", "w") as f:
            f.write(sys.argv[2 + ("mqtt-admin-password", "ingestion-password", "edge-01-password").index(name)])
        os.chmod(f"/target/{name}", 0o444)
    with open("/target/local-auth-password", "w") as f:
        f.write(sys.argv[5])
    os.chmod("/target/local-auth-password", 0o444)
elif kind == "backup-etc":
    import shutil
    shutil.copyfile("/host/dr-backup.key", "/target/dr-backup.key"); os.chmod("/target/dr-backup.key", 0o600)
    shutil.copyfile("/host/dr-backup.json", "/target/dr-backup.json"); os.chmod("/target/dr-backup.json", 0o600)
elif kind == "copy-out":
    import shutil
    names = sorted(n for n in os.listdir("/target") if n.endswith(".nxs") or n.endswith(".receipt.json"))
    for name in names:
        shutil.copyfile(os.path.join("/target", name), os.path.join("/host", name))
    print(json.dumps(names))
'''


class Rehearsal:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.ws: Path = args.workspace
        self.src = args.source_prefix
        self.label = ["--label", f"{restore_tool.LABEL}={self.src}"]
        self.net = f"{self.src}-net"
        self.vol = {name: f"{self.src}-{name}" for name in (
            "postgres-data", "object-storage-data", "mqtt-data", "edge-mqtt-data", "edge-data", "ingestion-data",
            "secrets", "backup-out", "backup-etc")}
        self.ctr = {name: f"{self.src}-{name}" for name in ("postgres", "object-storage", "mqtt", "telemetry")}
        self.timings: dict[str, float] = {}

    # ------------------------------------------------------------------ helpers
    def helper(self, volume: str, code: str, *argv: str, host_dir: Path | None = None, read_only: bool = False) -> str:
        args = ["run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0", *self.label,
                "-v", f"{volume}:/target{':ro' if read_only else ''}"]
        if host_dir is not None:
            args += ["-v", f"{host_dir}:/host"]
        args += ["--entrypoint", "python", self.args.telemetry_image, "-c", code, *argv]
        return docker(*args).stdout.decode().strip()

    def env_file(self, name: str, values: dict[str, str]) -> Path:
        path = self.ws / "private" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        return path

    def wait(self, what: str, argv: list[str], timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if docker(*argv, check=False).returncode == 0:
                return
            time.sleep(1)
        raise SystemExit(f"timed out waiting for {what}")

    def psql(self, sql: str) -> str:
        return docker("exec", "-i", "-e", "PGTZ=UTC", self.ctr["postgres"], "psql", "-X", "-q", "-At", "-v",
                      "ON_ERROR_STOP=1", "-U", "nexolab", "-d", "nexolab", input_bytes=sql.encode()).stdout.decode()

    # ------------------------------------------------------------------ source
    def build_source(self) -> dict[str, Any]:
        args = self.args
        started = time.monotonic()
        log("source: network and volumes")
        docker("network", "create", "--internal", *self.label, self.net)
        for volume in self.vol.values():
            docker("volume", "create", *self.label, volume)
        self.pg_password = secrets.token_urlsafe(24)
        self.os_access, self.os_secret = "nxdrsrc" + secrets.token_hex(4), secrets.token_urlsafe(24)
        mqtt_admin, ingestion, edge01 = (secrets.token_urlsafe(18) for _ in range(3))
        self.local_password = secrets.token_urlsafe(18)
        custody = self.ws / "key-custody"
        custody.mkdir(parents=True)
        (custody / "local-auth-password").write_text(self.local_password, encoding="utf-8")
        self.helper(self.vol["secrets"], SEED_FILES, "secrets", mqtt_admin, ingestion, edge01, self.local_password)
        docker("run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0", *self.label, "-v",
               f"{self.vol['secrets']}:/secrets", "--entrypoint", "sh", args.telemetry_image, "-ec",
               "python -m app.security.local_cli generate-keys --private-key-file /secrets/local-auth-private.pem "
               "--public-key-file /secrets/local-auth-public.pem >/dev/null && chown 10001:10001 /secrets/*.pem && "
               "chmod 0400 /secrets/local-auth-private.pem && chmod 0444 /secrets/local-auth-public.pem")
        log("source: PostgreSQL 16 + Alembic head")
        pg_env = self.env_file("src-postgres.env", {"POSTGRES_USER": "nexolab", "POSTGRES_DB": "nexolab",
                                                    "POSTGRES_PASSWORD": self.pg_password})
        docker("run", "-d", "--pull", "never", "--name", self.ctr["postgres"], "--network", self.net, *self.label,
               "--env-file", str(pg_env), "-v", f"{self.vol['postgres-data']}:/var/lib/postgresql/data",
               args.postgres_image)
        self.wait("source PostgreSQL", ["exec", self.ctr["postgres"], "pg_isready", "-h", "127.0.0.1", "-U", "nexolab"])
        db_url = f"postgresql+psycopg://nexolab:{self.pg_password}@{self.ctr['postgres']}:5432/nexolab"
        app_env = self.env_file("src-app.env", {"DATABASE_URL": db_url, "MQTT_ENABLED": "false",
                                                "OBJECT_STORAGE_BACKEND": "disabled", "RETENTION_ENABLED": "false"})
        run_app = ["run", "--rm", "--pull", "never", "--network", self.net, *self.label, "--env-file", str(app_env),
                   "-v", f"{self.vol['secrets']}:/run/secrets/nexolab:ro", args.telemetry_image]
        docker(*run_app, "alembic", "upgrade", "head")
        docker(*run_app, "python", "-m", "app.security.local_cli", "create-account", "--username", USERNAME,
               "--password-file", "/run/secrets/nexolab/local-auth-password", "--display-name",
               "DR Rehearsal Administrator", "--organization-id", ORG, "--organization-slug", "nexolab-dr-rehearsal",
               "--organization-name", "NEXOLAB DR Rehearsal", "--role", "administrator")
        self.psql(SAMPLES_SQL)
        log("source: VersityGW object storage + telemetry service")
        os_env = self.env_file("src-os.env", {"ROOT_ACCESS_KEY_ID": self.os_access, "ROOT_SECRET_ACCESS_KEY":
                                              self.os_secret, "VGW_PORT": ":9000", "VGW_REGION": "us-east-1",
                                              "VGW_HEALTH": "/health", "VGW_QUIET": "true"})
        docker("run", "-d", "--pull", "never", "--name", self.ctr["object-storage"], "--network", self.net,
               *self.label, "--env-file", str(os_env), "--read-only", "-v",
               f"{self.vol['object-storage-data']}:/data", args.object_storage_image, "posix", "/data")
        s3_env = self.env_file("src-s3.env", {"OBJECT_STORAGE_ACCESS_KEY_ID": self.os_access,
                                              "OBJECT_STORAGE_SECRET_ACCESS_KEY": self.os_secret,
                                              "OBJECT_STORAGE_REGION": "us-east-1"})
        endpoint = f"http://{self.ctr['object-storage']}:9000"
        s3 = ["run", "--rm", "--pull", "never", "--network", self.net, *self.label, "--env-file", str(s3_env), "-v",
              f"{SCRIPTS}:/opt/nexolab/scripts:ro", "--entrypoint", "python", args.telemetry_image,
              "/opt/nexolab/scripts/object-storage-s3.py", "--endpoint", endpoint]
        deadline = time.monotonic() + 60
        while docker(*s3, "ensure-bucket", "--bucket", BUCKET, check=False).returncode != 0:
            if time.monotonic() > deadline:
                raise SystemExit("source object storage did not become available")
            time.sleep(1)
        docker(*s3, "assert-private", "--bucket", BUCKET)
        tele_env = self.env_file("src-telemetry.env", {
            "DATABASE_URL": db_url, "MQTT_ENABLED": "false", "BROKER_CONTROL_ENABLED": "false",
            "RETENTION_ENABLED": "false", "OBJECT_STORAGE_BACKEND": "s3", "OBJECT_STORAGE_BUCKET": BUCKET,
            "OBJECT_STORAGE_ENDPOINT_URL": endpoint, "OBJECT_STORAGE_PUBLIC_ENDPOINT_URL": endpoint,
            "OBJECT_STORAGE_REGION": "us-east-1", "OBJECT_STORAGE_ACCESS_KEY_ID": self.os_access,
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": self.os_secret, "OBJECT_STORAGE_FORCE_PATH_STYLE": "true",
            "AUTH_MODE": "jwt", "AUTH_DEFAULT_ORGANIZATION_ID": ORG, "AUTH_LOCAL_ENABLED": "true",
            "AUTH_LOCAL_PRIVATE_KEY_FILE": "/run/secrets/local-auth/local-auth-private.pem",
            "AUTH_LOCAL_PUBLIC_KEY_FILE": "/run/secrets/local-auth/local-auth-public.pem",
            "AUTH_LOCAL_ISSUER": "urn:nexolab:local", "AUTH_LOCAL_AUDIENCE": "nexolab-api",
            "AUTH_LOCAL_PROVIDER": "nexolab-local", "CORS_ALLOWED_ORIGINS": ""})
        docker("run", "-d", "--pull", "never", "--name", self.ctr["telemetry"], "--network", self.net, *self.label,
               "--env-file", str(tele_env), "-v", f"{self.vol['secrets']}:/run/secrets/local-auth:ro", "-v",
               f"{self.vol['ingestion-data']}:/app/data/telemetry-ingestion", args.telemetry_image)
        ready = ["exec", self.ctr["telemetry"], "python", "-c",
                 "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8082/health/ready',timeout=3)"]
        self.wait("source telemetry /health/ready", ready, 180)
        log("source: Saved Dashboard with view_settings + equipment image through the API")
        payload = json.dumps({"username": USERNAME, "password": self.local_password, "organization_id": ORG,
                              "window": list(WINDOW)}).encode()
        created = json.loads(docker("exec", "-i", self.ctr["telemetry"], "python", "-c", SOURCE_API,
                                    input_bytes=payload).stdout.decode().strip().splitlines()[-1])
        log("source: Mosquitto Dynamic Security, SQLite outbox/spool, edge MQTT persistence")
        mqtt_env = self.env_file("src-mqtt.env", {
            "NEXOLAB_MQTT_ADMIN_USERNAME": "nexolab-dr-admin", "NEXOLAB_MQTT_ADMIN_CLIENT_ID": "nexolab-dr-admin-cli",
            "NEXOLAB_MQTT_ADMIN_PASSWORD_FILE": "/run/secrets/nexolab/mqtt-admin-password"})
        docker("run", "-d", "--pull", "never", "--name", self.ctr["mqtt"], "--network", self.net, *self.label,
               "--env-file", str(mqtt_env), "-v", f"{self.vol['mqtt-data']}:/mosquitto/data", "-v",
               f"{self.vol['secrets']}:/run/secrets/nexolab:ro", args.mqtt_image)
        self.wait("source MQTT", ["exec", self.ctr["mqtt"], "/usr/local/bin/nexolab-dynsec-admin", "list-clients"], 60)
        admin = ["exec", self.ctr["mqtt"], "/usr/local/bin/nexolab-dynsec-admin"]
        docker(*admin, "bootstrap-defaults")
        docker(*admin, "create-ingestion", "nexolab-central-ingestion", "nexolab-central-ingestion",
               "/run/secrets/nexolab/ingestion-password")
        docker(*admin, "create-node", f"node:{ORG}:edge-01", f"nexolab-{ORG}-edge-01", ORG, "edge-01",
               "/run/secrets/nexolab/edge-01-password")
        self.helper(self.vol["edge-data"], SEED_FILES, "outbox")
        self.helper(self.vol["ingestion-data"], SEED_FILES, "spool")
        self.helper(self.vol["edge-mqtt-data"], SEED_FILES, "edge-mqtt")
        self.timings["build_source_seconds"] = round(time.monotonic() - started, 1)
        return created

    # ------------------------------------------------------------------ leaf A
    def run_leaf_a(self) -> dict[str, Any]:
        args = self.args
        log("leaf A: building the backup runner image (docker CLI + python3 + cryptography)")
        docker("build", "-q", "-t", args.backup_runner_image, "-", input_bytes=BACKUP_RUNNER_DOCKERFILE.encode())
        custody = self.ws / "key-custody"
        key = secrets.token_bytes(32)
        (custody / "dr-backup.key").write_bytes(key)
        os.chmod(custody / "dr-backup.key", 0o600)
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
        config = {
            "schema_version": 1, "kind": "nexolab-dr-scheduled-backup", "repository": "eNgine9r/nexolab-platform",
            "source_commit": commit, "output_dir": "/var/backups/nexolab/dr", "key_file": "/etc/nexolab/dr-backup.key",
            "lock_file": "/run/nexolab-dr-backup/backup.lock", "reserve_free_bytes": 21474836480,
            "max_backup_bytes": 1073741824, "verify_after_capture": True,
            "stores": [
                {"id": "postgresql", "method": "docker_exec_stream", "format": "pg_custom",
                 "entry_path": "postgresql/nexolab.dump", "max_bytes": 536870912,
                 "argv": ["docker", "exec", self.ctr["postgres"], "nice", "-n", "19", "pg_dump", "-U", "nexolab",
                          "-d", "nexolab", "-Fc", "-Z", "3"]},
                {"id": "object-storage", "method": "directory_snapshot", "format": "volume_tar",
                 "entry_path": "object-storage/objects.tar", "max_bytes": 134217728, "path": "/src/object-storage"},
                {"id": "mqtt-dynamic-security", "method": "directory_snapshot", "format": "volume_tar",
                 "entry_path": "mqtt/mosquitto-data.tar", "max_bytes": 67108864, "path": "/src/mqtt"},
                {"id": "edge-mqtt-persistence", "method": "directory_snapshot", "format": "volume_tar",
                 "entry_path": "edge-mqtt/mosquitto-data.tar", "max_bytes": 67108864, "path": "/src/edge-mqtt"},
                {"id": "edge-sqlite-outbox", "method": "sqlite_online", "format": "sqlite",
                 "entry_path": "edge/outbox.sqlite", "max_bytes": 67108864, "path": "/src/edge/outbox.sqlite"},
                {"id": "central-ingestion-spool", "method": "sqlite_online", "format": "sqlite",
                 "entry_path": "central/ingestion-spool.sqlite", "max_bytes": 67108864,
                 "path": "/src/ingestion/spool.db"},
                {"id": "local-auth-private-key", "method": "docker_exec_stream", "format": "pem",
                 "entry_path": "local-auth/private.pem", "max_bytes": 65536,
                 "argv": ["docker", "exec", self.ctr["telemetry"], "cat",
                          "/run/secrets/local-auth/local-auth-private.pem"]},
                {"id": "local-auth-public-key", "method": "docker_exec_stream", "format": "pem",
                 "entry_path": "local-auth/public.pem", "max_bytes": 65536,
                 "argv": ["docker", "exec", self.ctr["telemetry"], "cat",
                          "/run/secrets/local-auth/local-auth-public.pem"]},
            ],
        }
        staging = self.ws / "private" / "backup-etc"
        staging.mkdir(parents=True)
        (staging / "dr-backup.key").write_bytes(key)
        (staging / "dr-backup.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        self.helper(self.vol["backup-etc"], SEED_FILES, "backup-etc", host_dir=staging)
        (staging / "dr-backup.key").unlink()
        log("leaf A: running scripts/nexolab-dr-scheduled-backup.py (unmodified) in a Linux container")
        started = time.monotonic()
        result = docker(
            "run", "--rm", "--pull", "never", "--network", "none", *self.label,
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "-v", f"{self.vol['backup-etc']}:/etc/nexolab:ro",
            "-v", f"{self.vol['backup-out']}:/var/backups/nexolab/dr",
            "-v", f"{self.vol['object-storage-data']}:/src/object-storage:ro",
            "-v", f"{self.vol['mqtt-data']}:/src/mqtt:ro",
            "-v", f"{self.vol['edge-mqtt-data']}:/src/edge-mqtt:ro",
            "-v", f"{self.vol['edge-data']}:/src/edge:ro",
            "-v", f"{self.vol['ingestion-data']}:/src/ingestion:ro",
            "-v", f"{SCRIPTS}:/opt/nexolab/scripts:ro",
            "--entrypoint", "python3", args.backup_runner_image, "-I", "-B",
            "/opt/nexolab/scripts/nexolab-dr-scheduled-backup.py", "--config", "/etc/nexolab/dr-backup.json",
            check=False, timeout=3600)
        self.timings["leaf_a_backup_seconds"] = round(time.monotonic() - started, 1)
        output = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
        log(f"leaf A exit {result.returncode}: {output[-600:]}")
        if result.returncode != 0:
            raise SystemExit("leaf A backup failed")
        return json.loads(result.stdout.decode().strip().splitlines()[-1])

    # ------------------------------------------------------------------ leaf C stub
    def run_leaf_c(self) -> dict[str, Path]:
        """Runs the REAL leaf-C code (#1631 copy_bundle) from the 'Pi' directory to a second directory.

        Only the device-identity probe is simulated (this PC has one disk; leaf C correctly refuses a
        same-disk destination). Verification, streaming copy, read-back and the canonical custody
        receipt are produced by the unmodified leaf-C implementation.
        """
        log("leaf C: real nexolab-dr-offdevice-copy.py copy_bundle (simulated device identities only)")
        pi_dir, media, receipts = self.ws / "pi-backup", self.ws / "media", self.ws / "pi-custody-receipts"
        pi_dir.mkdir()
        media.mkdir()
        names = json.loads(self.helper(self.vol["backup-out"], SEED_FILES, "copy-out", host_dir=pi_dir,
                                       read_only=True).splitlines()[-1])
        bundle = pi_dir / next(n for n in names if n.endswith(".nxs"))
        leaf_a_receipt = pi_dir / next(n for n in names if n.endswith(".receipt.json"))
        key_file = self.ws / "key-custody" / "dr-backup.key"
        oc = restore_tool.offdevice

        def probe(path: Path):
            resolved = Path(path).resolve()
            if resolved == media.resolve() or media.resolve() in resolved.parents:
                return oc.Volume("dev:8:17", "block:sdb", False, "uuid-rehearsal-usb-ssd")
            if resolved == key_file.resolve().parent or resolved == key_file.resolve():
                return oc.Volume("dev:8:33", "block:sdc", False, "uuid-rehearsal-key-stick")
            return oc.Volume("dev:8:2", "block:sda", False, "uuid-rehearsal-pi-root")

        oc.enroll(media, "dedicated_media", "rehearsal-usb-ssd", probe=probe)
        receipt = oc.copy_bundle(bundle, key_file, media, receipts, source_receipt=leaf_a_receipt, probe=probe,
                                 free=lambda _path: 64 * 1024**3)
        custody_path = media / oc.receipt_name(bundle.name)
        self.leaf_c_receipt = receipt
        return {"bundle": media / bundle.name, "custody": custody_path, "pi_bundle": bundle}

    # ------------------------------------------------------------------ observation
    def observe_source(self, created: dict[str, Any]) -> Path:
        log("source observation (read-only): dashboard CSV via API + table counts/latest via SQL")
        dashboards = [{"id": created["dashboard_id"], "from": WINDOW[0], "to": WINDOW[1], "timezone": "UTC"}]
        payload = json.dumps({"username": USERNAME, "password": self.local_password, "organization_id": ORG,
                              "dashboards": dashboards, "images": []}).encode()
        probe = json.loads(docker("exec", "-i", self.ctr["telemetry"], "python", "-c", restore_tool.PROBE,
                                  input_bytes=payload).stdout.decode().strip().splitlines()[-1])
        db = json.loads([line for line in self.psql(restore_tool.OBSERVE_SQL).splitlines() if line.startswith("{")][-1])
        observation = {
            "schema_version": 1, "kind": restore_tool.OBSERVATION_KIND,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "organization_id": ORG, "table_counts": db["table_counts"], "latest_captured_at": db["latest_captured_at"],
            "dashboards": [{k: d.get(k) for k in ("id", "from", "to", "timezone", "csv_sha256", "csv_rows",
                                                   "view_settings_sha256")} for d in probe["dashboards"]],
        }
        # S3 metadata on the SOURCE gateway, to compare with the restored one (VersityGW xattr finding).
        keys = json.loads(self.psql("SELECT COALESCE(json_agg(storage_key), '[]')::text FROM equipment_images;")
                          .strip().splitlines()[-1])
        head = docker("run", "--rm", "-i", "--pull", "never", "--network", self.net, *self.label, "--env-file",
                      str(self.ws / "private" / "src-s3.env"), "--entrypoint", "python", self.args.telemetry_image,
                      "-c", restore_tool.S3_HEAD_PROBE, f"http://{self.ctr['object-storage']}:9000", BUCKET,
                      input_bytes=json.dumps(keys).encode())
        self.source_s3_head = json.loads(head.stdout.decode().strip().splitlines()[-1])
        # Read-only HEAD results of the source gateway: the restore compares ETag/Content-Type against them.
        observation["objects"] = [{"key": s["key"], "etag": s.get("etag"), "content_type": s.get("content_type")}
                                  for s in self.source_s3_head if s.get("status") == 200]
        path = self.ws / "observation" / "source-observation.json"
        path.parent.mkdir()
        path.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    # ------------------------------------------------------------------ restore
    def restore_config(self, media: dict[str, Path], observation: Path, name: str, *, prefix: str,
                       custody: Path | None = None, key: Path | None = None) -> Path:
        args = self.args
        config = {
            "schema_version": 1, "kind": "nexolab-dr-isolated-restore", "mode": "rehearsal",
            # Disaster case: only the off-device media survives, so no leaf-A receipt is supplied.
            "media": {"bundle": str(media["bundle"]), "custody_receipt": str(custody or media["custody"])},
            "key_file": str(key or (self.ws / "key-custody" / "dr-backup.key")),
            "work_dir": str(self.ws / f"{name}-work"), "evidence_dir": str(self.ws / f"{name}-evidence"),
            "resource_prefix": prefix,
            "images": {"telemetry": args.telemetry_image, "postgres": args.postgres_image,
                       "object_storage": args.object_storage_image, "mqtt": args.mqtt_image},
            "production_hosts": ["nexolab-edge-01", "192.0.2.10"],
            "production_probe_ports": [22, 1883, 5432, 8082],
            "require_internet_disconnected": False,
            # This development PC reaches the real edge-01 over Tailscale; the waiver is recorded in the
            # receipt status (REHEARSAL_PASS_WITH_WAIVERS) and is impossible in mode=site.
            "rehearsal_waivers": ["isolation.production_unreachable"],
            "local_auth": {"username": USERNAME, "password_file": str(self.ws / "key-custody" / "local-auth-password"),
                           "organization_id": ORG},
            "verification": {"source_observation": str(observation)},
            "ready_timeout_seconds": 600,
        }
        path = self.ws / f"{name}-config.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return path

    def restored_s3_head(self, keys: list[str]) -> dict[str, Any]:
        """Independent check of the RESTORED object volume: a second VersityGW (labelled with the restore
        prefix, internal network, rehearsal credentials) answers HEAD and stat-keys for the source keys."""
        prefix = self.args.restore_prefix
        name, network, volume = f"{prefix}-verify-gw", f"{prefix}-net", f"{prefix}-object-storage-data"
        access, secret = "nxdrverify" + secrets.token_hex(4), secrets.token_urlsafe(24)
        gw_env = self.env_file("verify-gw.env", {"ROOT_ACCESS_KEY_ID": access, "ROOT_SECRET_ACCESS_KEY": secret,
                                                 "VGW_PORT": ":9000", "VGW_REGION": "us-east-1",
                                                 "VGW_HEALTH": "/health", "VGW_QUIET": "true"})
        s3_env = self.env_file("verify-s3.env", {"OBJECT_STORAGE_ACCESS_KEY_ID": access,
                                                 "OBJECT_STORAGE_SECRET_ACCESS_KEY": secret,
                                                 "OBJECT_STORAGE_REGION": "us-east-1"})
        docker("run", "-d", "--pull", "never", "--name", name, "--network", network, "--label",
               f"{restore_tool.LABEL}={prefix}", "--env-file", str(gw_env), "--read-only", "-v", f"{volume}:/data",
               self.args.object_storage_image, "posix", "/data")
        endpoint = f"http://{name}:9000"
        client = ["run", "--rm", "-i", "--pull", "never", "--network", network, "--label",
                  f"{restore_tool.LABEL}={prefix}", "--env-file", str(s3_env), "-v", f"{SCRIPTS}:/opt/nexolab/scripts:ro",
                  "--entrypoint", "python", self.args.telemetry_image]
        try:
            docker(*client, "/opt/nexolab/scripts/object-storage-s3.py", "--endpoint", endpoint, "wait", timeout=120)
            head = docker(*client, "-c", restore_tool.S3_HEAD_PROBE, endpoint, BUCKET,
                          input_bytes=json.dumps(keys).encode())
            stat = docker(*client, "/opt/nexolab/scripts/object-storage-s3.py", "--endpoint", endpoint, "stat-keys",
                          "--bucket", BUCKET, "--keys-file", "/dev/stdin",
                          input_bytes="".join(f"{key}\n" for key in keys).encode(), check=False)
        finally:
            docker("rm", "-f", name, check=False)
        return {"head": json.loads(head.stdout.decode().strip().splitlines()[-1]),
                "stat_keys_exit": stat.returncode,
                "stat_keys": [json.loads(line) for line in stat.stdout.decode().splitlines() if line.startswith("{")],
                "stat_keys_stderr_tail": stat.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]}

    def run_restore(self, config: Path, *extra: str) -> tuple[int, str]:
        result = subprocess.run([sys.executable, str(SCRIPTS / "nexolab-dr-isolated-restore.py"), "restore",
                                 "--config", str(config), *extra], capture_output=True, text=True, timeout=7200)
        return result.returncode, (result.stdout + result.stderr).strip()

    def negatives(self, media: dict[str, Path], observation: Path) -> dict[str, Any]:
        results = {}
        tampered = json.loads(media["custody"].read_text(encoding="utf-8"))
        tampered["bundle_sha256"] = tampered["readback_sha256"] = "0" * 64  # still schema-valid
        bad_custody = self.ws / "negative" / "tampered.custody.json"
        bad_custody.parent.mkdir()
        bad_custody.write_text(json.dumps(tampered), encoding="utf-8")
        wrong_key = self.ws / "negative" / "wrong.key"
        wrong_key.write_bytes(secrets.token_bytes(32))
        for name, kwargs in (("negative-hash", {"custody": bad_custody}), ("negative-key", {"key": wrong_key})):
            config = self.restore_config(media, observation, name, prefix=f"{self.args.restore_prefix}-n", **kwargs)
            code, output = self.run_restore(config)
            leaked = docker("ps", "-a", "--filter", f"label={restore_tool.LABEL}={self.args.restore_prefix}-n",
                            "--format", "{{.Names}}").stdout.decode().split()
            expected = {"negative-hash": "does not match the custody receipt",
                        "negative-key": "key file does not match"}[name]
            results[name] = {"exit": code, "refused": code == 78 and expected in output, "resources_created": leaked,
                             "plaintext_dir_exists": (self.ws / f"{name}-work" / "plaintext").exists(),
                             "reason": output.splitlines()[-1][:300] if output else ""}
            log(f"{name}: exit {code} (expected 78)")
        return results

    def teardown_all(self) -> dict[str, Any]:
        docker_tool = restore_tool.Docker()
        removed = {"restore": restore_tool.teardown(docker_tool, self.args.restore_prefix),
                   "negative": restore_tool.teardown(docker_tool, f"{self.args.restore_prefix}-n"),
                   "source": restore_tool.teardown(docker_tool, self.src)}
        leftovers = [n for n in docker("ps", "-a", "--format", "{{.Names}}").stdout.decode().split()
                     + docker("volume", "ls", "--format", "{{.Name}}").stdout.decode().split()
                     + docker("network", "ls", "--format", "{{.Name}}").stdout.decode().split()
                     if n.startswith((self.src, self.args.restore_prefix))]
        removed["leftovers"] = leftovers
        return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-prefix", default="nx-dr-rehearsal-src")
    parser.add_argument("--restore-prefix", default="nx-dr-rehearsal-rst")
    parser.add_argument("--telemetry-image", default="nx-dr/telemetry:rehearsal")
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--object-storage-image", default="nx-dr/object-storage:rehearsal")
    parser.add_argument("--mqtt-image", default="nx-dr/mqtt:rehearsal")
    parser.add_argument("--backup-runner-image", default="nx-dr/backup-runner:rehearsal")
    parser.add_argument("--keep", action="store_true", help="keep all rehearsal resources for inspection")
    args = parser.parse_args(argv)
    for prefix in (args.source_prefix, args.restore_prefix):
        if not restore_tool.PREFIX.fullmatch(prefix):
            raise SystemExit("prefixes must match nx-dr-<name>")
    if args.workspace.exists():
        raise SystemExit("workspace must not exist")
    args.workspace.mkdir(parents=True)
    rehearsal = Rehearsal(args)
    summary: dict[str, Any] = {"statement": restore_tool.REHEARSAL_STATEMENT}
    code = 1
    try:
        created = rehearsal.build_source()
        summary["source"] = created
        summary["leaf_a"] = rehearsal.run_leaf_a()
        media = rehearsal.run_leaf_c()
        summary["leaf_c"] = rehearsal.leaf_c_receipt
        observation = rehearsal.observe_source(created)
        summary["source_s3_head"] = rehearsal.source_s3_head
        summary["negative"] = rehearsal.negatives(media, observation)
        log("restore: nexolab-dr-isolated-restore.py restore (mode=rehearsal)")
        config = rehearsal.restore_config(media, observation, "restore", prefix=args.restore_prefix)
        code, output = rehearsal.run_restore(config)
        log(f"restore exit {code}: {output[-1500:]}")
        summary["restore_exit"] = code
        receipt_path = args.workspace / "restore-evidence" / "nexolab-dr-isolated-restore-receipt.json"
        if receipt_path.exists():
            summary["receipt_verify"] = restore_tool.verify_receipt_file(receipt_path)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            summary["restore_object_storage_s3"] = receipt.get("object_storage_s3")
        if code == 0:
            keys = [s["key"] for s in rehearsal.source_s3_head if s.get("status") == 200]
            summary["restored_s3_head"] = rehearsal.restored_s3_head(keys)
            source = {s["key"]: (s.get("etag"), s.get("content_type")) for s in rehearsal.source_s3_head}
            restored = {s["key"]: (s.get("etag"), s.get("content_type")) for s in summary["restored_s3_head"]["head"]}
            summary["metadata_equal_source"] = bool(source) and source == restored
            log(f"object metadata source={source} restored={restored} "
                f"stat-keys exit={summary['restored_s3_head']['stat_keys_exit']}")
            if not summary["metadata_equal_source"] or summary["restored_s3_head"]["stat_keys_exit"] != 0:
                code = 1
        negatives_ok = all(item["refused"] and not item["resources_created"] and not item["plaintext_dir_exists"]
                           for item in summary["negative"].values())
        code = 0 if code == 0 and negatives_ok else 1
    finally:
        summary["timings"] = rehearsal.timings
        shutil.rmtree(args.workspace / "private", ignore_errors=True)  # synthetic source secrets
        if not args.keep:
            summary["teardown"] = rehearsal.teardown_all()
            log(f"teardown leftovers: {summary['teardown']['leftovers']}")
        (args.workspace / "rehearsal-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                                               encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
