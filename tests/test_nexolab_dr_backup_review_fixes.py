"""#1630 regression tests for the independent review of PR #1635 (synthetic data only).

Each test reproduces one confirmed review finding (P1-1..P1-3, P2-4..P2-7).
No production Docker, PostgreSQL, MQTT, Raspberry Pi or hardware is touched.
"""
from __future__ import annotations

import copy
import os
import sqlite3
import subprocess
import sys
import tarfile
import textwrap

import pytest

import test_nexolab_dr_scheduled_backup as base
from test_nexolab_dr_scheduled_backup import site  # noqa: F401  (pytest fixture)

bk, drs = base.bk, base.drs
GiB, KEY, ROOT = base.GiB, base.KEY, base.ROOT
write_config, fake_capture, plenty, PG_DUMP_BYTES = base.write_config, base.fake_capture, base.plenty, base.PG_DUMP_BYTES

PG_CANONICAL = ["docker", "exec", "nexolab-central-postgres-1", "nice", "-n", "19",
                "pg_dump", "-U", "nexolab", "-d", "nexolab", "-Fc", "-Z", "3"]


# --------------------------------------------------------------- P1-1 strict pg_dump allowlist


@pytest.mark.parametrize("extra", [
    ["-f", "/tmp/plain.dump"], ["--file", "/tmp/plain.dump"], ["--file=/tmp/plain.dump"],
    ["-f/tmp/plain.dump"], ["-Fp"], ["--format=plain"], ["-Z", "9x"], ["-Z", "10"],
    ["-U", "a;rm"], ["--schema-only"], ["-j", "4"], ["--host", "remote.example"],
    ["-h", "10.0.0.1"], ["-Fd"], ["-Ft"], ["--exclude-table-data=telemetry_samples"],
])
def test_p1_pg_dump_allowlist_guarantees_stdout_only_custom_dump(extra):
    with pytest.raises(bk.Blocked):
        bk.validate_docker_argv(PG_CANONICAL + extra, "postgresql")


@pytest.mark.parametrize("argv", [
    PG_CANONICAL,
    PG_CANONICAL[:3] + PG_CANONICAL[6:],                       # without nice
    PG_CANONICAL[:3] + ["pg_dump", "-Fc", "-U", "nexolab", "-d", "nexolab", "--no-password"],
])
def test_p1_canonical_pg_dump_is_accepted(argv):
    assert bk.validate_docker_argv(argv, "postgresql") == argv


def test_p1_pg_dump_requires_user_database_and_custom_format():
    with pytest.raises(bk.Blocked):
        bk.validate_docker_argv(PG_CANONICAL[:3] + ["pg_dump", "-Fc"], "postgresql")
    with pytest.raises(bk.Blocked):
        bk.validate_docker_argv(PG_CANONICAL[:3] + ["pg_dump", "-U", "a", "-d", "b"], "postgresql")
    with pytest.raises(bk.Blocked):
        bk.validate_docker_argv(PG_CANONICAL + ["-Fc"], "postgresql")  # duplicate option


# --------------------------------------------------------------- P1-2 verification mandatory


def test_p1_verification_cannot_be_disabled(site):  # noqa: F811
    config = copy.deepcopy(site["config"])
    config["verify_after_capture"] = False
    with pytest.raises(bk.Blocked, match="verify_after_capture"):
        bk.load_config(write_config(site, config))


def test_p1_every_successful_run_is_cryptographically_verified(site, monkeypatch):  # noqa: F811
    calls = []
    real = drs.verify_file
    monkeypatch.setattr(drs, "verify_file", lambda path, key: calls.append(path) or real(path, key))
    receipt = bk.run_backup(bk.load_config(write_config(site)), free=plenty, capture=fake_capture)
    assert len(calls) == 1 and receipt["self_verified_after_capture"] is True


# --------------------------------------------------------------- P1-3 PostgreSQL / object storage


def test_p1_objects_are_captured_after_the_database_snapshot(site):  # noqa: F811
    order: list[str] = []
    bucket = site["src"] / "objects" / "nexolab-equipment-images"

    def capture(store, sink):
        order.append(store.id)
        if store.id == "postgresql":
            (bucket / "uploaded-during-dump.jpg").write_bytes(b"new")  # object put, then DB row commit
            sink.write(PG_DUMP_BYTES)
        else:
            bk.capture_store(store, sink)

    receipt = bk.run_backup(bk.load_config(write_config(site)), free=plenty, capture=capture)
    assert order.index("postgresql") < order.index("object-storage")
    restored = site["tmp"] / "restore"
    drs.extract_file(site["out"] / receipt["bundle"]["file"], KEY, restored)
    with tarfile.open(restored / "object-storage" / "objects.tar") as archive:
        assert "nexolab-equipment-images/uploaded-during-dump.jpg" in archive.getnames()
    cross = receipt["cross_store_consistency"]["postgresql_object_storage"]
    assert cross["status"] == "ORDERED_NO_DELETIONS_RESTORE_REFERENCE_CHECK_UNVERIFIED"
    assert cross["site_acceptance"] == "BLOCKED_UNTIL_1632_REFERENCE_CHECK"


def test_p1_object_deleted_after_db_snapshot_fails_the_run(site):  # noqa: F811
    victim = site["src"] / "objects" / "nexolab-equipment-images" / "a.jpg"

    def capture(store, sink):
        if store.id == "postgresql":
            victim.unlink()
            sink.write(PG_DUMP_BYTES)
        else:
            bk.capture_store(store, sink)

    with pytest.raises(bk.CaptureFailed, match="deleted after the database snapshot"):
        bk.run_backup(bk.load_config(write_config(site)), free=plenty, capture=capture)
    assert not any(site["out"].glob("*.nxs"))


# --------------------------------------------------------------- P2-4 SQLite peak memory


def test_p2_sqlite_capture_peak_rss_fits_the_service_memory_limit(tmp_path):
    pytest.importorskip("resource")
    db = tmp_path / "big.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE t (b BLOB)")
    connection.executemany("INSERT INTO t VALUES (?)", [(os.urandom(4096),) for _ in range(8192)])  # ~32 MiB
    connection.commit()
    connection.close()
    size = db.stat().st_size
    script = ROOT / "scripts" / "nexolab-dr-scheduled-backup.py"
    probe = textwrap.dedent(f"""
        import importlib.util, pathlib, resource, sys
        spec = importlib.util.spec_from_file_location("bk", {str(script)!r})
        bk = importlib.util.module_from_spec(spec); sys.modules["bk"] = bk; spec.loader.exec_module(bk)
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        class Discard:
            def write(self, data):
                return len(data)
        bk.capture_sqlite(pathlib.Path({str(db)!r}), Discard(), 1 << 30)
        print(base, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    """)
    output = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout.split()
    base_kib, peak_kib = int(output[0]), int(output[1])
    growth = (peak_kib - base_kib) * 1024
    assert growth < 2.4 * size + 24 * 1024**2, (growth, size)  # ~2.25-2.35x plus fixed overhead (measured)

    service = (ROOT / "infrastructure" / "systemd" / "nexolab-dr-backup.service").read_text()
    memory_max_mib = int(next(l for l in service.splitlines() if l.startswith("MemoryMax=")).split("=")[1].rstrip("M"))
    worst_case = 2.4 * bk.SQLITE_MAX_DEFAULT + 24 * 1024**2 + 64 * 1024**2 + 64 * 1024**2  # + interpreter + buffers
    assert worst_case < memory_max_mib * 1024**2, (worst_case, memory_max_mib)


# --------------------------------------------------------------- P2-5 verify before rename


def test_p2_failed_verification_leaves_no_final_bundle(site, monkeypatch):  # noqa: F811
    def broken(path, key):
        raise drs.StreamFailure("simulated authentication failure")

    monkeypatch.setattr(drs, "verify_file", broken)
    with pytest.raises(drs.StreamFailure):
        bk.run_backup(bk.load_config(write_config(site)), free=plenty, capture=fake_capture)
    assert list(site["out"].glob("*.nxs")) == []
    assert list(site["out"].glob(".*.partial")) == []


# --------------------------------------------------------------- P2-6 exact caps + final reserve


def test_p2_bundle_cap_has_no_hidden_tolerance(site):  # noqa: F811
    config = copy.deepcopy(site["config"])
    others = sum(s["max_bytes"] for s in config["stores"] if s["id"] != "postgresql")
    next(s for s in config["stores"] if s["id"] == "postgresql")["max_bytes"] = config["max_backup_bytes"] - others

    def capture(store, sink):
        sink.write(os.urandom(store.max_bytes))  # every store exactly at its cap: framing overhead exceeds the bundle cap

    with pytest.raises(bk.CaptureFailed, match="exceeds max_backup_bytes"):
        bk.run_backup(bk.load_config(write_config(site, config)), free=plenty, capture=capture)
    assert list(site["out"].glob("*.nxs")) == []


def test_p2_reserve_is_rechecked_right_before_finalization(site):  # noqa: F811
    state = {"done": False}

    def free(_path):
        return 1 * GiB if state["done"] else 500 * GiB

    def capture(store, sink):
        fake_capture(store, sink)
        if store.id == bk.CAPTURE_SEQUENCE[-1]:
            state["done"] = True  # disk filled by something else after the last periodic check

    with pytest.raises(bk.CaptureFailed, match="reserve"):
        bk.run_backup(bk.load_config(write_config(site)), free=free, capture=capture)
    assert list(site["out"].glob("*.nxs")) == []
    assert list(site["out"].glob(".*.partial")) == []


# --------------------------------------------------------------- P2-7 extract cleanup


def test_p2_failed_extract_removes_all_decrypted_material(tmp_path):
    output = __import__("io").BytesIO()
    writer = drs.EncryptedWriter(output, KEY, drs.build_header(
        repository="eNgine9r/nexolab-platform", commit="a" * 40, created_at="2026-11-21T00:00:00Z",
        key=KEY, chunk_size=4096, nonce_prefix=b"\x02" * drs.NONCE_PREFIX_BYTES))
    builder = drs.StreamBuilder(writer)
    builder.add_entry(path="local-auth/private.pem", store="local-auth-private-key", content_format="pem",
                      source=__import__("io").BytesIO(b"SECRET" * 4000), max_bytes=10**6)
    builder.add_entry(path="postgresql/nexolab.dump", store="postgresql", content_format="pg_custom",
                      source=__import__("io").BytesIO(os.urandom(40_000)), max_bytes=10**6)
    builder.finish({"kind": "test"})
    writer.close()
    blob = bytearray(output.getvalue())
    blob[-40] ^= 0x01  # corrupt the tail: the first (secret) entry is already decrypted when this is detected
    stream = tmp_path / "bad.nxs"
    stream.write_bytes(bytes(blob))
    target = tmp_path / "restore"
    with pytest.raises(drs.StreamFailure):
        drs.extract_file(stream, KEY, target)
    assert not target.exists()
