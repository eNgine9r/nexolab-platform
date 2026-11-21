"""#1630 DR-A orchestrator tests: synthetic stores only.

No production Docker, PostgreSQL, MQTT, Raspberry Pi or hardware is touched.
Docker execution is replaced by local subprocesses or injected capture functions.
"""
from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexolab_dr_scheduled_backup",
                                              ROOT / "scripts" / "nexolab-dr-scheduled-backup.py")
assert SPEC is not None and SPEC.loader is not None
bk = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bk
SPEC.loader.exec_module(bk)
drs = bk.drs

GiB = 1024**3
KEY = bytes(range(32))
COMMIT = "b" * 40
SECRET_MARKER = b"PRIVATE-KEY-MATERIAL-MUST-NOT-LEAK"


def make_sqlite(path: Path, rows: int) -> None:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE outbox (id INTEGER PRIMARY KEY, payload TEXT)")
    connection.executemany("INSERT INTO outbox (payload) VALUES (?)", [(f"event-{i}",) for i in range(rows)])
    connection.commit()
    connection.close()


@pytest.fixture()
def site(tmp_path: Path) -> dict:
    """Synthetic eight-store site layout plus a valid configuration dict."""
    src = tmp_path / "src"
    (src / "objects" / "nexolab-equipment-images").mkdir(parents=True)
    (src / "objects" / "nexolab-equipment-images" / "a.jpg").write_bytes(os.urandom(2048))
    (src / "mqtt").mkdir()
    (src / "mqtt" / "dynamic-security.json").write_text('{"clients":[]}')
    (src / "edge-mqtt").mkdir()
    (src / "edge-mqtt" / "mosquitto.db").write_bytes(b"persist")
    (src / "keys").mkdir()
    (src / "keys" / "private.pem").write_bytes(SECRET_MARKER)
    (src / "keys" / "public.pem").write_bytes(b"public")
    make_sqlite(src / "outbox.sqlite", 50)
    make_sqlite(src / "spool.sqlite", 5)
    key = tmp_path / "dr.key"
    key.write_bytes(KEY)
    key.chmod(0o600)
    out = tmp_path / "backups"
    config = {
        "schema_version": 1,
        "kind": "nexolab-dr-scheduled-backup",
        "repository": "eNgine9r/nexolab-platform",
        "source_commit": COMMIT,
        "output_dir": str(out),
        "key_file": str(key),
        "lock_file": str(tmp_path / "run" / "backup.lock"),
        "metrics_file": str(tmp_path / "metrics" / "dr-backup.prom"),
        "reserve_free_bytes": 20 * GiB,
        "max_backup_bytes": 64 * 1024**2,
        "verify_after_capture": True,
        "stores": [
            {"id": "postgresql", "method": "docker_exec_stream", "format": "pg_custom",
             "entry_path": "postgresql/nexolab.dump", "max_bytes": 32 * 1024**2,
             "argv": ["docker", "exec", "nexolab-central-postgres-1", "nice", "-n", "19",
                      "pg_dump", "-U", "nexolab", "-d", "nexolab", "-Fc", "-Z", "3"]},
            {"id": "object-storage", "method": "directory_snapshot", "format": "volume_tar",
             "entry_path": "object-storage/objects.tar", "max_bytes": 8 * 1024**2, "path": str(src / "objects")},
            {"id": "mqtt-dynamic-security", "method": "directory_snapshot", "format": "volume_tar",
             "entry_path": "mqtt/mosquitto-data.tar", "max_bytes": 1024**2, "path": str(src / "mqtt")},
            {"id": "edge-mqtt-persistence", "method": "directory_snapshot", "format": "volume_tar",
             "entry_path": "edge-mqtt/mosquitto-data.tar", "max_bytes": 1024**2, "path": str(src / "edge-mqtt")},
            {"id": "edge-sqlite-outbox", "method": "sqlite_online", "format": "sqlite",
             "entry_path": "edge/outbox.sqlite", "max_bytes": 4 * 1024**2, "path": str(src / "outbox.sqlite")},
            {"id": "central-ingestion-spool", "method": "sqlite_online", "format": "sqlite",
             "entry_path": "central/spool.sqlite", "max_bytes": 4 * 1024**2, "path": str(src / "spool.sqlite")},
            {"id": "local-auth-private-key", "method": "file_snapshot", "format": "pem",
             "entry_path": "local-auth/private.pem", "max_bytes": 65536, "path": str(src / "keys" / "private.pem")},
            {"id": "local-auth-public-key", "method": "file_snapshot", "format": "pem",
             "entry_path": "local-auth/public.pem", "max_bytes": 65536, "path": str(src / "keys" / "public.pem")},
        ],
    }
    return {"tmp": tmp_path, "src": src, "out": out, "config": config}


def write_config(site: dict, config: dict | None = None) -> Path:
    path = site["tmp"] / "config.json"
    path.write_text(json.dumps(config or site["config"]))
    return path


PG_DUMP_BYTES = b"PGDMP" + os.urandom(100_000)


def fake_capture(store, sink):
    if store.method == "docker_exec_stream":
        sink.write(PG_DUMP_BYTES)  # stands in for `docker exec ... pg_dump -Fc`
    else:
        bk.capture_store(store, sink)


def plenty(_path) -> int:
    return 500 * GiB


# --------------------------------------------------------------- happy path


def test_complete_run_captures_all_eight_stores_and_verifies(site):
    config = bk.load_config(write_config(site))
    receipt = bk.run_backup(config, free=plenty, capture=fake_capture)

    assert receipt["status"] == "CAPTURED_RESTORE_UNVERIFIED"
    assert receipt["isolated_restore_verified"] is False
    assert receipt["off_device_copy_verified"] is False
    assert receipt["self_verified_after_capture"] is True
    assert sorted(s["id"] for s in receipt["stores"]) == sorted(bk.V2_STORES)
    bundle = site["out"] / receipt["bundle"]["file"]
    result = drs.verify_file(bundle, KEY)
    assert {e.store for e in result.entries} == set(bk.V2_STORES)
    pg = next(s for s in receipt["stores"] if s["id"] == "postgresql")
    assert pg["consistency"] == "online_logical_or_atomic_read" and pg["size"] == len(PG_DUMP_BYTES)


def test_no_plaintext_or_secret_reaches_disk(site):
    config = bk.load_config(write_config(site))
    receipt = bk.run_backup(config, free=plenty, capture=fake_capture)
    for path in site["out"].iterdir():
        content = path.read_bytes()
        assert SECRET_MARKER not in content, path.name
        assert b"PGDMP" not in content, path.name
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
    receipt_text = json.dumps(receipt)
    assert KEY.hex() not in receipt_text and "PRIVATE-KEY" not in receipt_text


def test_extracted_bundle_reproduces_sources_exactly(site):
    config = bk.load_config(write_config(site))
    receipt = bk.run_backup(config, free=plenty, capture=fake_capture)
    restored = site["tmp"] / "restore"
    drs.extract_file(site["out"] / receipt["bundle"]["file"], KEY, restored)
    assert (restored / "local-auth" / "private.pem").read_bytes() == SECRET_MARKER
    assert (restored / "postgresql" / "nexolab.dump").read_bytes() == PG_DUMP_BYTES
    rows = sqlite3.connect(restored / "edge" / "outbox.sqlite").execute("SELECT count(*) FROM outbox").fetchone()[0]
    assert rows == 50


def test_directory_snapshot_is_volume_archive_compatible(site):
    """The object tree must extract with the existing nexolab-volume-archive.py tool."""
    spec = importlib.util.spec_from_file_location("nexolab_volume_archive", ROOT / "scripts" / "nexolab-volume-archive.py")
    archive_tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive_tool)
    config = bk.load_config(write_config(site))
    receipt = bk.run_backup(config, free=plenty, capture=fake_capture)
    restored = site["tmp"] / "restore"
    drs.extract_file(site["out"] / receipt["bundle"]["file"], KEY, restored)
    target = site["tmp"] / "objects-restored"
    target.mkdir()
    archive_tool.extract_archive(restored / "object-storage" / "objects.tar", target)
    original = site["src"] / "objects" / "nexolab-equipment-images" / "a.jpg"
    assert (target / "nexolab-equipment-images" / "a.jpg").read_bytes() == original.read_bytes()


def test_rebuildable_store_may_be_excluded_only_with_reason(site):
    config = copy.deepcopy(site["config"])
    config["stores"] = [s for s in config["stores"] if s["id"] != "edge-mqtt-persistence"] + [
        {"id": "edge-mqtt-persistence", "disposition": "rebuildable_excluded",
         "reason": "QoS1 queue is rebuilt from the edge SQLite outbox"}]
    receipt = bk.run_backup(bk.load_config(write_config(site, config)), free=plenty, capture=fake_capture)
    excluded = next(s for s in receipt["stores"] if s["id"] == "edge-mqtt-persistence")
    assert excluded["disposition"] == "rebuildable_excluded" and "reason" in excluded


# --------------------------------------------------------------- fail-closed capacity


def test_preflight_refuses_when_reserve_would_be_violated(site):
    config = bk.load_config(write_config(site))
    tight = lambda _p: config.reserve_free_bytes + config.max_backup_bytes - 1  # noqa: E731
    with pytest.raises(bk.Blocked, match="capacity"):
        bk.run_backup(config, free=tight, capture=fake_capture)
    assert not site["out"].exists() or not any(site["out"].glob("*.nxs"))


def test_mid_run_reserve_violation_aborts_and_removes_only_own_partial(site):
    site["out"].mkdir()
    older = site["out"] / "nexolab-dr-20260101T000000Z.nxs"
    older.write_bytes(b"older bundle must survive")
    config = bk.load_config(write_config(site))
    calls = {"n": 0}

    def shrinking(_p):
        calls["n"] += 1
        return 500 * GiB if calls["n"] == 1 else 1 * GiB

    def big_capture(store, sink):
        if store.method == "docker_exec_stream":
            for _ in range(80):
                sink.write(b"\x00" * (1024**2))
        else:
            bk.capture_store(store, sink)

    stores = tuple(dataclasses.replace(s, max_bytes=150 * 1024**2) if s.id == "postgresql" else s
                   for s in config.stores)
    config = dataclasses.replace(config, max_backup_bytes=200 * 1024**2, stores=stores)
    with pytest.raises(bk.CaptureFailed, match="reserve"):
        bk.run_backup(config, free=shrinking, capture=big_capture)
    assert older.read_bytes() == b"older bundle must survive"
    assert sorted(p.name for p in site["out"].iterdir()) == [older.name]


def test_per_store_cap_aborts_run(site):
    config = copy.deepcopy(site["config"])
    next(s for s in config["stores"] if s["id"] == "postgresql")["max_bytes"] = 1000
    with pytest.raises(bk.CaptureFailed, match="size cap"):
        bk.run_backup(bk.load_config(write_config(site, config)), free=plenty, capture=fake_capture)
    assert not any(site["out"].iterdir())


# --------------------------------------------------------------- consistency


def test_directory_change_during_capture_fails_closed(site, monkeypatch):
    real = bk._signature
    calls = {"n": 0}

    def drifting(root):
        calls["n"] += 1
        value = real(root)
        return value + (("changed", 1, 1, 1, 1),) if calls["n"] == 2 else value

    monkeypatch.setattr(bk, "_signature", drifting)
    config = bk.load_config(write_config(site))
    with pytest.raises(bk.CaptureFailed, match="changed during capture"):
        bk.run_backup(config, free=plenty, capture=fake_capture)
    assert not any(site["out"].glob("*.nxs"))


def test_sqlite_capture_is_consistent_while_writer_is_active(site):
    """A concurrent uncommitted writer must not leak partial state into the snapshot."""
    db = site["src"] / "outbox.sqlite"
    writer = sqlite3.connect(db)
    writer.execute("BEGIN")
    writer.execute("INSERT INTO outbox (payload) VALUES ('uncommitted')")

    class Collect:
        data = bytearray()

        def write(self, chunk):
            self.data.extend(chunk)

    sink = Collect()
    bk.capture_sqlite(db, sink, 4 * 1024**2)
    writer.rollback()
    writer.close()
    snapshot = site["tmp"] / "snap.sqlite"
    snapshot.write_bytes(bytes(sink.data))
    rows = sqlite3.connect(snapshot).execute("SELECT count(*) FROM outbox").fetchone()[0]
    assert rows == 50


def test_docker_exec_failure_is_reported_without_partial_success():
    class Collect:
        def write(self, chunk):
            pass

    with pytest.raises(bk.CaptureFailed, match="exited 3"):
        bk.capture_docker_exec([sys.executable, "-c", "import sys; sys.stdout.write('x'); "
                                "sys.stderr.write('pg_dump: connection refused'); sys.exit(3)"], Collect())


def test_docker_exec_streams_large_stdout():
    received = bytearray()

    class Collect:
        def write(self, chunk):
            received.extend(chunk)

    bk.capture_docker_exec([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'z' * 3_000_000)"], Collect())
    assert len(received) == 3_000_000


# --------------------------------------------------------------- configuration safety


@pytest.mark.parametrize("argv", [
    ["docker", "stop", "nexolab-central-postgres-1"],
    ["docker", "restart", "nexolab-central-postgres-1", "pg_dump", "-Fc"],
    ["docker", "exec", "-i", "nexolab-central-postgres-1", "pg_dump", "-Fc"],
    ["docker", "exec", "--privileged", "nexolab-central-postgres-1", "pg_dump", "-Fc"],
    ["docker", "exec", "nexolab-central-postgres-1", "pg_dump"],
    ["docker", "exec", "nexolab-central-postgres-1", "pg_dump", "-Fc", "--clean"],
    ["docker", "exec", "nexolab-central-postgres-1", "pg_dump", "-Fc", "-C"],
    ["docker", "exec", "nexolab-central-postgres-1", "psql", "-c", "DROP TABLE x"],
    ["sh", "-c", "pg_dump -Fc"],
])
def test_only_read_only_docker_exec_is_accepted_for_postgresql(argv):
    with pytest.raises(bk.Blocked):
        bk.validate_docker_argv(argv, "postgresql")


def test_key_capture_command_must_be_plain_cat():
    bk.validate_docker_argv(["docker", "exec", "nexolab-central-telemetry-service-1", "cat",
                             "/run/secrets/nexolab/local-auth-public.pem"], "local-auth-public-key")
    with pytest.raises(bk.Blocked):
        bk.validate_docker_argv(["docker", "exec", "c", "rm", "/run/secrets/x"], "local-auth-public-key")


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c["stores"].pop(), "exactly once"),
    (lambda c: c["stores"].append(copy.deepcopy(c["stores"][0])), "exactly once"),
    (lambda c: c.__setitem__("reserve_free_bytes", 19 * GiB), "20 GiB"),
    (lambda c: c.__setitem__("source_commit", "abc"), "commit"),
    (lambda c: c["stores"][0].__setitem__("max_bytes", 10**12), "max_bytes"),
    (lambda c: c["stores"][1].__setitem__("method", "docker_exec_stream"), "not allowed"),
    (lambda c: c["stores"][1].__setitem__("path", "relative/dir"), "absolute"),
    (lambda c: c["stores"].__setitem__(0, {"id": "postgresql", "disposition": "rebuildable_excluded",
                                            "reason": "postgres is not rebuildable at all"}), "only rebuildable"),
])
def test_invalid_configuration_is_blocked(site, mutate, message):
    config = copy.deepcopy(site["config"])
    mutate(config)
    with pytest.raises(bk.Blocked, match=message):
        bk.load_config(write_config(site, config))


def test_sum_of_store_caps_cannot_exceed_bundle_cap(site):
    config = copy.deepcopy(site["config"])
    for store in config["stores"]:
        store["max_bytes"] = config["max_backup_bytes"]
    with pytest.raises(bk.Blocked, match="sum of per-store caps"):
        bk.load_config(write_config(site, config))


# --------------------------------------------------------------- lock, exit codes, metrics


def test_overlapping_run_is_refused():
    pytest.importorskip("fcntl")
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        lock = Path(directory) / "backup.lock"
        with bk.single_run_lock(lock):
            with pytest.raises(bk.OverlapError):
                with bk.single_run_lock(lock):
                    pass


def test_execute_success_writes_metrics_and_receipt(site, monkeypatch):
    path = write_config(site)
    run = bk.run_backup
    monkeypatch.setattr(bk, "run_backup", lambda config: run(config, free=plenty, capture=fake_capture))
    assert bk.execute(path) == bk.EXIT_OK
    metrics = (site["tmp"] / "metrics" / "dr-backup.prom").read_text()
    assert "nexolab_dr_backup_last_run_ok 1" in metrics
    assert "nexolab_dr_backup_stores_captured 8" in metrics
    assert len(list(site["out"].glob("*.receipt.json"))) == 1


def test_execute_failure_reports_zero_and_keeps_last_success(site, monkeypatch):
    path = write_config(site)
    run = bk.run_backup
    monkeypatch.setattr(bk, "run_backup", lambda config: run(config, free=plenty, capture=fake_capture))
    assert bk.execute(path) == bk.EXIT_OK
    first = (site["tmp"] / "metrics" / "dr-backup.prom").read_text()
    success_line = next(line for line in first.splitlines() if line.startswith("nexolab_dr_backup_last_success"))

    def failing(store, sink):
        raise bk.CaptureFailed("simulated pg_dump failure")

    monkeypatch.setattr(bk, "run_backup", lambda config: run(config, free=plenty, capture=failing))
    assert bk.execute(path) == bk.EXIT_FAILED
    second = (site["tmp"] / "metrics" / "dr-backup.prom").read_text()
    assert "nexolab_dr_backup_last_run_ok 0" in second
    assert success_line.split()[1][:8] in second  # last success timestamp preserved


def test_execute_blocked_configuration_exits_78(site):
    config = copy.deepcopy(site["config"])
    config["reserve_free_bytes"] = 1
    assert bk.execute(write_config(site, config)) == bk.EXIT_BLOCKED


def test_plan_mode_reads_no_data_and_writes_nothing(site, monkeypatch, capsys):
    monkeypatch.setattr(bk, "free_bytes", plenty)
    monkeypatch.setattr(bk, "capture_store", lambda *a: pytest.fail("plan must not capture"))
    assert bk.execute(write_config(site), plan_only=True) == bk.EXIT_OK
    assert '"PLAN_OK"' in capsys.readouterr().out
    assert not site["out"].exists()


# --------------------------------------------------------------- systemd templates


UNIT_DIR = ROOT / "infrastructure" / "systemd"


def test_timer_is_persistent_and_named_for_the_health_probe():
    timer = (UNIT_DIR / "nexolab-dr-backup.timer").read_text()
    assert "Persistent=true" in timer and "Unit=nexolab-dr-backup.service" in timer
    assert "DO NOT install" in timer
    health = (ROOT / "scripts" / "nexolab-dr-readonly-health.py").read_text()
    assert 'TIMER = "nexolab-dr-backup.timer"' in health


def test_service_is_hardened_low_priority_and_never_restarts_containers():
    service = (UNIT_DIR / "nexolab-dr-backup.service").read_text()
    for required in ("Type=oneshot", "NoNewPrivileges=yes", "ProtectSystem=strict", "PrivateTmp=yes",
                     "Nice=19", "IOSchedulingClass=idle", "MemoryMax=", "UMask=0077",
                     "nexolab-dr-scheduled-backup.py", "DO NOT install"):
        assert required in service, required
    assert "Restart=" not in service
    for forbidden in ("docker stop", "docker restart", "docker compose down", "systemctl restart"):
        assert forbidden not in service




def test_free_bytes_uses_nearest_existing_ancestor(tmp_path):
    assert bk.free_bytes(tmp_path / "not" / "yet" / "created") > 0


def test_example_configuration_is_structurally_valid(tmp_path):
    example = json.loads((ROOT / "infrastructure" / "systemd" / "nexolab-dr-backup.example.json").read_text())
    example.pop("source_commit_file")
    example["source_commit"] = COMMIT
    path = tmp_path / "example.json"
    path.write_text(json.dumps(example))
    config = bk.load_config(path)
    assert {s.id for s in config.stores} == set(bk.V2_STORES)
    assert config.reserve_free_bytes >= 20 * GiB
    seq = [s.id for s in config.stores]
    assert seq.index("postgresql") < seq.index("object-storage") == len(seq) - 1  # objects after DB snapshot
