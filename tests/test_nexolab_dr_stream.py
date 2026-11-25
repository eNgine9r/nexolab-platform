"""#1630 nexolab-dr-stream-v1 tests: synthetic data only, no Docker, network or hardware."""
from __future__ import annotations

import importlib.util
import io
import os
import struct
import sys
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nexolab_dr_stream", ROOT / "scripts" / "nexolab-dr-stream.py")
assert SPEC is not None and SPEC.loader is not None
drs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = drs
SPEC.loader.exec_module(drs)

KEY = bytes(range(32))
COMMIT = "a" * 40


def header(key: bytes = KEY, chunk: int = 4096) -> dict:
    return drs.build_header(repository="eNgine9r/nexolab-platform", commit=COMMIT,
                            created_at="2026-11-21T00:00:00Z", key=key, chunk_size=chunk,
                            nonce_prefix=b"\x01" * drs.NONCE_PREFIX_BYTES)


def build(entries: list[tuple[str, str, bytes]], chunk: int = 4096) -> bytes:
    output = io.BytesIO()
    writer = drs.EncryptedWriter(output, KEY, header(chunk=chunk))
    builder = drs.StreamBuilder(writer, copy_buffer=1000)
    for path, store, data in entries:
        builder.add_entry(path=path, store=store, content_format="bin", source=io.BytesIO(data), max_bytes=10**9)
    builder.finish({"schema_version": 1, "kind": "test"})
    writer.close()
    return output.getvalue()


def chunks_of(blob: bytes) -> tuple[bytes, list[bytes]]:
    """Split a stream into (preamble incl. header, [length-prefixed sealed chunks])."""
    (length,) = struct.unpack(">I", blob[len(drs.MAGIC): len(drs.MAGIC) + 4])
    offset = len(drs.MAGIC) + 4 + length
    preamble, rest, parts = blob[:offset], blob[offset:], []
    while rest:
        (size,) = struct.unpack(">I", rest[:4])
        parts.append(rest[: 4 + size])
        rest = rest[4 + size:]
    return preamble, parts


ENTRIES = [("postgresql/nexolab.dump", "postgresql", os.urandom(50_000)),
           ("local-auth/public.pem", "local-auth-public-key", b"-----BEGIN PUBLIC KEY-----\n")]


def test_round_trip_and_per_entry_hashes():
    blob = build(ENTRIES)
    result = drs.walk(io.BytesIO(blob), KEY)
    assert [e.path for e in result.entries] == [p for p, _, _ in ENTRIES]
    assert result.entries[0].size == 50_000
    assert result.manifest["kind"] == "test"


def test_ciphertext_contains_no_plaintext():
    marker = b"NEXOLAB-PLAINTEXT-MARKER-" * 40
    blob = build([("mqtt/data.tar", "mqtt-dynamic-security", marker)])
    assert b"NEXOLAB-PLAINTEXT-MARKER" not in blob


def test_wrong_key_is_rejected_by_fingerprint():
    blob = build(ENTRIES)
    with pytest.raises(drs.StreamFailure, match="fingerprint"):
        drs.walk(io.BytesIO(blob), bytes(32))


def test_truncation_before_final_chunk_is_detected():
    preamble, parts = chunks_of(build(ENTRIES))
    assert len(parts) > 3
    with pytest.raises(drs.StreamFailure, match="truncated"):
        drs.walk(io.BytesIO(preamble + b"".join(parts[:-1])), KEY)


def test_chunk_reordering_is_detected():
    preamble, parts = chunks_of(build(ENTRIES))
    parts[1], parts[2] = parts[2], parts[1]
    with pytest.raises(drs.StreamFailure, match="authentication"):
        drs.walk(io.BytesIO(preamble + b"".join(parts)), KEY)


def test_single_bit_flip_is_detected():
    blob = bytearray(build(ENTRIES))
    blob[-40] ^= 0x01
    with pytest.raises(drs.StreamFailure):
        drs.walk(io.BytesIO(bytes(blob)), KEY)


def test_header_tampering_is_detected():
    blob = build(ENTRIES).replace(b'"created_at":"2026-11-21T00:00:00Z"', b'"created_at":"2026-11-22T00:00:00Z"')
    with pytest.raises(drs.StreamFailure, match="authentication"):
        drs.walk(io.BytesIO(blob), KEY)


def test_trailing_garbage_after_final_chunk_is_rejected():
    with pytest.raises(drs.StreamFailure, match="trailing"):
        drs.walk(io.BytesIO(build(ENTRIES) + b"x"), KEY)


def test_per_store_size_cap_is_enforced_while_streaming():
    writer = drs.EncryptedWriter(io.BytesIO(), KEY, header())
    builder = drs.StreamBuilder(writer)
    with pytest.raises(drs.StreamFailure, match="size cap"):
        builder.add_entry(path="a/b", store="postgresql", content_format="bin",
                          source=io.BytesIO(b"x" * 5000), max_bytes=4999)


@pytest.mark.parametrize("path", ["../escape", "/abs", "a/../b", "", "a\\b"])
def test_unsafe_entry_paths_are_rejected(path):
    builder = drs.StreamBuilder(drs.EncryptedWriter(io.BytesIO(), KEY, header()))
    with pytest.raises(drs.StreamFailure, match="unsafe"):
        builder.begin_entry(path=path, store="postgresql", content_format="bin", max_bytes=10)


def test_duplicate_entries_are_rejected():
    builder = drs.StreamBuilder(drs.EncryptedWriter(io.BytesIO(), KEY, header()))
    builder.add_entry(path="a", store="postgresql", content_format="bin", source=io.BytesIO(b"1"), max_bytes=10)
    with pytest.raises(drs.StreamFailure, match="duplicate"):
        builder.begin_entry(path="a", store="postgresql", content_format="bin", max_bytes=10)


def test_memory_stays_bounded_for_large_streams():
    """64 MiB through the writer must not allocate anything near 64 MiB."""

    class Zero:
        def __init__(self, remaining: int) -> None:
            self.remaining = remaining

        def read(self, size: int) -> bytes:
            size = min(size, self.remaining)
            self.remaining -= size
            return b"\x00" * size

    class Discard:
        def write(self, data: bytes) -> int:
            return len(data)

    writer = drs.EncryptedWriter(Discard(), KEY, header(chunk=drs.DEFAULT_CHUNK_SIZE))
    builder = drs.StreamBuilder(writer)
    tracemalloc.start()
    builder.add_entry(path="postgresql/nexolab.dump", store="postgresql", content_format="pg_custom",
                      source=Zero(64 * 1024 * 1024), max_bytes=10**10)
    builder.finish({"kind": "test"})
    writer.close()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 16 * 1024 * 1024


def test_extract_restores_exact_bytes_into_new_directory(tmp_path):
    stream = tmp_path / "b.nxs"
    stream.write_bytes(build(ENTRIES))
    out = tmp_path / "restore"
    drs.extract_file(stream, KEY, out)
    assert (out / "postgresql" / "nexolab.dump").read_bytes() == ENTRIES[0][2]
    assert not (out / ".incomplete").exists()
    with pytest.raises(drs.StreamFailure, match="must not exist"):
        drs.extract_file(stream, KEY, out)


def test_cli_verify_reports_entries(tmp_path, capsys):
    key = tmp_path / "k"
    key.write_bytes(KEY)
    key.chmod(0o600)
    stream = tmp_path / "b.nxs"
    stream.write_bytes(build(ENTRIES))
    assert drs.main(["verify", "--stream", str(stream), "--key-file", str(key)]) == 0
    assert '"status": "VERIFIED"' in capsys.readouterr().out


def test_key_file_permissions_are_enforced(tmp_path):
    key = tmp_path / "k"
    key.write_bytes(KEY)
    key.chmod(0o644)
    with pytest.raises(drs.StreamFailure, match="0600"):
        drs.load_key(key)
