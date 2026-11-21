#!/usr/bin/env python3
"""#1630 streaming encrypted NEXOLAB disaster-recovery container (nexolab-dr-stream-v1).

Why a second format: ``nexolab-backup-bundle.py`` (nexolab-dr-v1) builds the
whole tar archive in memory and encrypts it in one AES-GCM call from a
plaintext payload directory. That cannot hold a multi-GiB PostgreSQL dump on a
4 GB Raspberry Pi and requires unencrypted staging on disk. This format keeps
memory constant and never writes plaintext:

* AES-256-GCM in the STREAM construction: plaintext is cut into chunks of at
  most ``chunk_size`` bytes; chunk ``i`` uses nonce = 7-byte random prefix ||
  4-byte big-endian counter || 1-byte final flag, and the canonical header is
  bound as associated data to every chunk. Reordering, truncation, chunk
  replay and header tampering are all detected.
* Inside the encrypted stream, entries are framed so sizes need not be known
  in advance (``pg_dump`` stdout): BEGIN(json) DATA* END(json) ... MANIFEST END_OF_STREAM.

The module never contacts Docker, the network or hardware. It reuses the
mounted 32-byte key-file contract of nexolab-dr-v1 (regular file, 0600).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"NEXOLAB-DRS-1\n"
FORMAT = "nexolab-dr-stream-v1"
ENCRYPTION = "aes-256-gcm-stream"
KEY_BYTES = 32
NONCE_PREFIX_BYTES = 7
TAG_BYTES = 16
DEFAULT_CHUNK_SIZE = 1024 * 1024
MAX_CHUNK_SIZE = 8 * 1024 * 1024
MAX_COUNTER = 2**32 - 1
U32 = struct.Struct(">I")
FRAME = struct.Struct(">BQ")
MAX_JSON_FRAME = 1024 * 1024

FRAME_BEGIN = 0x42  # B
FRAME_DATA = 0x44  # D
FRAME_END = 0x45  # E
FRAME_MANIFEST = 0x4D  # M
FRAME_EOS = 0x5A  # Z

COMMIT = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
STORE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class StreamFailure(ValueError):
    """Fail-closed error for any malformed, tampered or unsafe stream."""


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_key(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StreamFailure("encryption key file is not readable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise StreamFailure("encryption key must be a regular non-symlink file")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise StreamFailure("encryption key file permissions must be 0600 or stricter")
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise StreamFailure("encryption key file is not readable") from exc
    if len(key) != KEY_BYTES:
        raise StreamFailure("encryption key file must contain exactly 32 raw bytes")
    return key


def key_fingerprint(key: bytes) -> str:
    """Public identifier of a key (domain-separated hash, never the key)."""
    return hashlib.sha256(b"nexolab-dr-stream-key-id\x00" + key).hexdigest()[:32]


def safe_entry_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise StreamFailure("entry path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StreamFailure("entry path is unsafe")
    return path.as_posix()


def _nonce(prefix: bytes, counter: int, final: bool) -> bytes:
    if counter > MAX_COUNTER:
        raise StreamFailure("stream exceeds the maximum chunk count")
    return prefix + counter.to_bytes(4, "big") + (b"\x01" if final else b"\x00")


def build_header(*, repository: str, commit: str, created_at: str, key: bytes,
                 chunk_size: int, nonce_prefix: bytes) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository):
        raise StreamFailure("repository must use owner/name format")
    if not COMMIT.fullmatch(commit):
        raise StreamFailure("commit must be a full lowercase Git SHA")
    if not 4096 <= chunk_size <= MAX_CHUNK_SIZE:
        raise StreamFailure("chunk size is out of range")
    return {
        "schema_version": 1,
        "format": FORMAT,
        "encryption": ENCRYPTION,
        "chunk_size": chunk_size,
        "nonce_prefix": base64.b64encode(nonce_prefix).decode("ascii"),
        "key_fingerprint": key_fingerprint(key),
        "repository": repository,
        "commit": commit,
        "created_at": created_at,
    }


class EncryptedWriter:
    """Buffers plaintext, emits authenticated chunks; never holds more than one chunk."""

    def __init__(self, output: BinaryIO, key: bytes, header: dict[str, Any],
                 on_write: Callable[[int], None] | None = None) -> None:
        self._output = output
        self._aead = AESGCM(key)
        self._header_bytes = canonical_json(header)
        self._prefix = base64.b64decode(header["nonce_prefix"], validate=True)
        self._chunk_size = int(header["chunk_size"])
        self._buffer = bytearray()
        self._counter = 0
        self._closed = False
        self._on_write = on_write
        self.ciphertext_bytes = 0
        self._sha256 = hashlib.sha256()
        self._emit(MAGIC + U32.pack(len(self._header_bytes)) + self._header_bytes)

    def _emit(self, data: bytes) -> None:
        self._output.write(data)
        self._sha256.update(data)
        self.ciphertext_bytes += len(data)
        if self._on_write is not None:
            self._on_write(self.ciphertext_bytes)

    def _seal(self, plaintext: bytes, final: bool) -> None:
        sealed = self._aead.encrypt(_nonce(self._prefix, self._counter, final), plaintext, self._header_bytes)
        self._emit(U32.pack(len(sealed)) + sealed)
        self._counter += 1

    def write(self, data: bytes) -> None:
        if self._closed:
            raise StreamFailure("writer is closed")
        self._buffer.extend(data)
        while len(self._buffer) > self._chunk_size:
            chunk = bytes(self._buffer[: self._chunk_size])
            del self._buffer[: self._chunk_size]
            self._seal(chunk, final=False)

    def close(self) -> str:
        """Seals the final chunk and returns the SHA-256 of the whole ciphertext file."""
        if not self._closed:
            self._seal(bytes(self._buffer), final=True)
            self._buffer.clear()
            self._closed = True
        return self._sha256.hexdigest()


@dataclass
class EntryResult:
    path: str
    store: str
    content_format: str
    size: int
    sha256: str


class StreamBuilder:
    """Frames entries into an EncryptedWriter with a bounded copy buffer."""

    def __init__(self, writer: EncryptedWriter, copy_buffer: int = 256 * 1024) -> None:
        self._writer = writer
        self._copy_buffer = copy_buffer
        self.entries: list[EntryResult] = []
        self._paths: set[str] = set()

    def _frame(self, kind: int, payload: bytes) -> None:
        self._writer.write(FRAME.pack(kind, len(payload)) + payload)

    def begin_entry(self, *, path: str, store: str, content_format: str, max_bytes: int) -> "EntrySink":
        path = safe_entry_path(path)
        if path in self._paths:
            raise StreamFailure(f"duplicate entry: {path}")
        if not STORE_ID.fullmatch(store):
            raise StreamFailure("store id is invalid")
        self._paths.add(path)
        self._frame(FRAME_BEGIN, canonical_json({"path": path, "store": store, "format": content_format}))
        return EntrySink(self, path, store, content_format, max_bytes)

    def add_entry(self, *, path: str, store: str, content_format: str, source: BinaryIO,
                  max_bytes: int) -> EntryResult:
        sink = self.begin_entry(path=path, store=store, content_format=content_format, max_bytes=max_bytes)
        while True:
            chunk = source.read(self._copy_buffer)
            if not chunk:
                break
            sink.write(chunk)
        return sink.close()

    def finish(self, manifest: dict[str, Any]) -> None:
        manifest = dict(manifest)
        manifest["entries"] = [
            {"path": e.path, "store": e.store, "format": e.content_format, "size": e.size, "sha256": e.sha256}
            for e in self.entries
        ]
        self._frame(FRAME_MANIFEST, canonical_json(manifest))
        self._frame(FRAME_EOS, b"")


class EntrySink:
    """Write-only view of one entry; enforces the per-store size cap while streaming."""

    def __init__(self, builder: StreamBuilder, path: str, store: str, content_format: str, max_bytes: int) -> None:
        self._builder = builder
        self._path = path
        self._store = store
        self._format = content_format
        self._max = max_bytes
        self._digest = hashlib.sha256()
        self.size = 0
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            raise StreamFailure("entry is closed")
        view = memoryview(data)
        for offset in range(0, len(view), MAX_CHUNK_SIZE):
            part = bytes(view[offset: offset + MAX_CHUNK_SIZE])
            self.size += len(part)
            if self.size > self._max:
                raise StreamFailure(f"store {self._store} exceeds its size cap")
            self._digest.update(part)
            self._builder._frame(FRAME_DATA, part)
        return len(data)

    def flush(self) -> None:  # file-object protocol for tarfile
        return None

    def close(self) -> EntryResult:
        if self._closed:
            raise StreamFailure("entry already closed")
        self._closed = True
        result = EntryResult(self._path, self._store, self._format, self.size, self._digest.hexdigest())
        self._builder._frame(FRAME_END, canonical_json({"path": self._path, "size": self.size, "sha256": result.sha256}))
        self._builder.entries.append(result)
        return result


# ----------------------------------------------------------------- reading


def _read_exact(source: BinaryIO, size: int) -> bytes:
    data = source.read(size)
    if len(data) != size:
        raise StreamFailure("stream is truncated")
    return data


def read_header(source: BinaryIO) -> tuple[dict[str, Any], bytes]:
    if _read_exact(source, len(MAGIC)) != MAGIC:
        raise StreamFailure("stream has an invalid magic header")
    (length,) = U32.unpack(_read_exact(source, U32.size))
    if not 0 < length <= 65536:
        raise StreamFailure("stream header length is invalid")
    header_bytes = _read_exact(source, length)
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StreamFailure("stream header is invalid") from exc
    expected = {"schema_version", "format", "encryption", "chunk_size", "nonce_prefix",
                "key_fingerprint", "repository", "commit", "created_at"}
    if not isinstance(header, dict) or set(header) != expected:
        raise StreamFailure("stream header has unexpected fields")
    if header["schema_version"] != 1 or header["format"] != FORMAT or header["encryption"] != ENCRYPTION:
        raise StreamFailure("stream header version is unsupported")
    if canonical_json(header) != header_bytes:
        raise StreamFailure("stream header is not canonical")
    chunk_size = header["chunk_size"]
    if type(chunk_size) is not int or not 4096 <= chunk_size <= MAX_CHUNK_SIZE:
        raise StreamFailure("stream chunk size is invalid")
    try:
        prefix = base64.b64decode(str(header["nonce_prefix"]), validate=True)
    except (ValueError, TypeError) as exc:
        raise StreamFailure("stream nonce prefix is invalid") from exc
    if len(prefix) != NONCE_PREFIX_BYTES:
        raise StreamFailure("stream nonce prefix length is invalid")
    return header, header_bytes


def iter_plaintext(source: BinaryIO, key: bytes) -> tuple[dict[str, Any], Iterator[bytes]]:
    header, header_bytes = read_header(source)
    if header["key_fingerprint"] != key_fingerprint(key):
        raise StreamFailure("key does not match this stream (fingerprint mismatch)")
    aead = AESGCM(key)
    prefix = base64.b64decode(header["nonce_prefix"])
    max_sealed = header["chunk_size"] + TAG_BYTES

    def chunks() -> Iterator[bytes]:
        counter = 0
        while True:
            raw_length = source.read(U32.size)
            if len(raw_length) != U32.size:
                raise StreamFailure("stream is truncated before its final chunk")
            (length,) = U32.unpack(raw_length)
            if not TAG_BYTES <= length <= max_sealed:
                raise StreamFailure("stream chunk length is invalid")
            sealed = _read_exact(source, length)
            for final in (False, True):
                try:
                    plaintext = aead.decrypt(_nonce(prefix, counter, final), sealed, header_bytes)
                except InvalidTag:
                    continue
                break
            else:
                raise StreamFailure("stream chunk authentication failed")
            counter += 1
            yield plaintext
            if final:
                if source.read(1):
                    raise StreamFailure("trailing data after the final chunk")
                return

    return header, chunks()


class _PlainReader:
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buffer = bytearray()
        self._done = False

    def read(self, size: int) -> bytes:
        while len(self._buffer) < size and not self._done:
            try:
                self._buffer.extend(next(self._chunks))
            except StopIteration:
                self._done = True
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data


@dataclass
class VerifyResult:
    header: dict[str, Any]
    manifest: dict[str, Any]
    entries: list[EntryResult] = field(default_factory=list)


def walk(source: BinaryIO, key: bytes,
         sink_factory: Callable[[dict[str, Any]], BinaryIO | None] | None = None) -> VerifyResult:
    """Authenticates and parses the whole stream; optionally hands entry bytes to sinks."""
    header, chunks = iter_plaintext(source, key)
    reader = _PlainReader(chunks)
    entries: list[EntryResult] = []
    seen: set[str] = set()
    manifest: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    digest = hashlib.sha256()
    size = 0
    sink: BinaryIO | None = None

    def json_payload(length: int) -> dict[str, Any]:
        if length > MAX_JSON_FRAME:
            raise StreamFailure("metadata frame is too large")
        try:
            value = json.loads(_read_exact(reader, length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise StreamFailure("metadata frame is invalid") from exc
        if not isinstance(value, dict):
            raise StreamFailure("metadata frame must be an object")
        return value

    while True:
        raw = reader.read(FRAME.size)
        if len(raw) != FRAME.size:
            raise StreamFailure("stream ended without an end-of-stream frame")
        kind, length = FRAME.unpack(raw)
        if kind == FRAME_BEGIN:
            if current is not None or manifest is not None:
                raise StreamFailure("unexpected entry start")
            current = json_payload(length)
            if set(current) != {"path", "store", "format"}:
                raise StreamFailure("entry metadata has unexpected fields")
            current["path"] = safe_entry_path(current["path"])
            if current["path"] in seen:
                raise StreamFailure("duplicate entry in stream")
            seen.add(current["path"])
            digest, size = hashlib.sha256(), 0
            sink = sink_factory(current) if sink_factory else None
        elif kind == FRAME_DATA:
            if current is None or length > MAX_CHUNK_SIZE:
                raise StreamFailure("unexpected data frame")
            data = _read_exact(reader, length)
            digest.update(data)
            size += len(data)
            if sink is not None:
                sink.write(data)
        elif kind == FRAME_END:
            if current is None:
                raise StreamFailure("unexpected entry end")
            end = json_payload(length)
            if end != {"path": current["path"], "size": size, "sha256": digest.hexdigest()}:
                raise StreamFailure(f"entry integrity mismatch: {current['path']}")
            if sink is not None:
                sink.close()
                sink = None
            entries.append(EntryResult(current["path"], current["store"], current["format"], size, end["sha256"]))
            current = None
        elif kind == FRAME_MANIFEST:
            if current is not None or manifest is not None:
                raise StreamFailure("unexpected manifest")
            manifest = json_payload(length)
        elif kind == FRAME_EOS:
            if length != 0 or manifest is None or current is not None:
                raise StreamFailure("invalid end-of-stream")
            if reader.read(1):
                raise StreamFailure("data after end-of-stream frame")
            break
        else:
            raise StreamFailure("unknown frame type")

    declared = manifest.get("entries")
    actual = [{"path": e.path, "store": e.store, "format": e.content_format, "size": e.size, "sha256": e.sha256}
              for e in entries]
    if declared != actual:
        raise StreamFailure("manifest does not match the streamed entries")
    return VerifyResult(header, manifest, entries)


def verify_file(path: Path, key: bytes) -> VerifyResult:
    try:
        with path.open("rb") as source:
            return walk(source, key)
    except OSError as exc:
        raise StreamFailure("stream file is not readable") from exc


def extract_file(path: Path, key: bytes, output_dir: Path) -> VerifyResult:
    """Restore helper (#1632): writes entries into a NEW empty directory, 0600 files."""
    if output_dir.exists():
        raise StreamFailure("extract destination must not exist")
    output_dir.mkdir(mode=0o700, parents=True)
    staging = output_dir / ".incomplete"
    staging.mkdir(mode=0o700)

    def sink(entry: dict[str, Any]) -> BinaryIO:
        target = staging / entry["path"]
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return os.fdopen(descriptor, "wb")

    with path.open("rb") as source:
        result = walk(source, key, sink)
    for child in staging.iterdir():
        child.rename(output_dir / child.name)
    staging.rmdir()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NEXOLAB #1630 streaming encrypted DR container")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="authenticate the whole stream without writing plaintext")
    verify.add_argument("--stream", type=Path, required=True)
    verify.add_argument("--key-file", type=Path, required=True)
    extract = sub.add_parser("extract", help="isolated restore only: decrypt into a new empty directory")
    extract.add_argument("--stream", type=Path, required=True)
    extract.add_argument("--key-file", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        key = load_key(args.key_file)
        if args.command == "verify":
            result = verify_file(args.stream, key)
        else:
            result = extract_file(args.stream, key, args.output_dir)
    except StreamFailure as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "VERIFIED" if args.command == "verify" else "EXTRACTED",
        "format": result.header["format"],
        "created_at": result.header["created_at"],
        "commit": result.header["commit"],
        "key_fingerprint": result.header["key_fingerprint"],
        "entries": [{"path": e.path, "store": e.store, "size": e.size, "sha256": e.sha256} for e in result.entries],
    }, sort_keys=True))
    return 0


def new_nonce_prefix() -> bytes:
    return secrets.token_bytes(NONCE_PREFIX_BYTES)


if __name__ == "__main__":
    raise SystemExit(main())
