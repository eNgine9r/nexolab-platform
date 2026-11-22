#!/usr/bin/env python3
"""#1632 DR-B: isolated restore and verification of a NEXOLAB nexolab-dr-stream-v1 bundle.

Restores the off-device copy (leaf C, #1631) of a leaf-A bundle (#1630) onto a clean,
isolated target host and writes a hashed verification receipt.

Safety contract (enforced in code, covered by tests):
* never connects to production: the configuration accepts no connection strings or
  endpoints; production host names/addresses are only used to prove that they are
  NOT resolvable and NOT reachable, and any ``NEXOLAB_*``/database/broker endpoint in
  the environment refuses the run;
* every restored service runs on a new ``docker network create --internal`` network
  (no default route, no external connectivity) with NO published ports; helper
  containers run with ``--network none``; images are never pulled (``--pull never``);
* restores only into NEW volumes whose names carry the ``nx-dr-`` prefix and a run
  label; existing resources with the planned names refuse the run;
* the inputs (bundle, receipts, key) are only read; the bundle hash is re-verified
  against the custody receipt and the leaf-A receipt, then the whole stream is
  authenticated (``nexolab-dr-stream.py verify``) before anything is decrypted;
* decrypted plaintext exists only in one private staging directory that is removed
  on success AND on failure (the receipt records the removal);
* a receipt from ``mode=rehearsal`` says plainly that it is NOT site evidence.

Exit codes: 0 verified, 1 restore/verification failed, 78 refused (isolation,
custody, configuration).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.util
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 78
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent

CONFIG_KIND = "nexolab-dr-isolated-restore"
RECEIPT_KIND = "nexolab-dr-isolated-restore-receipt"
OBSERVATION_KIND = "nexolab-dr-source-observation"
BACKUP_RECEIPT_KIND = "nexolab-dr-backup-receipt"
V2_STORES = (
    "postgresql", "object-storage", "mqtt-dynamic-security", "edge-sqlite-outbox",
    "local-auth-private-key", "local-auth-public-key", "central-ingestion-spool",
    "edge-mqtt-persistence",
)
REBUILDABLE = frozenset({"central-ingestion-spool", "edge-mqtt-persistence"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PREFIX = re.compile(r"^nx-dr-[a-z0-9][a-z0-9-]{2,40}$")
PG_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
DIGEST_REF = re.compile(r"@sha256:[0-9a-f]{64}$")
# Connection strings/endpoints are never accepted anywhere in the configuration.
ENDPOINT_VALUE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
FORBIDDEN_CONFIG_KEYS = re.compile(r"(url|dsn|endpoint|connection|host_port)$", re.IGNORECASE)
FORBIDDEN_ENV_EXACT = frozenset({
    "DATABASE_URL", "PGHOST", "PGHOSTADDR", "PGPORT", "PGSERVICE", "PGPASSWORD", "PGPASSFILE",
    "MQTT_HOST", "MQTT_PORT", "OBJECT_STORAGE_ENDPOINT_URL", "OBJECT_STORAGE_PUBLIC_ENDPOINT_URL",
    "DOCKER_HOST", "DOCKER_CONTEXT",
})
FORBIDDEN_ENV_PREFIXES = ("NEXOLAB_",)
DEFAULT_PRODUCTION_HOSTS = ("nexolab-edge-01", "nexolab-edge-01.local")
DEFAULT_PROBE_PORTS = (22, 1883, 3000, 5432, 8082, 8883, 9000)
DEFAULT_INTERNET_PROBES = (("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53))
# Only these checks may be waived, only in mode=rehearsal, and a waiver is visible in the status.
WAIVABLE = frozenset({"isolation.production_unreachable", "isolation.internet_disconnected"})
PRODUCTION_RESOURCE = re.compile(r"^nexolab-(central|edge)-")
LABEL = "nexolab.dr.restore.prefix"
REHEARSAL_STATEMENT = (
    "LOCAL REHEARSAL ONLY. This receipt was produced on a development machine from synthetic data. "
    "It is NOT site evidence for #1632/#1428 and must not be used to set isolated_restore_verified."
)
SITE_STATEMENT = (
    "Isolated restore of the off-device copy on a target host without a network path to production. "
    "Valid as site evidence only together with the owner's record of the physical setup (#1632)."
)


class Refused(Exception):
    """Isolation, custody or configuration refuses the run (exit 78)."""


class RestoreFailed(Exception):
    """A restore or verification step failed (exit 1)."""


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise Refused(f"{filename} is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


drs = _load_module("nexolab_dr_stream", "nexolab-dr-stream.py")
# #1631 leaf C: shared custody receipt validator (single source of the contract).
offdevice = _load_module("nexolab_dr_offdevice_copy", "nexolab-dr-offdevice-copy.py")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Refused(f"{label}: expected a UTC timestamp ending in Z")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Refused(f"{label}: invalid timestamp") from exc
    return moment.astimezone(timezone.utc)


def canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


# ----------------------------------------------------------------- configuration


@dataclass(frozen=True)
class Config:
    mode: str
    bundle: Path
    custody_receipt: Path
    backup_receipt: Path | None
    key_file: Path
    work_dir: Path
    evidence_dir: Path
    prefix: str
    images: dict[str, str]
    production_hosts: tuple[str, ...]
    probe_ports: tuple[int, ...]
    internet_probes: tuple[tuple[str, int], ...]
    require_offline: bool
    pg_user: str
    pg_database: str
    bucket: str
    local_auth: dict[str, Any]
    source_observation: Path | None
    dashboards: tuple[dict[str, str], ...]
    objectives_file: Path
    ready_timeout_seconds: int
    approved_image_ids: frozenset[str] = field(default_factory=frozenset)
    waivers: frozenset[str] = field(default_factory=frozenset)

    @property
    def rehearsal(self) -> bool:
        return self.mode == "rehearsal"


def _reject_endpoints(value: Any, path: str = "config") -> None:
    """No connection string, URL or endpoint is accepted anywhere (#1632 isolation)."""
    if isinstance(value, dict):
        for key, item in value.items():
            if FORBIDDEN_CONFIG_KEYS.search(str(key)):
                raise Refused(f"{path}.{key}: connection strings/endpoints are not accepted")
            _reject_endpoints(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_endpoints(item, f"{path}[{index}]")
    elif isinstance(value, str) and ENDPOINT_VALUE.match(value):
        raise Refused(f"{path}: connection strings/endpoints are not accepted")


def _abs(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise Refused(f"{label} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise Refused(f"{label} must be absolute")
    return path


def load_config(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refused("restore configuration is unreadable or invalid JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or raw.get("kind") != CONFIG_KIND:
        raise Refused("restore configuration schema is unsupported")
    _reject_endpoints(raw)
    mode = raw.get("mode")
    if mode not in ("site", "rehearsal"):
        raise Refused("mode must be 'site' or 'rehearsal'")
    media = raw.get("media")
    if not isinstance(media, dict):
        raise Refused("media must name the off-device bundle and its custody receipt (backup_receipt optional)")
    prefix = raw.get("resource_prefix")
    if not isinstance(prefix, str) or not PREFIX.fullmatch(prefix) or PRODUCTION_RESOURCE.match(prefix):
        raise Refused("resource_prefix must match nx-dr-<name> (never a production resource name)")
    images = raw.get("images")
    required_images = {"telemetry", "postgres", "object_storage", "mqtt"}
    if not isinstance(images, dict) or set(images) != required_images or not all(
        isinstance(v, str) and v and not v.startswith("-") and " " not in v for v in images.values()
    ):
        raise Refused("images must define exactly telemetry, postgres, object_storage and mqtt references")
    hosts = raw.get("production_hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) and h for h in hosts):
        raise Refused("production_hosts must be a list of host names or addresses")
    all_hosts = tuple(dict.fromkeys([*DEFAULT_PRODUCTION_HOSTS, *hosts]))
    if mode == "site" and len(hosts) == 0:
        raise Refused("site mode requires production_hosts (edge-01 addresses/names) to prove isolation")
    ports = raw.get("production_probe_ports", list(DEFAULT_PROBE_PORTS))
    if not isinstance(ports, list) or not ports or not all(type(p) is int and 0 < p < 65536 for p in ports):
        raise Refused("production_probe_ports must be a non-empty list of TCP ports")
    probes_raw = raw.get("internet_probes", [list(p) for p in DEFAULT_INTERNET_PROBES])
    try:
        probes = tuple((str(ipaddress.ip_address(h)), int(p)) for h, p in probes_raw)
    except (TypeError, ValueError) as exc:
        raise Refused("internet_probes must be [ip, port] pairs") from exc
    require_offline = raw.get("require_internet_disconnected", mode == "site")
    if mode == "site" and require_offline is not True:
        raise Refused("site mode requires require_internet_disconnected=true (offline proof)")
    pg = raw.get("postgres", {})
    pg_user, pg_db = pg.get("user", "nexolab"), pg.get("database", "nexolab")
    if not PG_IDENT.fullmatch(str(pg_user)) or not PG_IDENT.fullmatch(str(pg_db)):
        raise Refused("postgres user/database must be simple identifiers")
    bucket = raw.get("object_storage", {}).get("bucket", "nexolab-equipment-images")
    if not BUCKET.fullmatch(str(bucket)):
        raise Refused("object_storage.bucket is invalid")
    local_auth = raw.get("local_auth")
    if not isinstance(local_auth, dict):
        raise Refused("local_auth (username, password_file, organization_id) is required")
    if not isinstance(local_auth.get("username"), str) or not local_auth["username"]:
        raise Refused("local_auth.username is required")
    _abs(local_auth.get("password_file"), "local_auth.password_file")
    if not UUID.fullmatch(str(local_auth.get("organization_id", ""))):
        raise Refused("local_auth.organization_id must be a UUID")
    verification = raw.get("verification", {})
    observation = verification.get("source_observation")
    dashboards = verification.get("dashboards", [])
    if not isinstance(dashboards, list) or not all(isinstance(d, dict) for d in dashboards):
        raise Refused("verification.dashboards must be a list")
    for item in dashboards:
        if not UUID.fullmatch(str(item.get("id", ""))):
            raise Refused("dashboard id must be a UUID")
        parse_utc(item.get("from"), "dashboard.from")
        parse_utc(item.get("to"), "dashboard.to")
    if mode == "site" and (observation is None or not dashboards):
        raise Refused("site mode requires a source observation and at least one saved dashboard to compare")
    timeout = raw.get("ready_timeout_seconds", 900)
    if type(timeout) is not int or not 30 <= timeout <= 7200:
        raise Refused("ready_timeout_seconds must be between 30 and 7200")
    waivers = raw.get("rehearsal_waivers", [])
    if not isinstance(waivers, list) or not set(waivers) <= WAIVABLE:
        raise Refused(f"rehearsal_waivers may only contain {sorted(WAIVABLE)}")
    if waivers and mode != "rehearsal":
        raise Refused("waivers are forbidden in site mode")
    approved = raw.get("approved_image_ids", [])
    if not isinstance(approved, list) or not all(isinstance(i, str) and i.startswith("sha256:") for i in approved):
        raise Refused("approved_image_ids must list sha256: image ids")
    config = Config(
        mode=mode,
        bundle=_abs(media.get("bundle"), "media.bundle"),
        custody_receipt=_abs(media.get("custody_receipt"), "media.custody_receipt"),
        backup_receipt=(_abs(media["backup_receipt"], "media.backup_receipt")
                        if media.get("backup_receipt") is not None else None),
        key_file=_abs(raw.get("key_file"), "key_file"),
        work_dir=_abs(raw.get("work_dir"), "work_dir"),
        evidence_dir=_abs(raw.get("evidence_dir"), "evidence_dir"),
        prefix=prefix,
        images=dict(images),
        production_hosts=all_hosts,
        probe_ports=tuple(ports),
        internet_probes=probes,
        require_offline=bool(require_offline),
        pg_user=str(pg_user),
        pg_database=str(pg_db),
        bucket=str(bucket),
        local_auth={
            "username": local_auth["username"],
            "password_file": _abs(local_auth["password_file"], "local_auth.password_file"),
            "organization_id": local_auth["organization_id"],
            "issuer": str(local_auth.get("issuer", "urn:nexolab:local")),
            "audience": str(local_auth.get("audience", "nexolab-api")),
        },
        source_observation=_abs(observation, "verification.source_observation") if observation else None,
        dashboards=tuple({"id": d["id"], "from": d["from"], "to": d["to"],
                          "timezone": str(d.get("timezone", "UTC"))} for d in dashboards),
        objectives_file=_abs(raw.get("objectives_file", str(ROOT / "security" / "disaster-recovery-assets.json")),
                             "objectives_file"),
        ready_timeout_seconds=timeout,
        approved_image_ids=frozenset(approved),
        waivers=frozenset(waivers),
    )
    inputs = tuple(p for p in (config.bundle, config.custody_receipt, config.backup_receipt, config.key_file) if p)
    for output in (config.work_dir, config.evidence_dir):
        for item in inputs:
            if output == item or output in item.parents:
                raise Refused("work_dir/evidence_dir must not contain the read-only inputs")
    return config


# ----------------------------------------------------------------- isolation


def check_environment(environ: dict[str, str]) -> list[str]:
    """Names of production endpoint variables present in the environment (values never logged)."""
    return sorted(name for name in environ if name in FORBIDDEN_ENV_EXACT
                  or any(name.startswith(prefix) for prefix in FORBIDDEN_ENV_PREFIXES))


def _default_resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except (socket.gaierror, UnicodeError, OSError):
        return []


def _default_connect(address: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_production_isolation(hosts: Iterable[str], ports: Iterable[int], *,
                               resolve: Callable[[str], list[str]] = _default_resolve,
                               connect: Callable[[str, int, float], bool] = _default_connect,
                               timeout: float = 1.5) -> dict[str, Any]:
    """Every production host must be unresolvable and every literal address unreachable."""
    findings: list[str] = []
    checked: list[dict[str, Any]] = []
    all_addresses: set[str] = set()
    for host in hosts:
        try:
            literal = str(ipaddress.ip_address(host))
        except ValueError:
            literal = None
        addresses = [literal] if literal else resolve(host)
        all_addresses.update(addresses)
        if addresses and literal is None:
            findings.append(f"production host name resolves: {host}")
        reachable = sorted({port for address in addresses for port in ports if connect(address, port, timeout)})
        if reachable:
            findings.append(f"production host reachable: {host} (TCP ports {reachable})")
        checked.append({"host_sha256": sha256_bytes(host.encode()), "resolved": bool(addresses) and literal is None,
                        "reachable": bool(reachable)})
    return {"checked": checked, "findings": findings, "isolated": not findings, "addresses": sorted(all_addresses)}


def check_internet(probes: Iterable[tuple[str, int]], *,
                   connect: Callable[[str, int, float], bool] = _default_connect,
                   timeout: float = 2.0) -> dict[str, Any]:
    reachable = [f"{host}:{port}" for host, port in probes if connect(host, port, timeout)]
    return {"internet_reachable": bool(reachable), "reachable_probes": reachable}


def target_fingerprint(facts: dict[str, str]) -> str:
    """Stable identity of the restore target; recorded as restore_target_identity_sha256."""
    return sha256_bytes(b"nexolab-dr-restore-target\x00" + canonical(facts))


def collect_target_facts(docker_info: dict[str, Any]) -> dict[str, str]:
    machine_id = ""
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        with contextlib.suppress(OSError):
            machine_id = Path(candidate).read_text(encoding="ascii").strip()
            break
    return {
        "hostname": socket.gethostname(),
        "machine_id": machine_id,
        "host_architecture": platform.machine(),
        "host_system": platform.system(),
        "docker_engine_id": str(docker_info.get("ID", "")),
        "docker_architecture": str(docker_info.get("Architecture", "")),
        "docker_kernel": str(docker_info.get("KernelVersion", "")),
    }


# ----------------------------------------------------------------- custody


def read_json_file(path: Path, label: str, limit: int = 1024 * 1024) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise Refused(f"{label} must be a regular non-symlink file")
        data = path.read_bytes()
    except OSError as exc:
        raise Refused(f"{label} is not readable") from exc
    if not 0 < len(data) <= limit:
        raise Refused(f"{label} size is invalid")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Refused(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise Refused(f"{label} must be a JSON object")
    return value, data


def validate_custody_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Exact nexolab-dr-custody-receipt-v1 contract, validated by the leaf-C (#1631) shared validator."""
    try:
        return offdevice.validate_custody_receipt(receipt)
    except offdevice.CopyFailed as exc:
        raise Refused(str(exc)) from exc


def validate_store_list(stores: Any, label: str) -> list[dict[str, Any]]:
    """All eight v2 stores exactly once; only rebuildable stores may be excluded (with a reason)."""
    if not isinstance(stores, list) or not all(isinstance(s, dict) for s in stores):
        raise Refused(f"{label}: stores are missing")
    if sorted(s.get("id") for s in stores) != sorted(V2_STORES):
        raise Refused(f"{label}: does not classify all eight stores exactly once")
    for store in stores:
        if store.get("disposition") == "rebuildable_excluded":
            if store["id"] not in REBUILDABLE or len(str(store.get("reason", "")).strip()) < 10:
                raise Refused(f"{label}: {store['id']}: invalid exclusion")
        elif store.get("disposition") != "capture":
            raise Refused(f"{label}: {store.get('id')}: unknown disposition")
    return stores


def verify_custody(*, bundle_path: Path, custody: dict[str, Any], key: bytes) -> dict[str, Any]:
    """Re-verifies the off-device copy against its custody receipt (no decryption yet)."""
    validate_custody_receipt(custody)
    if bundle_path.name != custody["bundle_name"]:
        raise Refused("bundle file name does not match the custody receipt")
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise Refused("bundle must be a regular non-symlink file on the off-device media")
    digest, size = sha256_file(bundle_path)
    if digest != custody["bundle_sha256"] or size != custody["bundle_bytes"]:
        raise Refused("bundle hash/size does not match the custody receipt")
    # sha256 of the raw key file bytes (leaf-C contract); NOT the domain-separated stream key_fingerprint.
    if sha256_bytes(key) != custody["key_fingerprint_sha256"]:
        raise Refused("key file does not match the custody receipt key fingerprint")
    return {"bundle_sha256": digest, "bundle_bytes": size}


def bind_source_manifest(custody: dict[str, Any], stream_manifest: dict[str, Any]) -> str:
    """Leaf C records sha256(canonical_json(decrypted in-stream manifest)); recomputed after authentication."""
    if custody["source_manifest_sha256"] != sha256_bytes(drs.canonical_json(stream_manifest)):
        raise Refused("custody source_manifest_sha256 does not match the authenticated stream manifest")
    return "in_stream_manifest_canonical_sha256"


def compare_stream_with_manifest(entries: list[Any], manifest: dict[str, Any]) -> dict[str, dict]:
    """The authenticated stream must contain exactly the captured stores its manifest declares."""
    if manifest.get("kind") != "nexolab-dr-stream-manifest":
        raise Refused("stream manifest kind is unexpected")
    stores = validate_store_list(manifest.get("stores"), "stream manifest")
    captured = {s["id"]: s for s in stores if s.get("disposition") == "capture"}
    by_store: dict[str, Any] = {}
    for entry in entries:
        if entry.store in by_store:
            raise Refused(f"stream contains more than one entry for {entry.store}")
        by_store[entry.store] = entry
    if set(by_store) != set(captured):
        raise Refused("stream entries do not match the captured stores of the manifest")
    for store_id, store in captured.items():
        entry = by_store[store_id]
        if (entry.path, entry.size, entry.sha256) != (store.get("entry_path"), store.get("size"), store.get("sha256")):
            raise Refused(f"{store_id}: stream entry does not match the manifest")
    parse_utc(manifest.get("created_at"), "stream manifest created_at")
    return {store_id: {"path": e.path, "size": e.size, "sha256": e.sha256, "format": e.content_format}
            for store_id, e in by_store.items()}


def cross_check_backup_receipt(backup: dict[str, Any], *, bundle_name: str, bundle_sha256: str, bundle_bytes: int,
                               key: bytes, manifest: dict[str, Any]) -> None:
    """Optional: the leaf-A receipt usually stays on the (lost) Pi; when it is available it must agree."""
    if backup.get("kind") != BACKUP_RECEIPT_KIND or backup.get("schema_version") != 1 or \
            backup.get("format") != drs.FORMAT:
        raise Refused("backup receipt is not a nexolab-dr-backup-receipt v1 for nexolab-dr-stream-v1")
    if backup.get("bundle") != {"file": bundle_name, "size": bundle_bytes, "sha256": bundle_sha256}:
        raise Refused("bundle hash/size/name does not match the leaf-A backup receipt")
    if backup.get("key_fingerprint") != drs.key_fingerprint(key):
        raise Refused("key file does not match the backup receipt key fingerprint")
    receipt_stores = [{k: v for k, v in s.items() if k != "duration_seconds"}
                      for s in validate_store_list(backup.get("stores"), "backup receipt")]
    if receipt_stores != manifest.get("stores") or backup.get("created_at") != manifest.get("created_at"):
        raise Refused("leaf-A backup receipt does not match the authenticated stream manifest")


@contextlib.contextmanager
def plaintext_session(bundle: Path, key: bytes, staging: Path) -> Iterator[tuple[Path, Any]]:
    """Decrypts into a NEW private directory and always removes it afterwards."""
    if staging.exists():
        raise Refused("plaintext staging directory already exists")
    try:
        result = drs.extract_file(bundle, key, staging)  # removes partial plaintext itself on failure
    except drs.StreamFailure as exc:
        raise RestoreFailed(f"isolated extract failed: {exc}") from exc
    try:
        yield staging, result
    finally:
        remove_tree(staging)


def remove_tree(path: Path) -> None:
    def _make_writable(function, target, _exc):  # pragma: no cover - platform specific
        with contextlib.suppress(OSError):
            os.chmod(target, 0o700)
            function(target)
    if path.exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_make_writable)
        else:  # pragma: no cover
            shutil.rmtree(path, onerror=_make_writable)


# ----------------------------------------------------------------- PostgreSQL archive


COPY_HEADER = re.compile(r'^COPY ((?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)\.(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)) \((.*)\) FROM stdin;$')
IDENT_PART = re.compile(r'"((?:[^"]|"")+)"|([A-Za-z_][A-Za-z0-9_$]*)')


def split_qualified(name: str) -> tuple[str, str]:
    parts = [(quoted.replace('""', '"') if quoted else plain) for quoted, plain in IDENT_PART.findall(name)]
    if len(parts) != 2:
        raise RestoreFailed(f"unexpected table identifier in archive: {name[:80]}")
    return parts[0], parts[1]


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def normalize_timestamp(value: str) -> str:
    """COPY/psql timestamptz text -> canonical UTC ISO (microseconds)."""
    text = value.strip().replace(" ", "T", 1)
    match = re.fullmatch(r"(.*?)([+-]\d{2})(?::?(\d{2}))?(?::?(\d{2}))?$", text)
    if match and "T" in match.group(1):
        hours, minutes = match.group(2), match.group(3) or "00"
        text = f"{match.group(1)}{hours}:{minutes}"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_archive_data(lines: Iterable[str], *, latest_table: tuple[str, str] = ("public", "telemetry_samples"),
                       channel_columns: tuple[str, ...] = ("node_id", "equipment_id", "channel_id", "metric"),
                       time_column: str = "captured_at") -> dict[str, Any]:
    """Counts COPY rows per table in ``pg_restore --data-only -f -`` output (independent of the restore).

    Also derives the latest ``captured_at`` per channel from the archived telemetry rows.
    """
    counts: dict[str, int] = {}
    latest: dict[str, str] = {}
    current: tuple[str, str] | None = None
    indices: tuple[list[int], int] | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        if current is None:
            match = COPY_HEADER.match(line)
            if match:
                current = split_qualified(match.group(1))
                key = f"{current[0]}.{current[1]}"
                if key in counts:
                    raise RestoreFailed(f"duplicate COPY block for {key}")
                counts[key] = 0
                indices = None
                if current == latest_table:
                    columns = [split_qualified(f'x.{c.strip()}')[1] for c in match.group(2).split(",")]
                    if all(c in columns for c in (*channel_columns, time_column)):
                        indices = ([columns.index(c) for c in channel_columns], columns.index(time_column))
            continue
        if line == "\\.":
            current = None
            continue
        counts[f"{current[0]}.{current[1]}"] += 1
        if indices is not None:
            fields = line.split("\t")
            channel = "|".join("" if fields[i] == "\\N" else fields[i] for i in indices[0])
            stamp = fields[indices[1]]
            if stamp != "\\N":
                value = normalize_timestamp(stamp)
                if value > latest.get(channel, ""):
                    latest[channel] = value
    if current is not None:
        raise RestoreFailed("archive data stream ended inside a COPY block")
    return {"table_counts": counts, "latest_captured_at": latest}


def parse_domain_tables(sql_text: str) -> dict[str, str]:
    """Reuses the domain -> table mapping of scripts/disaster-recovery-domain-counts.sql.

    That file counts fixture rows only (synthetic CI ids); for a real restore the full table is compared.
    """
    pairs = re.findall(r"'([a-z_]+)',\s*\(SELECT count\(\*\) FROM ([a-z_]+)", sql_text)
    if not pairs:
        raise RestoreFailed("domain counts SQL could not be parsed")
    return {domain: f"public.{table}" for domain, table in pairs}


EXTRA_DOMAINS = {
    "telemetry_samples": "public.telemetry_samples",
    "telemetry_latest": "public.telemetry_latest",
    "live_dashboards": "public.live_dashboards",
    "live_dashboard_items": "public.live_dashboard_items",
    "local_accounts": "public.security_local_accounts",
    "organizations": "public.security_organizations",
    "audit_events": "public.security_audit_events",
}


def compare_counts(expected: dict[str, int], restored: dict[str, int]) -> list[dict[str, Any]]:
    """Exact equality per table; any difference (or missing table) is a FAIL."""
    differences = []
    for table in sorted(set(expected) | set(restored)):
        left, right = expected.get(table), restored.get(table)
        if left != right:
            differences.append({"table": table, "archive": left, "restored": right})
    return differences


def compare_latest(expected: dict[str, str], restored: dict[str, str]) -> list[dict[str, Any]]:
    return [{"channel": channel, "archive": expected.get(channel), "restored": restored.get(channel)}
            for channel in sorted(set(expected) | set(restored)) if expected.get(channel) != restored.get(channel)]


def compare_with_observation(observation: dict[str, Any], restored_counts: dict[str, int],
                             restored_latest: dict[str, str], backup_created_at: datetime) -> dict[str, Any]:
    """Source (production) observation taken read-only AFTER the backup: growth is explained by the
    consistency boundary (append-only data newer than the snapshot), anything else is a FAIL."""
    failures: list[str] = []
    explained: list[str] = []
    for table, source in sorted((observation.get("table_counts") or {}).items()):
        restored = restored_counts.get(table)
        if restored is None:
            failures.append(f"{table}: present in source, missing after restore")
        elif restored > source:
            failures.append(f"{table}: restored {restored} > source {source}")
        elif restored < source:
            explained.append(f"{table}: source grew by {source - restored} after the backup snapshot")
    backup_point = normalize_timestamp(iso(backup_created_at))
    for channel, raw_source in sorted((observation.get("latest_captured_at") or {}).items()):
        source = normalize_timestamp(raw_source)
        restored = restored_latest.get(channel)
        if restored == source:
            continue
        if restored is not None and restored > source:
            failures.append(f"{channel}: restored latest {restored} newer than source {source}")
        elif source > backup_point:
            explained.append(f"{channel}: source sample(s) newer than the backup point ({restored} < {source})")
        else:
            failures.append(f"{channel}: restored {restored} != source {source} although older than the backup")
    return {"failures": failures, "explained_by_consistency_boundary": explained, "passed": not failures}


# ----------------------------------------------------------------- RPO / RTO


def compute_rpo_rto(*, backup_created_at: datetime, restore_started_at: datetime, ready_at: datetime | None,
                    newest_data_at: datetime | None, objectives: dict[str, Any]) -> dict[str, Any]:
    """RPO = backup age when the restored stack became ready; RTO = restore start -> /health/ready."""
    result: dict[str, Any] = {
        "backup_created_at": iso(backup_created_at),
        "restore_started_at": iso(restore_started_at),
        "ready_at": iso(ready_at) if ready_at else None,
        "definition": {
            "rpo_seconds": "ready_at - backup receipt created_at (capture start; conservative)",
            "rto_seconds": "restore_started_at (custody verification start) -> first /health/ready with database=ready",
        },
    }
    rpo = (ready_at or restore_started_at) - backup_created_at
    result["rpo_seconds"] = round(rpo.total_seconds(), 3)
    result["rto_seconds"] = round((ready_at - restore_started_at).total_seconds(), 3) if ready_at else None
    result["newest_restored_sample_age_seconds"] = (
        round(((ready_at or restore_started_at) - newest_data_at).total_seconds(), 3) if newest_data_at else None
    )
    rpo_objective = objectives.get("software_rpo_seconds")
    rto_objective = objectives.get("software_restore_target_seconds")
    result["objectives"] = {"software_rpo_seconds": rpo_objective, "software_restore_target_seconds": rto_objective}
    gaps: dict[str, Any] = {}
    if isinstance(rpo_objective, (int, float)):
        gaps["rpo_gap_seconds"] = round(result["rpo_seconds"] - rpo_objective, 3)
        gaps["rpo_objective_met"] = result["rpo_seconds"] <= rpo_objective
    if isinstance(rto_objective, (int, float)) and result["rto_seconds"] is not None:
        gaps["rto_gap_seconds"] = round(result["rto_seconds"] - rto_objective, 3)
        gaps["rto_objective_met"] = result["rto_seconds"] <= rto_objective
    result["gaps"] = gaps
    result["note"] = ("software objectives in security/disaster-recovery-assets.json describe the quiesced CI "
                      "drill (RPO 0 s); a scheduled daily backup has an RPO of up to the schedule interval plus "
                      "the capture time, so a positive rpo_gap_seconds is expected and must be accepted or the "
                      "objective changed by the owner")
    return result


# ----------------------------------------------------------------- receipt


@dataclass
class Checks:
    items: list[dict[str, Any]] = field(default_factory=list)
    waivers: frozenset[str] = field(default_factory=frozenset)

    def add(self, name: str, passed: bool, detail: Any = None) -> bool:
        item = {"name": name, "passed": bool(passed), "detail": detail}
        if not passed and name in self.waivers:
            item["waived"] = True  # rehearsal only; reported in the status, never hidden
        self.items.append(item)
        return bool(passed) or bool(item.get("waived"))

    @property
    def passed(self) -> bool:
        return bool(self.items) and all(item["passed"] or item.get("waived") for item in self.items)

    def failed(self) -> list[str]:
        return [item["name"] for item in self.items if not item["passed"] and not item.get("waived")]

    def waived(self) -> list[str]:
        return [item["name"] for item in self.items if item.get("waived")]


REQUIRED_CHECKS = (
    "isolation.environment", "isolation.production_unreachable", "isolation.internal_network",
    "isolation.no_published_ports", "isolation.container_egress_blocked", "custody.verified",
    "stream.authenticated", "stream.matches_custody_manifest", "postgresql.restored",
    "postgresql.row_counts_equal_archive", "postgresql.latest_captured_at_equal_archive",
    "postgresql.migrations_at_head", "object_storage.tree_equals_archive",
    "object_storage.reference_integrity", "object_storage.bucket_private", "mqtt.dynamic_security_present", "mqtt.broker_started",
    "local_auth.keypair_matches", "application.ready_database", "local_auth.login_with_restored_keys",
    "plaintext.removed",
)


def evaluate_status(checks: Checks, *, rehearsal: bool) -> str:
    names = {item["name"] for item in checks.items}
    missing = [name for name in REQUIRED_CHECKS if name not in names]
    if missing or not checks.passed:
        return "FAIL"
    if checks.waived():
        return "REHEARSAL_PASS_WITH_WAIVERS" if rehearsal else "FAIL"
    return "REHEARSAL_PASS" if rehearsal else "PASS"


def store_verification_block(store_id: str, verification: dict[str, Any], passed: bool) -> dict[str, Any]:
    return {
        "status": "verified" if passed else "failed",
        "new_target": True,
        "source_untouched": True,
        "verification": verification,
        "verification_sha256": sha256_bytes(canonical({"store": store_id, "verification": verification})),
    }


def write_receipt(receipt: dict[str, Any], evidence_dir: Path) -> tuple[Path, str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path = evidence_dir / "nexolab-dr-isolated-restore-receipt.json"
    path.write_bytes(data)
    digest = sha256_bytes(data)
    (evidence_dir / "nexolab-dr-isolated-restore-receipt.json.sha256").write_text(
        f"{digest}  {path.name}\n", encoding="ascii")
    return path, digest


def v2_fields(receipt: dict[str, Any], receipt_sha256: str) -> dict[str, Any]:
    """Fields for validate-site-dr-inventory-v2.py: storage block + per-asset RESTORE_FIELDS."""
    site_pass = receipt["status"] == "PASS" and receipt["evidence_class"] == "SITE_ISOLATED_RESTORE"
    assets = {}
    for store_id, block in receipt["stores"].items():
        if block.get("disposition") == "rebuildable_excluded":
            continue
        assets[store_id] = {
            "status": block["status"] if site_pass else "unverified",
            "receipt_sha256": receipt_sha256,
            "new_target": block["new_target"],
            "source_untouched": block["source_untouched"],
            "verification_sha256": block["verification_sha256"],
        }
    return {
        "storage": {
            "isolated_restore_verified": site_pass,
            "restore_target_kind": "isolated_host",
            "restore_target_identity_sha256": receipt["target"]["identity_sha256"],
            "restore_receipt_sha256": receipt_sha256,
            "destination_identity_sha256": receipt["inputs"]["destination_identity_sha256"],
        },
        "assets_restore": assets,
        "evidence_class": receipt["evidence_class"],
        "note": None if site_pass else "not site evidence: isolated_restore_verified must stay false",
    }


def verify_receipt_file(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    receipt = json.loads(data.decode("utf-8"))
    sidecar = path.with_name(path.name + ".sha256")
    recorded = sidecar.read_text(encoding="ascii").split()[0] if sidecar.exists() else None
    digest = sha256_bytes(data)
    if receipt.get("kind") != RECEIPT_KIND:
        raise Refused("not an isolated restore receipt")
    checks = Checks(list(receipt.get("checks", [])))
    expected_status = evaluate_status(checks, rehearsal=receipt.get("evidence_class") != "SITE_ISOLATED_RESTORE")
    return {"sha256": digest, "sidecar_matches": recorded == digest, "status": receipt.get("status"),
            "status_consistent": receipt.get("status") == expected_status}


# ----------------------------------------------------------------- docker


class Docker:
    """Thin docker CLI wrapper. Only create/inspect/run/exec/rm verbs on nx-dr- resources are used."""

    def __init__(self, binary: str = "docker", runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.binary = binary
        self.runner = runner

    def __call__(self, *args: str, input_bytes: bytes | None = None, stdin: Any = None, check: bool = True,
                 timeout: float = 600) -> subprocess.CompletedProcess:
        argv = [self.binary, *args]
        try:
            result = self.runner(argv, input=input_bytes, stdin=stdin if input_bytes is None else None,
                                 capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RestoreFailed(f"docker {args[0]} failed to run: {type(exc).__name__}") from exc
        if check and result.returncode != 0:
            lines = (result.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            tail = " | ".join(line.strip() for line in lines[-4:]) or "no diagnostics"
            raise RestoreFailed(f"docker {args[0]} {args[1] if len(args) > 1 else ''} exited "
                                f"{result.returncode}: {tail[:500]}")
        return result

    def json(self, *args: str) -> Any:
        return json.loads(self(*args).stdout.decode("utf-8"))


HELPER = r'''
import hashlib, json, os, shutil, sqlite3, subprocess, sys
op = json.loads(sys.argv[1])
target = "/target"
def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
kind = op["op"]
if kind == "extract_tar":
    subprocess.run([sys.executable, "/opt/nexolab/scripts/nexolab-volume-archive.py", "extract",
                    "--archive", "/restore/" + op["src"], "--destination", target], check=True)
    print(json.dumps({"ok": True}))
elif kind == "install_file":
    dst = os.path.join(target, op["name"])
    if os.path.exists(dst):
        raise SystemExit("destination exists")
    shutil.copyfile("/restore/" + op["src"], dst)
    os.chown(dst, op["uid"], op["gid"])
    os.chmod(dst, int(op["mode"], 8))
    print(json.dumps({"sha256": sha(dst), "size": os.path.getsize(dst)}))
elif kind == "tree":
    files, others = [], 0
    for root, dirs, names in os.walk(target):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(root, name)
            if os.path.islink(path) or not os.path.isfile(path):
                others += 1
                continue
            files.append([os.path.relpath(path, target).replace(os.sep, "/"), os.path.getsize(path), sha(path)])
    print(json.dumps({"files": files, "non_regular": others}))
elif kind == "sqlite":
    path = os.path.join(target, op["name"])
    con = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {t: con.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}
    con.close()
    print(json.dumps({"integrity": integrity, "table_counts": counts, "sha256": sha(path)}))
elif kind == "dynsec":
    with open(os.path.join(target, "dynamic-security.json"), encoding="utf-8") as f:
        data = json.load(f)
    clients = data.get("clients", [])
    roles = data.get("roles", [])
    print(json.dumps({
        "clients": len(clients),
        "disabled_clients": sum(1 for c in clients if c.get("disabled")),
        "usernames_sha256": hashlib.sha256("\n".join(sorted(c.get("username", "") for c in clients)).encode()).hexdigest(),
        "clients_with_roles": sum(1 for c in clients if c.get("roles")),
        "roles": len(roles),
        "acls": sum(len(r.get("acls", [])) for r in roles),
        "groups": len(data.get("groups", [])),
        "default_acl_access": bool(data.get("defaultACLAccess")),
    }))
'''

PROBE = r'''
import hashlib, json, sys, urllib.error, urllib.parse, urllib.request
cfg = json.loads(sys.stdin.read())
base = "http://127.0.0.1:8082"
def call(path, token=None, payload=None, raw=False):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-Organization-ID"] = cfg["organization_id"]
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return response.status, body
    except urllib.error.HTTPError as error:
        return error.code, error.read()
out = {}
status, body = call("/health/ready")
out["ready"] = {"status_code": status, "body": json.loads(body or b"{}")}
status, body = call("/api/v1/auth/local/login", payload={"username": cfg["username"], "password": cfg["password"]})
out["login_status"] = status
token = refresh = None
if status == 200:
    tokens = json.loads(body)
    token, refresh = tokens.get("access_token"), tokens.get("refresh_token")
    out["access_token"] = token
    status, body = call("/api/v1/auth/session", token=token)
    out["session_status"] = status
    session = json.loads(body or b"{}")
    out["session_identity"] = {"provider": session.get("identity", {}).get("provider"),
                               "subject_sha256": hashlib.sha256(str(session.get("identity", {}).get("subject")).encode()).hexdigest()}
    dashboards = []
    for item in cfg["dashboards"]:
        record = {"id": item["id"], "from": item["from"], "to": item["to"], "timezone": item["timezone"]}
        status, body = call("/api/v1/live-dashboards/" + item["id"], token=token)
        record["get_status"] = status
        if status == 200:
            dashboard = json.loads(body)
            record["view_settings_sha256"] = hashlib.sha256(json.dumps(dashboard.get("view_settings"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            record["items"] = len(dashboard.get("items", []))
            record["view_settings_present"] = dashboard.get("view_settings") is not None
        query = urllib.parse.urlencode({"from": item["from"], "to": item["to"], "timezone": item["timezone"]})
        status, body = call("/api/v1/live-dashboards/" + item["id"] + "/telemetry.csv?" + query, token=token)
        record["csv_status"] = status
        if status == 200:
            record["csv_sha256"] = hashlib.sha256(body).hexdigest()
            record["csv_rows"] = max(body.count(b"\n") - 1, 0)
        dashboards.append(record)
    out["dashboards"] = dashboards
    images = []
    for image in cfg.get("images", []):
        status, body = call("/api/v1/equipment/" + urllib.parse.quote(image["equipment_id"], safe="") + "/images/" + image["id"] + "/content", token=token)
        images.append({"id": image["id"], "status": status, "sha256": hashlib.sha256(body).hexdigest() if status == 200 else None})
    out["image_content"] = images
    if refresh:
        status, _ = call("/api/v1/auth/local/logout", payload={"refresh_token": refresh})
        out["logout_status"] = status
print(json.dumps(out))
'''

S3_HEAD_PROBE = r'''
import json, os, sys
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
endpoint, bucket = sys.argv[1], sys.argv[2]
s3 = boto3.client("s3", endpoint_url=endpoint, region_name=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
                  aws_access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["OBJECT_STORAGE_SECRET_ACCESS_KEY"],
                  config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}))
out = []
for key in json.loads(sys.stdin.read()):
    try:
        response = s3.head_object(Bucket=bucket, Key=key)
        out.append({"key": key, "status": 200, "etag": response.get("ETag"), "size": response.get("ContentLength"),
                    "content_type": response.get("ContentType")})
    except ClientError as error:
        out.append({"key": key, "status": int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))})
print(json.dumps(out))
'''

EGRESS_PROBE = r'''
import json, socket, sys
targets = json.loads(sys.argv[1])
reachable, resolved = [], []
for host, port in targets["connect"]:
    try:
        socket.create_connection((host, port), timeout=2).close()
        reachable.append(f"{host}:{port}")
    except OSError:
        pass
for name in targets["resolve"]:
    try:
        socket.getaddrinfo(name, None)
        resolved.append(name)
    except OSError:
        pass
print(json.dumps({"reachable": reachable, "resolved": resolved}))
'''


def verify_rs256(token: str, public_pem: bytes) -> dict[str, Any]:
    """Verifies a JWT signature with the RESTORED public key (proves the restored key pair signs)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    header_b64, payload_b64, signature_b64 = token.split(".")
    header = json.loads(b64(header_b64))
    payload = json.loads(b64(payload_b64))
    if header.get("alg") != "RS256":
        return {"verified": False, "reason": "unexpected algorithm"}
    key = serialization.load_pem_public_key(public_pem)
    try:
        key.verify(b64(signature_b64), f"{header_b64}.{payload_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return {"verified": False, "reason": "signature does not verify with the restored public key"}
    return {"verified": True, "issuer": payload.get("iss"), "audience": payload.get("aud")}


def keypair_matches(private_pem: bytes, public_pem: bytes) -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(private_pem, password=None)
    public = serialization.load_pem_public_key(public_pem)
    der = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    derived = private.public_key().public_bytes(*der)
    return {"matches": derived == public.public_bytes(*der), "public_key_sha256": sha256_bytes(derived),
            "key_type": type(private).__name__}


# ----------------------------------------------------------------- orchestration


class Restore:
    def __init__(self, config: Config, docker: Docker | None = None, environ: dict[str, str] | None = None,
                 resolve: Callable[[str], list[str]] = _default_resolve,
                 connect: Callable[[str, int, float], bool] = _default_connect,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.config = config
        self.docker = docker or Docker()
        self.environ = dict(os.environ if environ is None else environ)
        self.resolve = resolve
        self.connect = connect
        self.clock = clock
        self.checks = Checks(waivers=config.waivers)
        self.receipt: dict[str, Any] = {}
        self.warnings: list[str] = []
        prefix = config.prefix
        self.network = f"{prefix}-net"
        self.volumes = {
            "postgresql": f"{prefix}-postgres-data",
            "object-storage": f"{prefix}-object-storage-data",
            "mqtt-dynamic-security": f"{prefix}-mqtt-data",
            "edge-mqtt-persistence": f"{prefix}-edge-mqtt-data",
            "edge-sqlite-outbox": f"{prefix}-edge-device-agent-data",
            "central-ingestion-spool": f"{prefix}-telemetry-ingestion-data",
            "local-auth": f"{prefix}-local-auth",
        }
        self.containers = {name: f"{prefix}-{name}" for name in ("postgres", "object-storage", "mqtt", "telemetry")}
        self.secrets_dir = config.work_dir / "runtime-secrets"

    # -- isolation ---------------------------------------------------------
    def preflight(self) -> dict[str, Any]:
        config = self.config
        forbidden = check_environment(self.environ)
        if not self.checks.add("isolation.environment", not forbidden, {"forbidden_variables": forbidden}):
            raise Refused(f"production endpoint variables are set: {', '.join(forbidden)}")
        if socket.gethostname().lower() in {h.lower() for h in config.production_hosts}:
            raise Refused("this host is a production host; restore only on an isolated target")
        isolation = check_production_isolation(config.production_hosts, config.probe_ports,
                                               resolve=self.resolve, connect=self.connect)
        self.production_addresses = isolation["addresses"]
        if not self.checks.add("isolation.production_unreachable", isolation["isolated"], isolation["findings"]):
            raise Refused("; ".join(isolation["findings"]))
        if not isolation["isolated"]:
            self.warnings.append("WAIVED (rehearsal): production is resolvable/reachable from this host; the "
                                 "restored stack still runs on an internal network (see container egress check)")
        internet = check_internet(config.internet_probes, connect=self.connect)
        offline_ok = not internet["internet_reachable"]
        if config.require_offline:
            if not self.checks.add("isolation.internet_disconnected", offline_ok, internet):
                raise Refused("internet is reachable; disconnect the uplink for the offline proof")
        elif not offline_ok:
            self.warnings.append("internet reachable on the rehearsal host (offline proof NOT demonstrated)")
        info = self.docker.json("info", "--format", "{{json .}}")
        names = self.docker("ps", "-a", "--format", "{{.Names}}").stdout.decode().split()
        volumes = self.docker("volume", "ls", "--format", "{{.Name}}").stdout.decode().split()
        production_like = sorted(n for n in [*names, *volumes] if PRODUCTION_RESOURCE.match(n))
        if production_like:
            message = f"production-named Docker resources exist on the target: {len(production_like)}"
            if not config.rehearsal:
                raise Refused(message + " (the isolated target must be clean)")
            self.warnings.append(message + " (rehearsal host; they are never touched)")
        planned = [self.network, *self.volumes.values(), *self.containers.values()]
        networks = self.docker("network", "ls", "--format", "{{.Name}}").stdout.decode().split()
        existing = sorted(set(planned) & set([*names, *volumes, *networks]))
        if existing:
            raise Refused(f"planned restore resources already exist (not fresh): {', '.join(existing)}")
        if config.work_dir.exists():
            raise Refused("work_dir must not exist (fresh restore staging)")
        facts = collect_target_facts(info)
        isolation = {k: v for k, v in isolation.items() if k != "addresses"}
        return {"identity_sha256": target_fingerprint(facts), "facts_sha256": {k: sha256_bytes(v.encode())
                for k, v in facts.items()}, "host_architecture": facts["host_architecture"],
                "docker_architecture": facts["docker_architecture"], "isolation": isolation, "internet": internet}

    def inspect_images(self, docker_arch: str) -> dict[str, Any]:
        result = {}
        for role, reference in self.config.images.items():
            data = self.docker.json("image", "inspect", reference)[0]
            image_id = data["Id"]
            pinned = bool(DIGEST_REF.search(reference)) or image_id in self.config.approved_image_ids
            if not self.config.rehearsal and not pinned:
                raise Refused(f"image {role} is neither digest-pinned nor in approved_image_ids")
            arch = data.get("Architecture")
            result[role] = {"reference": reference, "id": image_id, "architecture": arch, "pinned_or_approved": pinned,
                            "repo_digests": data.get("RepoDigests", [])}
            if docker_arch and arch and _normal_arch(arch) != _normal_arch(docker_arch):
                self.warnings.append(f"image {role} architecture {arch} differs from the target {docker_arch} "
                                     "(emulated; architecture fidelity NOT demonstrated)")
        return result

    # -- docker resources ---------------------------------------------------
    def _label(self) -> list[str]:
        return ["--label", f"{LABEL}={self.config.prefix}"]

    def create_resources(self) -> dict[str, Any]:
        self.created_resources = True
        self.docker("network", "create", "--internal", "--driver", "bridge", *self._label(), self.network)
        internal = self.docker.json("network", "inspect", self.network)[0].get("Internal") is True
        if not self.checks.add("isolation.internal_network", internal, {"network": self.network}):
            raise RestoreFailed("restore network is not internal")
        for volume in self.volumes.values():
            self.docker("volume", "create", *self._label(), volume)
        return {"network": self.network, "internal": internal, "volumes": sorted(self.volumes.values())}

    def helper(self, volume: str, op: dict[str, Any], plaintext: Path | None = None) -> dict[str, Any]:
        args = ["run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0", *self._label(),
                "-v", f"{volume}:/target", "-v", f"{SCRIPTS}:/opt/nexolab/scripts:ro"]
        if plaintext is not None:
            args += ["-v", f"{plaintext}:/restore:ro"]
        args += ["--entrypoint", "python", self.config.images["telemetry"], "-c", HELPER, json.dumps(op)]
        result = self.docker(*args)
        return json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])

    def _env_file(self, name: str, values: dict[str, str]) -> Path:
        self.secrets_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.secrets_dir / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        return path

    def _run_service(self, name: str, image: str, args: list[str], command: list[str]) -> None:
        self.docker("run", "-d", "--pull", "never", "--name", self.containers[name], "--network", self.network,
                    "--restart", "no", "--security-opt", "no-new-privileges:true", *self._label(), *args, image,
                    *command)
        ports = self.docker.json("inspect", self.containers[name])[0]["HostConfig"].get("PortBindings") or {}
        if ports:
            self.checks.add("isolation.no_published_ports", False, {name: list(ports)})
            raise RestoreFailed(f"{name} has published ports")

    def _wait(self, description: str, probe: Callable[[], bool], timeout: float, interval: float = 1.0) -> float:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if probe():
                return time.monotonic() - started
            time.sleep(interval)
        raise RestoreFailed(f"timed out waiting for {description}")

    # -- stores -------------------------------------------------------------
    def restore_postgresql(self, plaintext: Path, entry: dict[str, Any]) -> dict[str, Any]:
        config = self.config
        password = secrets.token_urlsafe(32)
        self.pg_password = password
        env = self._env_file("postgres.env", {"POSTGRES_USER": config.pg_user, "POSTGRES_DB": config.pg_database,
                                              "POSTGRES_PASSWORD": password})
        self._run_service("postgres", config.images["postgres"],
                          ["--env-file", str(env), "-v", f"{self.volumes['postgresql']}:/var/lib/postgresql/data"], [])
        pg = self.containers["postgres"]

        def ready() -> bool:
            return self.docker("exec", pg, "pg_isready", "-h", "127.0.0.1", "-U", config.pg_user, "-d",
                               config.pg_database, check=False).returncode == 0
        self._wait("PostgreSQL", ready, 180)
        dump = plaintext / entry["path"]
        started = time.monotonic()
        with dump.open("rb") as handle:
            result = self.docker("exec", "-i", pg, "pg_restore", "-U", config.pg_user, "-d", config.pg_database,
                                 "--exit-on-error", "--no-owner", "--no-privileges", stdin=handle, check=False,
                                 timeout=6 * 3600)
        restore_seconds = round(time.monotonic() - started, 3)
        stderr = result.stderr.decode("utf-8", "replace").strip().splitlines()
        if not self.checks.add("postgresql.restored", result.returncode == 0,
                               {"exit": result.returncode, "stderr_tail": stderr[-3:]}):
            raise RestoreFailed("pg_restore failed")
        archive = self.archive_data(dump)
        restored = self.restored_state(sorted(archive["table_counts"]))
        diffs = compare_counts(archive["table_counts"], restored["table_counts"])
        self.checks.add("postgresql.row_counts_equal_archive", not diffs,
                        {"tables": len(archive["table_counts"]), "differences": diffs[:50]})
        latest_diffs = compare_latest(archive["latest_captured_at"], restored["latest_captured_at"])
        self.checks.add("postgresql.latest_captured_at_equal_archive", not latest_diffs,
                        {"channels": len(archive["latest_captured_at"]), "differences": latest_diffs[:50]})
        self.archive = archive
        self.restored_pg = restored
        return {"pg_restore_seconds": restore_seconds, "archive_rows_total": sum(archive["table_counts"].values()),
                "tables": len(archive["table_counts"]), "row_count_differences": diffs,
                "latest_captured_at_differences": latest_diffs}

    def archive_data(self, dump: Path) -> dict[str, Any]:
        """Independent row counts straight from the archive (pg_restore --data-only to stdout)."""
        argv = [self.docker.binary, "run", "--rm", "-i", "--pull", "never", "--network", "none", *self._label(),
                "--entrypoint", "pg_restore", self.config.images["postgres"], "--data-only", "-f", "-"]
        with dump.open("rb") as handle:
            process = subprocess.Popen(argv, stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert process.stdout is not None
            try:
                parsed = parse_archive_data(line.decode("utf-8", "replace") for line in process.stdout)
            finally:
                process.stdout.close()
                stderr = process.stderr.read() if process.stderr else b""
                code = process.wait()
        if code != 0:
            raise RestoreFailed(f"pg_restore --data-only failed: {stderr.decode('utf-8', 'replace')[-200:]}")
        return parsed

    def psql(self, sql: str) -> str:
        result = self.docker("exec", "-i", "-e", "PGTZ=UTC", self.containers["postgres"], "psql", "-X", "-q", "-At",
                             "-v", "ON_ERROR_STOP=1", "-U", self.config.pg_user, "-d", self.config.pg_database,
                             input_bytes=sql.encode("utf-8"), timeout=6 * 3600)
        return result.stdout.decode("utf-8").strip()

    def restored_state(self, tables: list[str]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        # json_build_object takes at most 100 arguments (50 key/value pairs) in PostgreSQL.
        for start in range(0, len(tables), 40):
            batch = tables[start:start + 40]
            if not batch:
                continue
            parts = []
            for table in batch:
                schema, name = table.split(".", 1)
                parts.append(f"'{table.replace(chr(39), chr(39) * 2)}', "
                             f"(SELECT count(*) FROM ONLY {quote_ident(schema)}.{quote_ident(name)})")
            counts.update(json.loads(self.psql("SELECT json_build_object(" + ", ".join(parts) + ")::text;")))
        latest: dict[str, str] = {}
        exists = self.psql("SELECT to_regclass('public.telemetry_samples') IS NOT NULL;")
        if exists == "t":
            rows = self.psql(
                "SELECT COALESCE(json_object_agg(k, v), '{}')::text FROM (SELECT concat_ws('|', COALESCE(node_id,''), "
                "COALESCE(equipment_id,''), COALESCE(channel_id,''), COALESCE(metric,'')) AS k, "
                "max(captured_at) AS v FROM telemetry_samples GROUP BY 1) s;")
            latest = {k: normalize_timestamp(v) for k, v in json.loads(rows).items()}
        return {"table_counts": counts, "latest_captured_at": latest}

    def migrate(self) -> dict[str, Any]:
        env = self._env_file("migrate.env", {"DATABASE_URL": self._database_url(), "MQTT_ENABLED": "false",
                                             "OBJECT_STORAGE_BACKEND": "disabled", "RETENTION_ENABLED": "false"})
        before = self.psql("SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version;")
        base = ["run", "--rm", "--pull", "never", "--network", self.network, *self._label(), "--env-file", str(env),
                self.config.images["telemetry"]]
        self.docker(*base, "alembic", "upgrade", "head", timeout=3600)
        heads = self.docker(*base, "alembic", "heads").stdout.decode().split()
        after = self.psql("SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version;")
        head_ids = sorted(token for token in heads if re.fullmatch(r"[0-9a-zA-Z_]+", token) and token != "head")
        at_head = bool(head_ids) and sorted(after.split(",")) == head_ids
        self.checks.add("postgresql.migrations_at_head", at_head, {"before": before, "after": after, "heads": head_ids})
        post = self.restored_state(sorted(self.archive["table_counts"]))
        changed = compare_counts(self.restored_pg["table_counts"], post["table_counts"])
        return {"alembic_before": before, "alembic_after": after, "alembic_heads": head_ids,
                "upgrade_was_noop": before == after, "row_counts_changed_by_migration": changed}

    def _database_url(self) -> str:
        return (f"postgresql+psycopg://{self.config.pg_user}:{self.pg_password}@{self.containers['postgres']}:5432/"
                f"{self.config.pg_database}")

    def restore_objects(self, plaintext: Path, entry: dict[str, Any]) -> dict[str, Any]:
        volume = self.volumes["object-storage"]
        self.helper(volume, {"op": "extract_tar", "src": entry["path"]}, plaintext)
        expected = tar_listing(plaintext / entry["path"])
        tree = self.helper(volume, {"op": "tree"})
        restored = {path: (size, digest) for path, size, digest in tree["files"]}
        equal = restored == expected and tree["non_regular"] == 0
        self.checks.add("object_storage.tree_equals_archive", equal,
                        {"archive_files": len(expected), "restored_files": len(restored)})
        rows = json.loads(self.psql(
            "SELECT COALESCE(json_agg(json_build_object('id', id, 'equipment_id', equipment_id, 'storage_key', "
            "storage_key, 'sha256', checksum_sha256, 'size', size_bytes) ORDER BY id), '[]')::text "
            "FROM equipment_images;") or "[]") if self._table_exists("equipment_images") else []
        bucket = self.config.bucket
        missing, mismatched = [], []
        for row in rows:
            found = restored.get(f"{bucket}/{row['storage_key']}")
            if found is None:
                missing.append(row["id"])
            elif found[1] != row["sha256"] or found[0] != row["size"]:
                mismatched.append(row["id"])
        self.checks.add("object_storage.reference_integrity", not missing and not mismatched,
                        {"referenced": len(rows), "missing": missing[:50], "checksum_mismatch": mismatched[:50]})
        bucket_objects = sorted(p for p in restored if p.startswith(f"{bucket}/"))
        referenced = {f"{bucket}/{row['storage_key']}" for row in rows}
        sample = sorted(bucket_objects, key=lambda p: sha256_bytes(p.encode()))[:16]
        self.image_rows = rows
        return {"files": len(restored), "bucket": bucket, "bucket_objects": len(bucket_objects),
                "referenced_objects": len(rows), "orphan_objects": len(set(bucket_objects) - referenced),
                "missing_references": missing, "checksum_mismatches": mismatched,
                "hash_sample": [{"path_sha256": sha256_bytes(p.encode()), "sha256": restored[p][1]} for p in sample],
                "tree_sha256": sha256_bytes(canonical(sorted([p, *restored[p]] for p in restored)))}

    def _table_exists(self, table: str) -> bool:
        return self.psql(f"SELECT to_regclass('public.{table}') IS NOT NULL;") == "t"

    def start_object_storage(self) -> None:
        self.os_access = "nxdr" + secrets.token_hex(6)
        self.os_secret = secrets.token_urlsafe(30)
        env = self._env_file("object-storage.env", {
            "ROOT_ACCESS_KEY_ID": self.os_access, "ROOT_SECRET_ACCESS_KEY": self.os_secret, "VGW_PORT": ":9000",
            "VGW_REGION": "us-east-1", "VGW_HEALTH": "/health", "VGW_QUIET": "true"})
        self._run_service("object-storage", self.config.images["object_storage"],
                          ["--env-file", str(env), "--read-only", "-v", f"{self.volumes['object-storage']}:/data"],
                          ["posix", "/data"])

    def check_s3(self) -> dict[str, Any]:
        """Bucket privacy and S3-level object metadata on the RESTORED gateway (internal network only)."""
        env = self._env_file("s3-client.env", {"OBJECT_STORAGE_ACCESS_KEY_ID": self.os_access,
                                               "OBJECT_STORAGE_SECRET_ACCESS_KEY": self.os_secret,
                                               "OBJECT_STORAGE_REGION": "us-east-1"})
        base = ["run", "--rm", "-i", "--pull", "never", "--network", self.network, *self._label(), "--env-file",
                str(env), "-v", f"{SCRIPTS}:/opt/nexolab/scripts:ro", "--entrypoint", "python",
                self.config.images["telemetry"], "/opt/nexolab/scripts/object-storage-s3.py", "--endpoint",
                f"http://{self.containers['object-storage']}:9000"]
        self.docker(*base, "wait", timeout=180)
        private = self.docker(*base, "assert-private", "--bucket", self.config.bucket, check=False)
        is_private = private.returncode == 0 and b"private" in private.stdout
        self.checks.add("object_storage.bucket_private", is_private,
                        {"exit": private.returncode, "output": private.stdout.decode(errors="replace").strip()[-120:]})
        rows = getattr(self, "image_rows", [])
        result: dict[str, Any] = {"bucket_private": is_private, "stat_checked": 0, "etag_mismatches": 0,
                                  "content_type_mismatches": 0}
        if rows:
            meta = json.loads(self.psql(
                "SELECT COALESCE(json_object_agg(storage_key, json_build_object('etag', object_etag, 'media_type', "
                "media_type)), '{}')::text FROM equipment_images;"))
            head = ["run", "--rm", "-i", "--pull", "never", "--network", self.network, *self._label(), "--env-file",
                    str(env), "--entrypoint", "python", self.config.images["telemetry"], "-c", S3_HEAD_PROBE,
                    f"http://{self.containers['object-storage']}:9000", self.config.bucket]
            probe = self.docker(*head, input_bytes=json.dumps(sorted(meta)).encode(), check=False)
            stats = json.loads(probe.stdout.decode().strip().splitlines()[-1]) if probe.returncode == 0 else []
            present = [s for s in stats if s["status"] == 200]
            ok = probe.returncode == 0 and len(present) == len(meta)
            etag_bad = [s["key"] for s in present
                        if (meta[s["key"]]["etag"] or "").strip('"') != (s.get("etag") or "").strip('"')]
            type_bad = [s["key"] for s in present if meta[s["key"]]["media_type"] != s.get("content_type")]
            result.update({"stat_checked": len(stats), "present": len(present), "etag_mismatches": len(etag_bad),
                           "etag_missing": sum(1 for s in present if not s.get("etag")),
                           "content_type_mismatches": len(type_bad),
                           "metadata_fidelity": "PRESERVED" if not (etag_bad or type_bad) else "DEGRADED"})
            self.checks.add("object_storage.objects_present_via_s3", ok, {
                "objects": len(present), "expected": len(meta), "exit": probe.returncode,
                "stderr_tail": probe.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]})
            if etag_bad or type_bad:
                self.warnings.append(
                    f"FINDING: restored S3 metadata differs from the database for {len(set(etag_bad) | set(type_bad))} "
                    "object(s) (ETag/Content-Type missing or different). VersityGW's posix backend keeps object "
                    "metadata in extended attributes, which the leaf-A directory snapshot does not capture. Object "
                    "bytes and SHA-256 are intact and the application serves them, but S3 clients that require "
                    "ETag (e.g. object-storage-s3.py stat-keys) fail on the restored store")
        return result

    def restore_mqtt(self, plaintext: Path, entry: dict[str, Any]) -> dict[str, Any]:
        volume = self.volumes["mqtt-dynamic-security"]
        self.helper(volume, {"op": "extract_tar", "src": entry["path"]}, plaintext)
        expected = tar_listing(plaintext / entry["path"])
        tree = self.helper(volume, {"op": "tree"})
        restored = {path: (size, digest) for path, size, digest in tree["files"]}
        summary = self.helper(volume, {"op": "dynsec"})
        present = restored == expected and summary["clients"] > 0 and summary["roles"] > 0
        self.checks.add("mqtt.dynamic_security_present", present, summary)
        self._run_service("mqtt", self.config.images["mqtt"], ["-v", f"{volume}:/mosquitto/data"], [])

        def running() -> bool:
            state = self.docker.json("inspect", self.containers["mqtt"])[0]["State"]
            logs = self.docker("logs", self.containers["mqtt"], check=False)
            text = (logs.stdout + logs.stderr).decode("utf-8", "replace")
            return state.get("Running") is True and " running" in text
        try:
            self._wait("MQTT broker", running, 60)
            started = True
        except RestoreFailed:
            started = False
        state = self.docker.json("inspect", self.containers["mqtt"])[0]["State"]
        self.checks.add("mqtt.broker_started", started and state.get("Running") is True,
                        {"running": state.get("Running"), "exit_code": state.get("ExitCode")})
        return {"files": len(restored), "tree_equals_archive": restored == expected, "dynamic_security": summary}

    def restore_tree_store(self, store: str, plaintext: Path, entry: dict[str, Any]) -> dict[str, Any]:
        volume = self.volumes[store]
        self.helper(volume, {"op": "extract_tar", "src": entry["path"]}, plaintext)
        expected = tar_listing(plaintext / entry["path"])
        tree = self.helper(volume, {"op": "tree"})
        restored = {path: (size, digest) for path, size, digest in tree["files"]}
        ok = restored == expected
        self.checks.add(f"{store}.tree_equals_archive", ok, {"files": len(restored)})
        return {"files": len(restored), "tree_equals_archive": ok}

    def restore_sqlite(self, store: str, plaintext: Path, entry: dict[str, Any], name: str, uid: int) -> dict[str, Any]:
        volume = self.volumes[store]
        installed = self.helper(volume, {"op": "install_file", "src": entry["path"], "name": name, "uid": uid,
                                         "gid": uid, "mode": "0600"}, plaintext)
        check = self.helper(volume, {"op": "sqlite", "name": name})
        ok = check["integrity"] == "ok" and installed["sha256"] == entry["sha256"] == check["sha256"]
        self.checks.add(f"{store}.sqlite_restored", ok, {"integrity": check["integrity"]})
        return {"file": name, "integrity": check["integrity"], "table_counts": check["table_counts"],
                "sha256_matches_manifest": installed["sha256"] == entry["sha256"]}

    def restore_local_auth(self, plaintext: Path, entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
        private_pem = (plaintext / entries["local-auth-private-key"]["path"]).read_bytes()
        public_pem = (plaintext / entries["local-auth-public-key"]["path"]).read_bytes()
        self.public_pem = public_pem
        pair = keypair_matches(private_pem, public_pem)
        del private_pem
        self.checks.add("local_auth.keypair_matches", pair["matches"], {"public_key_sha256": pair["public_key_sha256"]})
        volume = self.volumes["local-auth"]
        self.helper(volume, {"op": "install_file", "src": entries["local-auth-private-key"]["path"],
                             "name": "private.pem", "uid": 10001, "gid": 10001, "mode": "0400"}, plaintext)
        self.helper(volume, {"op": "install_file", "src": entries["local-auth-public-key"]["path"],
                             "name": "public.pem", "uid": 10001, "gid": 10001, "mode": "0444"}, plaintext)
        return pair

    def start_telemetry(self) -> None:
        auth = self.config.local_auth
        env = self._env_file("telemetry.env", {
            "DATABASE_URL": self._database_url(), "DATABASE_CONNECT_TIMEOUT_SECONDS": "3",
            "MQTT_ENABLED": "false", "BROKER_CONTROL_ENABLED": "false", "RETENTION_ENABLED": "false",
            "OBJECT_STORAGE_BACKEND": "s3", "OBJECT_STORAGE_BUCKET": self.config.bucket,
            "OBJECT_STORAGE_ENDPOINT_URL": f"http://{self.containers['object-storage']}:9000",
            "OBJECT_STORAGE_PUBLIC_ENDPOINT_URL": f"http://{self.containers['object-storage']}:9000",
            "OBJECT_STORAGE_REGION": "us-east-1", "OBJECT_STORAGE_ACCESS_KEY_ID": self.os_access,
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": self.os_secret, "OBJECT_STORAGE_FORCE_PATH_STYLE": "true",
            "AUTH_MODE": "jwt", "AUTH_DEFAULT_ORGANIZATION_ID": auth["organization_id"], "AUTH_LOCAL_ENABLED": "true",
            "AUTH_LOCAL_PRIVATE_KEY_FILE": "/run/secrets/local-auth/private.pem",
            "AUTH_LOCAL_PUBLIC_KEY_FILE": "/run/secrets/local-auth/public.pem",
            "AUTH_LOCAL_ISSUER": auth["issuer"], "AUTH_LOCAL_AUDIENCE": auth["audience"],
            "AUTH_LOCAL_PROVIDER": "nexolab-local", "CORS_ALLOWED_ORIGINS": "",
            "INGESTION_SPOOL_PATH": "/app/data/telemetry-ingestion/spool.db",
        })
        self._run_service("telemetry", self.config.images["telemetry"], [
            "--env-file", str(env), "-v", f"{self.volumes['local-auth']}:/run/secrets/local-auth:ro",
            "-v", f"{self.volumes['central-ingestion-spool']}:/app/data/telemetry-ingestion"], [])

    def wait_ready(self) -> tuple[datetime, dict[str, Any]]:
        script = ("import json,urllib.request,urllib.error\n"
                  "try:\n r=urllib.request.urlopen('http://127.0.0.1:8082/health/ready',timeout=3);print(r.read().decode())\n"
                  "except urllib.error.HTTPError as e:\n print(e.read().decode())\n")
        last: dict[str, Any] = {}
        deadline = time.monotonic() + self.config.ready_timeout_seconds
        while time.monotonic() < deadline:
            state = self.docker.json("inspect", self.containers["telemetry"])[0]["State"]
            if not state.get("Running"):
                logs = self.docker("logs", "--tail", "20", self.containers["telemetry"], check=False)
                raise RestoreFailed("telemetry service exited: " +
                                    (logs.stdout + logs.stderr).decode("utf-8", "replace")[-400:])
            result = self.docker("exec", self.containers["telemetry"], "python", "-c", script, check=False)
            with contextlib.suppress(ValueError, IndexError):
                last = json.loads(result.stdout.decode().strip().splitlines()[-1])
                if last.get("status") == "ready" and last.get("database") == "ready":
                    return self.clock(), last
            time.sleep(1)
        raise RestoreFailed(f"/health/ready not reached within {self.config.ready_timeout_seconds}s: {last}")

    def egress_blocked(self) -> dict[str, Any]:
        production = sorted({*getattr(self, "production_addresses", []),
                             *(h for h in self.config.production_hosts if _is_ip(h))})
        targets = {"connect": [list(p) for p in self.config.internet_probes] +
                   [[address, port] for address in production for port in self.config.probe_ports],
                   "resolve": [h for h in self.config.production_hosts if not _is_ip(h)] + ["example.com"]}
        result = self.docker("exec", self.containers["telemetry"], "python", "-c", EGRESS_PROBE, json.dumps(targets))
        data = json.loads(result.stdout.decode().strip().splitlines()[-1])
        blocked = not data["reachable"] and not [n for n in data["resolved"] if n != "example.com"]
        data["internet_name_resolution_from_stack"] = "example.com" in data["resolved"]
        self.checks.add("isolation.container_egress_blocked", blocked and not data["reachable"], data)
        return data

    def probe_application(self, dashboards: list[dict[str, str]]) -> dict[str, Any]:
        password = self.config.local_auth["password_file"].read_text(encoding="utf-8").strip()
        payload = json.dumps({"username": self.config.local_auth["username"], "password": password,
                              "organization_id": self.config.local_auth["organization_id"],
                              "dashboards": dashboards,
                              "images": [{"id": r["id"], "equipment_id": r["equipment_id"]}
                                         for r in getattr(self, "image_rows", [])[:16]]}).encode()
        del password
        result = self.docker("exec", "-i", self.containers["telemetry"], "python", "-c", PROBE, input_bytes=payload)
        data = json.loads(result.stdout.decode().strip().splitlines()[-1])
        token = data.pop("access_token", None)
        signature = verify_rs256(token, self.public_pem) if token else {"verified": False, "reason": "no token"}
        login_ok = data.get("login_status") == 200 and data.get("session_status") == 200 and signature["verified"]
        self.checks.add("local_auth.login_with_restored_keys", login_ok,
                        {"login_status": data.get("login_status"), "session_status": data.get("session_status"),
                         "token_signature": signature})
        images = data.get("image_content", [])
        expected = {r["id"]: r["sha256"] for r in getattr(self, "image_rows", [])}
        if images:
            self.checks.add("object_storage.images_served_by_api",
                            all(i["status"] == 200 and i["sha256"] == expected.get(i["id"]) for i in images),
                            images)
        data["token_signature"] = signature
        return data

    # -- run ------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        config = self.config
        started_at = self.clock()
        receipt: dict[str, Any] = self.receipt
        receipt.update({
            "schema_version": 1, "kind": RECEIPT_KIND, "issue": 1632,
            "evidence_class": "LOCAL_REHEARSAL_NOT_SITE_EVIDENCE" if config.rehearsal else "SITE_ISOLATED_RESTORE",
            "statement": REHEARSAL_STATEMENT if config.rehearsal else SITE_STATEMENT,
            "status": "FAIL", "tool": {"script_sha256": sha256_file(Path(__file__))[0]},
            "started_at": iso(started_at), "stores": {}, "warnings": self.warnings,
        })
        plaintext_dir = config.work_dir / "plaintext"
        try:
            receipt["target"] = self.preflight()
            receipt["images"] = self.inspect_images(receipt["target"]["docker_architecture"])
            restore_started = self.clock()
            receipt["restore_started_at"] = iso(restore_started)
            key = drs.load_key(config.key_file)
            custody, _ = read_json_file(config.custody_receipt, "custody receipt")
            inputs = verify_custody(bundle_path=config.bundle, custody=custody, key=key)
            if receipt["target"]["identity_sha256"] == custody["destination_identity_sha256"]:
                raise Refused("restore target identity equals the custody destination identity")
            same_device = _same_device(config.bundle, config.work_dir)
            if same_device:
                message = "bundle is on the same filesystem as the restore work_dir (expected: mounted off-device media)"
                if not config.rehearsal:
                    raise Refused(message)
                self.warnings.append(message)
            self.checks.add("custody.verified", True, {"destination_kind": custody["destination_kind"]})
            verified = drs.verify_file(config.bundle, key)
            self.checks.add("stream.authenticated", True, {"entries": len(verified.entries)})
            manifest = verified.manifest
            entries = compare_stream_with_manifest(verified.entries, manifest)
            binding = bind_source_manifest(custody, manifest)
            leaf_a = "not_available_on_media"
            if config.backup_receipt is not None:
                backup, backup_bytes = read_json_file(config.backup_receipt, "backup receipt")
                cross_check_backup_receipt(backup, bundle_name=config.bundle.name, key=key, manifest=manifest,
                                           bundle_sha256=inputs["bundle_sha256"], bundle_bytes=inputs["bundle_bytes"])
                leaf_a = sha256_bytes(backup_bytes)
            self.checks.add("stream.matches_custody_manifest", True,
                            {"source_manifest_binding": binding, "leaf_a_receipt": leaf_a})
            receipt["inputs"] = {
                **inputs, "bundle_name": custody["bundle_name"], "custody_receipt_sha256":
                sha256_file(config.custody_receipt)[0], "destination_kind": custody["destination_kind"],
                "destination_identity_sha256": custody["destination_identity_sha256"],
                "custody_copied_at": custody["copied_at"], "key_fingerprint": drs.key_fingerprint(key),
                "source_manifest_binding": binding, "backup_created_at": manifest["created_at"],
                "backup_commit": manifest.get("commit"), "leaf_a_receipt_sha256": leaf_a,
            }
            receipt["resources"] = self.create_resources()
            config.work_dir.mkdir(mode=0o700, parents=True)
            with plaintext_session(config.bundle, key, plaintext_dir) as (plaintext, _):
                del key
                stores = receipt["stores"]
                for store in manifest["stores"]:
                    if store.get("disposition") == "rebuildable_excluded":
                        stores[store["id"]] = {"disposition": "rebuildable_excluded", "reason": store["reason"],
                                               "status": "excluded", "new_target": True, "source_untouched": True,
                                               "verification_sha256": None}
                pg = self.restore_postgresql(plaintext, entries["postgresql"])
                stores["postgresql"] = store_verification_block(
                    "postgresql", pg, self._passed("postgresql."))
                obj = self.restore_objects(plaintext, entries["object-storage"])
                stores["object-storage"] = store_verification_block(
                    "object-storage", obj, self._passed("object_storage."))
                mqtt = self.restore_mqtt(plaintext, entries["mqtt-dynamic-security"])
                stores["mqtt-dynamic-security"] = store_verification_block(
                    "mqtt-dynamic-security", mqtt, self._passed("mqtt."))
                if "edge-mqtt-persistence" in entries:
                    edge = self.restore_tree_store("edge-mqtt-persistence", plaintext, entries["edge-mqtt-persistence"])
                    stores["edge-mqtt-persistence"] = store_verification_block(
                        "edge-mqtt-persistence", edge, self._passed("edge-mqtt-persistence."))
                if "edge-sqlite-outbox" in entries:
                    outbox = self.restore_sqlite("edge-sqlite-outbox", plaintext, entries["edge-sqlite-outbox"],
                                                 "outbox.sqlite", 0)
                    stores["edge-sqlite-outbox"] = store_verification_block(
                        "edge-sqlite-outbox", outbox, self._passed("edge-sqlite-outbox."))
                if "central-ingestion-spool" in entries:
                    spool = self.restore_sqlite("central-ingestion-spool", plaintext,
                                                entries["central-ingestion-spool"], "spool.db", 10001)
                    stores["central-ingestion-spool"] = store_verification_block(
                        "central-ingestion-spool", spool, self._passed("central-ingestion-spool."))
                pair = self.restore_local_auth(plaintext, entries)
                receipt["local_auth_keypair"] = pair
            self.checks.add("plaintext.removed", not plaintext_dir.exists(), {"path_removed": True})
            receipt["postgresql_migration"] = self.migrate()
            self.start_object_storage()
            receipt["object_storage_s3"] = self.check_s3()
            self.start_telemetry()
            ready_at, ready = self.wait_ready()
            receipt["ready_at"] = iso(ready_at)
            self.checks.add("application.ready_database", ready.get("database") == "ready", ready)
            self.checks.add("isolation.no_published_ports", True, {"containers": sorted(self.containers.values())})
            receipt["egress"] = self.egress_blocked()
            observation = self._load_observation()
            dashboards = list(config.dashboards) or [
                {k: d[k] for k in ("id", "from", "to", "timezone")} for d in (observation or {}).get("dashboards", [])]
            app = self.probe_application(dashboards)
            receipt["application"] = app
            receipt["dashboards"] = self._compare_dashboards(app.get("dashboards", []), observation)
            login = next(i for i in self.checks.items if i["name"] == "local_auth.login_with_restored_keys")
            auth_block = {"keypair": pair, "login": {"passed": login["passed"],
                                                     "token_signature": login["detail"]["token_signature"]}}
            for store_id in ("local-auth-private-key", "local-auth-public-key"):
                receipt["stores"][store_id] = store_verification_block(
                    "local-auth-keypair", auth_block, self._passed("local_auth."))
            receipt["postgresql"] = {
                "archive_table_counts": self.archive["table_counts"],
                "restored_table_counts": self.restored_pg["table_counts"],
                "domains": self._domains(),
                "latest_captured_at": self.restored_pg["latest_captured_at"],
            }
            backup_created = parse_utc(manifest["created_at"], "backup created_at")
            if observation is not None:
                comparison = compare_with_observation(observation, self.restored_pg["table_counts"],
                                                      self.restored_pg["latest_captured_at"], backup_created)
                self.checks.add("source_observation.consistent", comparison["passed"], comparison)
                receipt["source_observation"] = {"sha256": sha256_file(config.source_observation)[0],
                                                 "observed_at": observation.get("observed_at"), **comparison}
            newest = max((datetime.fromisoformat(v.replace("Z", "+00:00"))
                          for v in self.restored_pg["latest_captured_at"].values()), default=None)
            objectives = json.loads(config.objectives_file.read_text(encoding="utf-8")).get("objectives", {})
            receipt["rpo_rto"] = compute_rpo_rto(backup_created_at=backup_created, restore_started_at=restore_started,
                                                 ready_at=ready_at, newest_data_at=newest, objectives=objectives)
        except BaseException as exc:
            receipt["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
            receipt["plaintext_removed_after_failure"] = not plaintext_dir.exists()
            raise
        finally:
            remove_tree(self.secrets_dir)
            receipt["checks"] = self.checks.items
            receipt["completed_at"] = iso(self.clock())
            receipt["status"] = evaluate_status(self.checks, rehearsal=config.rehearsal)
            receipt["failed_checks"] = self.checks.failed()
            receipt["waived_checks"] = self.checks.waived()
            receipt["acceptance_basis"] = ("pg_restore into a fresh PostgreSQL with exact per-table row counts versus "
                                           "the archive data, application readiness, login and API rendering; never "
                                           "pg_restore --list alone")
        return receipt

    def _passed(self, prefix: str) -> bool:
        relevant = [i for i in self.checks.items if i["name"].startswith(prefix)]
        return bool(relevant) and all(i["passed"] for i in relevant)

    def _domains(self) -> dict[str, Any]:
        mapping = parse_domain_tables((SCRIPTS / "disaster-recovery-domain-counts.sql").read_text(encoding="utf-8"))
        mapping.update(EXTRA_DOMAINS)
        return {domain: {"table": table, "archive": self.archive["table_counts"].get(table),
                         "restored": self.restored_pg["table_counts"].get(table)}
                for domain, table in sorted(mapping.items())}

    def _load_observation(self) -> dict[str, Any] | None:
        if self.config.source_observation is None:
            return None
        observation, _ = read_json_file(self.config.source_observation, "source observation", 16 * 1024 * 1024)
        if observation.get("kind") != OBSERVATION_KIND or observation.get("schema_version") != 1:
            raise Refused("source observation kind/schema is unsupported")
        return observation

    def _compare_dashboards(self, restored: list[dict[str, Any]], observation: dict[str, Any] | None) -> dict[str, Any]:
        source = {d["id"]: d for d in (observation or {}).get("dashboards", [])}
        results = []
        for item in restored:
            expected = source.get(item["id"])
            entry = {"id": item["id"], "window": [item["from"], item["to"]], "csv_rows": item.get("csv_rows"),
                     "csv_sha256": item.get("csv_sha256"), "view_settings_present": item.get("view_settings_present")}
            if expected is None:
                entry["source_comparison"] = "UNVERIFIED_NO_SOURCE_OBSERVATION"
                entry["passed"] = False
            else:
                entry["source_csv_sha256"] = expected.get("csv_sha256")
                entry["source_view_settings_sha256"] = expected.get("view_settings_sha256")
                entry["passed"] = (item.get("get_status") == 200 and item.get("csv_status") == 200
                                   and item.get("csv_sha256") == expected.get("csv_sha256")
                                   and item.get("view_settings_sha256") == expected.get("view_settings_sha256"))
            results.append(entry)
        if restored:
            self.checks.add("dashboards.same_series_as_source", all(r["passed"] for r in results), results)
        return {"compared": results}

    def teardown(self) -> dict[str, Any]:
        return teardown(self.docker, self.config.prefix)


def tar_listing(path: Path) -> dict[str, tuple[int, str]]:
    listing: dict[str, tuple[int, str]] = {}
    with tarfile.open(path, mode="r:") as archive:
        for member in archive:
            if member.isfile():
                handle = archive.extractfile(member)
                assert handle is not None
                digest = hashlib.sha256()
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                listing[member.name] = (member.size, digest.hexdigest())
    return listing


def _same_device(bundle: Path, work_dir: Path) -> bool:
    probe = work_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return os.stat(bundle).st_dev == os.stat(probe).st_dev
    except OSError:
        return False


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _normal_arch(value: str) -> str:
    value = value.lower()
    return {"x86_64": "amd64", "aarch64": "arm64", "arm64/v8": "arm64"}.get(value, value)


def teardown(docker: Docker, prefix: str) -> dict[str, Any]:
    """Removes ONLY resources that carry this run's label AND the nx-dr- prefix."""
    if not PREFIX.fullmatch(prefix):
        raise Refused("invalid prefix")
    label = f"label={LABEL}={prefix}"
    removed: dict[str, list[str]] = {"containers": [], "volumes": [], "networks": []}
    for kind, list_args, rm_args in (
        ("containers", ["ps", "-a", "--filter", label, "--format", "{{.Names}}"], ["rm", "-f", "-v"]),
        ("volumes", ["volume", "ls", "--filter", label, "--format", "{{.Name}}"], ["volume", "rm", "-f"]),
        ("networks", ["network", "ls", "--filter", label, "--format", "{{.Name}}"], ["network", "rm"]),
    ):
        names = [n for n in docker(*list_args).stdout.decode().split() if n.startswith(prefix + "-")]
        for name in names:
            docker(*rm_args, name, check=False)
            removed[kind].append(name)
    return removed


OBSERVE_SQL = r"""-- #1632 source observation (READ-ONLY). Run by the owner against production right AFTER the backup:
--   docker exec -i nexolab-central-postgres-1 psql -X -At -U nexolab -d nexolab < observe.sql > observation-db.json
-- It only SELECTs; it never writes. Full-table counts can take minutes on a large telemetry table.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TimeZone = 'UTC';
SELECT json_build_object(
  'table_counts', (SELECT json_object_agg('public.' || c.relname,
      (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM ONLY public.%I', c.relname),
       false, true, '')))[1]::text::bigint)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')),
  'latest_captured_at', (SELECT COALESCE(json_object_agg(k, to_char(v AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')), '{}'::json) FROM (SELECT concat_ws('|', COALESCE(node_id,''),
      COALESCE(equipment_id,''), COALESCE(channel_id,''), COALESCE(metric,'')) AS k, max(captured_at) AS v
      FROM telemetry_samples GROUP BY 1) s)
)::text;
COMMIT;
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NEXOLAB #1632 isolated restore and verification")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "restore"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        if name == "restore":
            command.add_argument("--teardown-after", action="store_true",
                                 help="remove the restored stack after verification (default: keep it for inspection)")
    down = sub.add_parser("teardown", help="remove only the labelled nx-dr- resources of one run")
    down.add_argument("--prefix", required=True)
    check = sub.add_parser("verify-receipt")
    check.add_argument("--receipt", type=Path, required=True)
    sub.add_parser("observe-sql", help="print the read-only source observation SQL (the tool never connects)")
    args = parser.parse_args(argv)
    if args.command == "observe-sql":
        print(OBSERVE_SQL)
        return EXIT_OK
    if args.command == "teardown":
        try:
            print(json.dumps(teardown(Docker(), args.prefix), sort_keys=True))
        except (Refused, RestoreFailed) as exc:
            print(json.dumps({"status": "FAILED", "reason": str(exc)}), file=sys.stderr)
            return EXIT_FAILED
        return EXIT_OK
    if args.command == "verify-receipt":
        result = verify_receipt_file(args.receipt)
        print(json.dumps(result, sort_keys=True))
        return EXIT_OK if result["sidecar_matches"] and result["status_consistent"] else EXIT_FAILED
    try:
        config = load_config(args.config)
    except Refused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}), file=sys.stderr)
        return EXIT_REFUSED
    restore = Restore(config)
    if args.command == "preflight":
        try:
            target = restore.preflight()
        except (Refused, RestoreFailed) as exc:
            print(json.dumps({"status": "REFUSED", "reason": str(exc)}), file=sys.stderr)
            return EXIT_REFUSED
        print(json.dumps({"status": "PREFLIGHT_OK", "target_identity_sha256": target["identity_sha256"],
                          "warnings": restore.warnings}, sort_keys=True))
        return EXIT_OK
    code = EXIT_FAILED
    try:
        receipt = restore.run()
        code = EXIT_OK if receipt["status"] in ("PASS", "REHEARSAL_PASS", "REHEARSAL_PASS_WITH_WAIVERS")             else EXIT_FAILED
    except Refused as exc:
        restore.receipt["refused"] = str(exc)
        code = EXIT_REFUSED
    except (RestoreFailed, drs.StreamFailure, OSError, KeyError, ValueError) as exc:
        restore.receipt.setdefault("error", {"type": type(exc).__name__, "message": str(exc)[:500]})
        code = EXIT_FAILED
    finally:
        receipt = restore.receipt
        if getattr(restore, "created_resources", False) and (code != EXIT_OK or args.teardown_after):
            receipt["teardown"] = restore.teardown()
    path, digest = write_receipt(receipt, config.evidence_dir)
    fields = v2_fields(receipt, digest) if receipt.get("target") and receipt.get("inputs") else None
    if fields is not None:
        (config.evidence_dir / "inventory-v2-restore-fields.json").write_text(
            json.dumps(fields, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt.get("status"), "receipt": str(path), "receipt_sha256": digest,
                      "failed_checks": receipt.get("failed_checks"), "evidence_class": receipt.get("evidence_class"),
                      "waived_checks": receipt.get("waived_checks"),
                      "reason": receipt.get("refused") or receipt.get("error"),
                      "rpo_rto": {k: receipt.get("rpo_rto", {}).get(k) for k in ("rpo_seconds", "rto_seconds")}},
                     sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
