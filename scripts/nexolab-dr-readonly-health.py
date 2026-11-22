#!/usr/bin/env python3
"""NEXOLAB #1441: read-only offline DR observability, NEVER site readiness approval.

Missing/stale backup or systemd timer evidence is an alarm, not permission to
restart services, take backups, erase data or activate production recovery.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

GiB = 1024 ** 3
TIMER = "nexolab-dr-backup.timer"
PROPERTIES = {"LoadState", "UnitFileState", "ActiveState", "Persistent"}
EXPECTED = {"postgresql", "object-storage", "mqtt-dynamic-security",
            "edge-sqlite-outbox", "local-auth-private-key",
            "local-auth-public-key", "central-ingestion-spool", "edge-mqtt-persistence"}
STATUS = {"BLOCKED", "UNVERIFIED", "REPORTED_OK"}
OBJECTIVES_FILE = Path(__file__).resolve().parents[1] / "security" / "disaster-recovery-assets.json"
RESTORE_RECEIPT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_RESTORE_MAX_AGE_DAYS = 35
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CHECK_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
SIDECAR_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._-]{1,200})\r?\n$")
SITE_EVIDENCE_CLASS = "SITE_ISOLATED_RESTORE"
KNOWN_EVIDENCE_CLASSES = {SITE_EVIDENCE_CLASS, "LOCAL_REHEARSAL_NOT_SITE_EVIDENCE"}
# A site-mode run is always configured with the offline proof, a source observation and at least one
# saved dashboard (load_config refuses site mode otherwise), so a genuine site receipt carries these too.
SITE_MODE_CHECKS = ("isolation.internet_disconnected", "source_observation.consistent",
                    "dashboards.same_series_as_source")
RECEIPT_TYPES = {
    "evidence_class": str, "statement": str, "status": str, "started_at": str, "restore_started_at": str,
    "ready_at": str, "completed_at": str, "stores": dict, "warnings": list, "target": dict, "inputs": dict,
    "checks": list, "failed_checks": list, "waived_checks": list, "rpo_rto": dict, "object_storage_s3": dict,
    "egress": dict,
}


class HealthBlocked(ValueError):
    pass


def read_sanitized_receipt(path: Path) -> dict:
    try:
        st = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(st.st_mode):
            raise HealthBlocked("evidence is a symlink or non-regular file")
        if not 0 < st.st_size <= 512 * 1024 or stat.S_IMODE(st.st_mode) & 0o077:
            raise HealthBlocked("evidence size or mode is unsafe; require 0600")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HealthBlocked("protected sanitized receipt is unavailable") from exc
    if not isinstance(data, dict):
        raise HealthBlocked("receipt must be a JSON object")
    return data


def read_timer() -> dict[str, str]:
    """Exact allowlisted read-only systemctl query; no shell or service changes."""
    argv = [
        "systemctl", "show", TIMER, "--no-pager",
        *[f"--property={name}" for name in sorted(PROPERTIES)],
    ]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HealthBlocked("systemd timer metadata not available") from exc
    if result.returncode != 0 or len(result.stdout) > 2048:
        raise HealthBlocked("read-only systemd timer query failed")
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            raise HealthBlocked("invalid systemd property evidence")
        key, value = line.split("=", 1)
        if key not in PROPERTIES or key in properties or len(value) > 128:
            raise HealthBlocked("unexpected or duplicate systemd metadata")
        properties[key] = value
    if set(properties) != PROPERTIES:
        raise HealthBlocked("missing systemd timer metadata")
    return properties


def verify_structural_contract(inventory: dict) -> None:
    script = Path(__file__).with_name("validate-site-dr-inventory-v2.py")
    spec = importlib.util.spec_from_file_location("nexolab_dr_v2_validator", script)
    if spec is None or spec.loader is None:
        raise HealthBlocked("local v2 contract unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.validate_site_inventory(inventory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HealthBlocked("8-store inventory does not satisfy v2 contract") from exc


def offdevice_reverifier(destination: Path):
    """#1631: returns a callable that RE-READS the newest bundle on a mounted destination and
    compares it with its custody receipt. A receipt alone (a claim) never changes the gate."""
    def run() -> dict:
        script = Path(__file__).with_name("nexolab-dr-offdevice-copy.py")
        spec = importlib.util.spec_from_file_location("nexolab_dr_offdevice_copy", script)
        if spec is None or spec.loader is None:
            raise HealthBlocked("local off-device copy contract unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            return module.reverify_destination(destination)
        except (module.Blocked, module.CopyFailed, OSError) as exc:
            raise HealthBlocked(f"off-device copy not re-verified: {exc}") from exc
    return run


# ------------------------------------------------------------------ #1632 isolated restore receipt


def _load_local_script(name: str, filename: str):
    """Loads a sibling script read-only (registered so its dataclasses resolve their module)."""
    script = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise HealthBlocked(f"local {filename} contract unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # missing dependency or broken script keeps the gate closed
        sys.modules.pop(spec.name, None)
        raise HealthBlocked(f"local {filename} contract unavailable") from exc
    return module


def _read_regular_bytes(path: Path, label: str, limit: int) -> bytes:
    try:
        st = path.lstat()
    except OSError as exc:
        raise HealthBlocked(f"{label} is missing or unreadable") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise HealthBlocked(f"{label} is a symlink or non-regular file")
    if not 0 < st.st_size <= limit:
        raise HealthBlocked(f"{label} is empty or larger than {limit} bytes")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HealthBlocked(f"{label} is missing or unreadable") from exc
    if len(data) != st.st_size:
        raise HealthBlocked(f"{label} changed while it was read")
    return data


def _strict_json_object(data: bytes, label: str) -> dict:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise HealthBlocked(f"{label} contains duplicate keys")
            out[key] = value
        return out

    def constant(_token):
        raise HealthBlocked(f"{label} contains non-finite numbers")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HealthBlocked(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise HealthBlocked(f"{label} must be a JSON object")
    return value


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HealthBlocked(f"restore receipt {label} is not a UTC timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HealthBlocked(f"restore receipt {label} is malformed") from exc
    if stamp.utcoffset() != timedelta(0):
        raise HealthBlocked(f"restore receipt {label} must be UTC")
    return stamp


def _seconds(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise HealthBlocked(f"restore receipt {label} missing or not a non-negative number")
    return float(value)


def _load_objectives(path: Path) -> dict:
    try:
        objectives = json.loads(path.read_text(encoding="utf-8"))["objectives"]
        rpo, rto = objectives["software_rpo_seconds"], objectives["software_restore_target_seconds"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise HealthBlocked("RPO/RTO objectives (security/disaster-recovery-assets.json) unavailable") from exc
    if type(rpo) not in (int, float) or type(rto) not in (int, float) or rpo < 0 or rto < 0:
        raise HealthBlocked("RPO/RTO objectives are not non-negative numbers")
    return {"software_rpo_seconds": rpo, "software_restore_target_seconds": rto}


def _check_receipt_mode_and_checks(receipt: dict, ir) -> list:
    evidence_class = receipt["evidence_class"]
    if evidence_class != SITE_EVIDENCE_CLASS:
        shown = evidence_class if evidence_class in KNOWN_EVIDENCE_CLASSES else "unknown"
        raise HealthBlocked(f"not a site-mode receipt (evidence_class={shown}); a rehearsal is never site evidence")
    if receipt["statement"] != ir.SITE_STATEMENT or "rehearsal" in receipt["statement"].lower():
        raise HealthBlocked("receipt statement is not the site-mode statement")
    if receipt["status"] != "PASS":
        raise HealthBlocked("receipt status is not PASS")
    checks = receipt["checks"]
    if receipt["waived_checks"] or any(isinstance(i, dict) and i.get("waived") for i in checks) \
            or any("waived" in w.lower() or "rehearsal" in w.lower() for w in receipt["warnings"]):
        raise HealthBlocked("receipt carries rehearsal waivers; waivers never count as site evidence")
    names: list = []
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) \
                or not CHECK_NAME.fullmatch(item["name"]) or type(item.get("passed")) is not bool:
            raise HealthBlocked("restore receipt schema: malformed check entry")
        names.append(item["name"])
    if len(names) != len(set(names)):
        raise HealthBlocked("restore receipt lists a check more than once")
    not_passed = sorted(i["name"] for i in checks if i["passed"] is not True)
    isolation_bad = [n for n in not_passed if n.startswith("isolation.")]
    if isolation_bad:
        raise HealthBlocked(f"isolation check(s) not PASS: {', '.join(isolation_bad)}")
    missing = [n for n in (*ir.REQUIRED_CHECKS, *SITE_MODE_CHECKS) if n not in names]
    if missing:
        raise HealthBlocked(f"mandatory check(s) missing: {', '.join(missing)}")
    if not_passed or receipt["failed_checks"]:
        raise HealthBlocked(f"verification check(s) not PASS: {', '.join(not_passed) or 'failed_checks set'}")
    if ir.evaluate_status(ir.Checks(list(checks)), rehearsal=False) != "PASS":
        raise HealthBlocked("receipt status is inconsistent with its checks")
    target = receipt["target"]
    isolation, internet = target.get("isolation"), target.get("internet")
    if not isinstance(isolation, dict) or isolation.get("isolated") is not True or isolation.get("findings") \
            or not isinstance(internet, dict) or internet.get("internet_reachable") is not False:
        raise HealthBlocked("target isolation/offline proof is not recorded as isolated and offline")
    if receipt["egress"].get("reachable") != []:
        raise HealthBlocked("restored stack egress was not recorded as blocked")
    return checks


def _check_fidelity(receipt: dict) -> None:
    s3 = receipt["object_storage_s3"]
    if s3.get("bucket_private") is not True:
        raise HealthBlocked("restored bucket privacy not recorded")
    fidelity = s3.get("metadata_fidelity")
    if fidelity not in (None, "PRESERVED") or (s3.get("stat_checked", 0) and fidelity != "PRESERVED") \
            or any(s3.get(k, 0) != 0 for k in ("etag_mismatches", "etag_missing", "content_type_mismatches")):
        raise HealthBlocked("object metadata fidelity is not PRESERVED (a degraded restore is not accepted)")
    for warning in receipt["warnings"]:
        lowered = warning.lower()
        if "same filesystem" in lowered:
            raise HealthBlocked("bundle was restored from the restore host's own filesystem, not off-device media")
        if "architecture" in lowered:
            raise HealthBlocked("image architecture differed from the target (emulated); fidelity not demonstrated")
    if receipt["warnings"]:
        raise HealthBlocked(f"receipt carries {len(receipt['warnings'])} warning(s); the strict default accepts none")


def _check_stores(receipt: dict, ir) -> None:
    stores = receipt["stores"]
    if set(stores) != set(ir.V2_STORES):
        raise HealthBlocked("receipt does not classify all eight stores exactly once")
    auth_hashes = set()
    for store_id, block in stores.items():
        if not isinstance(block, dict):
            raise HealthBlocked(f"{store_id}: malformed store block")
        if block.get("disposition") == "rebuildable_excluded":
            if store_id not in ir.REBUILDABLE or block.get("status") != "excluded":
                raise HealthBlocked(f"{store_id}: invalid exclusion")
            continue
        if block.get("status") != "verified" or block.get("new_target") is not True \
                or block.get("source_untouched") is not True or not isinstance(block.get("verification"), dict):
            raise HealthBlocked(f"{store_id}: store not verified on a new target")
        hash_id = "local-auth-keypair" if store_id.startswith("local-auth-") else store_id
        expected = ir.store_verification_block(hash_id, block["verification"], True)["verification_sha256"]
        if block.get("verification_sha256") != expected:
            raise HealthBlocked(f"{store_id}: verification_sha256 does not match its verification block")
        if hash_id == "local-auth-keypair":
            auth_hashes.add(expected)
    if len(auth_hashes) != 1:
        raise HealthBlocked("local-auth key pair stores are not verified together")


def verify_restore_receipt(
    receipt_path: Path | None,
    custody_path: Path | None,
    *,
    now: datetime,
    max_age: timedelta = timedelta(days=DEFAULT_RESTORE_MAX_AGE_DAYS),
    offdevice: dict | None = None,
    objectives_file: Path = OBJECTIVES_FILE,
    restore_module=None,
) -> dict:
    """#1632: re-verifies a site-mode isolated restore receipt locally; raises HealthBlocked otherwise.

    The receipt is the restore tool's own attestation. Acceptance proves that the supplied receipt is
    intact, internally consistent, strict site evidence and bound to the verified off-device copy. It is
    NOT an independent observation of the physical restore and NOT production readiness."""
    if receipt_path is None:
        raise HealthBlocked("--custody-receipt given without --restore-receipt")
    if custody_path is None:
        raise HealthBlocked("--custody-receipt is required to bind the restored bundle to its custody receipt")
    ir = restore_module or _load_local_script("nexolab_dr_isolated_restore_health", "nexolab-dr-isolated-restore.py")
    oc = ir.offdevice

    # 1. exact bytes and the .sha256 sidecar written by the restore tool
    data = _read_regular_bytes(receipt_path, "restore receipt", RESTORE_RECEIPT_MAX_BYTES)
    digest = hashlib.sha256(data).hexdigest()
    sidecar = receipt_path.with_name(receipt_path.name + ".sha256")
    try:
        line = _read_regular_bytes(sidecar, "restore receipt .sha256 sidecar", 4096).decode("ascii")
    except UnicodeError as exc:
        raise HealthBlocked("restore receipt .sha256 sidecar is not ASCII") from exc
    match = SIDECAR_LINE.fullmatch(line)
    if match is None or match.group(2) != receipt_path.name:
        raise HealthBlocked("restore receipt .sha256 sidecar is malformed or names another file")
    if match.group(1) != digest:
        raise HealthBlocked("restore receipt bytes do not match the .sha256 sidecar (tampered or replaced)")

    # 2. receipt schema
    receipt = _strict_json_object(data, "restore receipt")
    if receipt.get("kind") != ir.RECEIPT_KIND or type(receipt.get("schema_version")) is not int \
            or receipt.get("schema_version") != 1 or receipt.get("issue") != 1632:
        raise HealthBlocked("not a nexolab-dr-isolated-restore-receipt v1 (#1632)")
    for key in ("error", "refused", "plaintext_removed_after_failure"):
        if key in receipt:
            raise HealthBlocked(f"restore receipt records a failed or refused run ({key})")
    for key, kind in RECEIPT_TYPES.items():
        if not isinstance(receipt.get(key), kind):
            raise HealthBlocked(f"restore receipt schema: {key} missing or of the wrong type")
    if not all(isinstance(item, str) for item in receipt["warnings"]):
        raise HealthBlocked("restore receipt schema: warnings must be strings")

    # 3. site mode, no waivers, isolation and every verification check strictly PASS
    checks = _check_receipt_mode_and_checks(receipt, ir)
    # 4. fidelity: degraded object metadata or any warning never yields REPORTED_OK (strict default)
    _check_fidelity(receipt)

    # 5. custody binding: restored copy == custody-verified off-device copy; target != destination
    inputs = receipt["inputs"]
    try:
        custody = oc.read_receipt(custody_path)
    except (oc.CopyFailed, OSError) as exc:
        raise HealthBlocked(f"custody receipt rejected: {exc}") from exc
    custody_sha = hashlib.sha256(_read_regular_bytes(custody_path, "custody receipt", 64 * 1024)).hexdigest()
    if inputs.get("custody_receipt_sha256") != custody_sha:
        raise HealthBlocked("restore receipt was not produced from this custody receipt (custody_receipt_sha256)")
    for key, custody_key in (("bundle_sha256", "bundle_sha256"), ("bundle_bytes", "bundle_bytes"),
                             ("bundle_name", "bundle_name"), ("destination_kind", "destination_kind"),
                             ("destination_identity_sha256", "destination_identity_sha256"),
                             ("custody_copied_at", "copied_at")):
        if inputs.get(key) != custody[custody_key]:
            raise HealthBlocked(f"restored bundle does not match the custody receipt ({key})")
    if custody["destination_kind"] not in oc.DESTINATION_KINDS or custody["source_disk_independent"] is not True:
        raise HealthBlocked("restore did not start from an independent off-device copy")
    custody_check = next(i for i in checks if i["name"] == "custody.verified")
    if not isinstance(custody_check.get("detail"), dict) \
            or custody_check["detail"].get("destination_kind") != custody["destination_kind"]:
        raise HealthBlocked("custody.verified does not name the custody destination")
    identity = receipt["target"].get("identity_sha256")
    if not isinstance(identity, str) or not SHA256_HEX.fullmatch(identity):
        raise HealthBlocked("restore_target_identity_sha256 missing or malformed")
    if identity == custody["destination_identity_sha256"]:
        raise HealthBlocked("restore_target_identity_sha256 equals destination_identity_sha256 (not independent)")
    if offdevice is not None:
        for key in ("bundle_sha256", "bundle_name", "destination_identity_sha256"):
            if offdevice.get(key) != custody[key]:
                raise HealthBlocked(f"restored copy is not the newest re-verified bundle on the destination ({key})")

    # 6. per-store blocks recompute to their verification hashes
    _check_stores(receipt, ir)

    # 7. timestamps, age, RPO/RTO (recomputed and echoed against the repository objectives)
    started = _utc(receipt["started_at"], "started_at")
    restore_started = _utc(receipt["restore_started_at"], "restore_started_at")
    ready = _utc(receipt["ready_at"], "ready_at")
    completed = _utc(receipt["completed_at"], "completed_at")
    backup_created = _utc(inputs.get("backup_created_at"), "inputs.backup_created_at")
    if not started <= restore_started <= ready <= completed or backup_created > restore_started:
        raise HealthBlocked("restore receipt timestamps are out of order")
    if completed > now + timedelta(minutes=1):
        raise HealthBlocked("restore receipt is dated in the future")
    age = now - completed
    if age > max_age:
        raise HealthBlocked(f"restore receipt is {age.days} days old (maximum {max_age.days}); repeat the restore")
    rpo_rto = receipt["rpo_rto"]
    rpo = _seconds(rpo_rto.get("rpo_seconds"), "rpo_rto.rpo_seconds")
    rto = _seconds(rpo_rto.get("rto_seconds"), "rpo_rto.rto_seconds")
    if rpo_rto.get("ready_at") != receipt["ready_at"] or rpo_rto.get("backup_created_at") != inputs["backup_created_at"] \
            or abs(rpo - (ready - backup_created).total_seconds()) > 1 \
            or abs(rto - (ready - restore_started).total_seconds()) > 1:
        raise HealthBlocked("rpo_rto is inconsistent with the receipt timestamps")
    objectives = _load_objectives(objectives_file)
    rpo_gap = round(rpo - objectives["software_rpo_seconds"], 3)
    rto_gap = round(rto - objectives["software_restore_target_seconds"], 3)
    findings = []
    if rpo_gap > 0:
        findings.append(f"RPO objective missed by {rpo_gap} s (rpo {rpo} s > {objectives['software_rpo_seconds']} s);"
                        " reported, not blocking: the owner must accept the gap or change the objective")
    if rto_gap > 0:
        findings.append(f"RTO objective missed by {rto_gap} s (rto {rto} s > "
                        f"{objectives['software_restore_target_seconds']} s); reported, not blocking")
    return {
        "accepted": True,
        "evidence": "RECEIPT_ATTESTED_REVERIFIED_LOCALLY",
        "receipt_sha256": digest,
        "custody_receipt_sha256": custody_sha,
        "bundle_sha256": custody["bundle_sha256"],
        "bound_to_offdevice_readback": offdevice is not None,
        "restore_target_identity_sha256": identity,
        "destination_identity_sha256": custody["destination_identity_sha256"],
        "completed_at": receipt["completed_at"],
        "age_days": round(age.total_seconds() / 86400, 2),
        "max_age_days": max_age.days,
        "rpo_rto": {
            "rpo_seconds": rpo, "rto_seconds": rto, "objectives": objectives,
            "rpo_gap_seconds": rpo_gap, "rto_gap_seconds": rto_gap,
            "rpo_objective_met": rpo_gap <= 0, "rto_objective_met": rto_gap <= 0,
        },
        "findings": findings,
        "not_proven": "physical restore, host isolation and the offline setup are attested by the receipt only; "
                      "this is not production readiness",
    }


def restore_receipt_reverifier(receipt_path: Path | None, custody_path: Path | None,
                               max_age_days: int = DEFAULT_RESTORE_MAX_AGE_DAYS):
    def run(*, now: datetime, offdevice: dict | None) -> dict:
        return verify_restore_receipt(receipt_path, custody_path, now=now, offdevice=offdevice,
                                      max_age=timedelta(days=max_age_days))
    return run


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HealthBlocked("inventory timestamp missing UTC")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HealthBlocked("inventory timestamp malformed") from exc
    if stamp.utcoffset() != timedelta(0):
        raise HealthBlocked("inventory timestamp must be UTC")
    return stamp


def assess(
    inventory: dict | None,
    timer: dict[str, str] | None,
    root_free_bytes: int | None,
    *,
    now: datetime | None = None,
    structural_validator=verify_structural_contract,
    offdevice_verifier=None,
    restore_verifier=None,
) -> dict:
    """Always fail closed for independent site recovery; do not treat claims as proof."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise HealthBlocked("current time lacks timezone")
    gates: dict[str, dict[str, str]] = {}

    def gate(name: str, state: str, reason: str) -> None:
        if state not in STATUS:
            raise HealthBlocked("invalid status")
        gates[name] = {"status": state, "reason": reason}

    if timer is None:
        gate("scheduler", "BLOCKED", "application backup timer evidence unavailable")
    elif set(timer) != PROPERTIES:
        gate("scheduler", "BLOCKED", "incomplete timer metadata")
    elif (timer["LoadState"], timer["UnitFileState"], timer["ActiveState"], timer["Persistent"]) != (
        "loaded", "enabled", "active", "yes"
    ):
        gate("scheduler", "BLOCKED", "required persistent application backup timer not enabled and active")
    else:
        gate("scheduler", "REPORTED_OK", "timer installed, enabled and active; successful backup NOT proven")

    if type(root_free_bytes) is not int or root_free_bytes < 20 * GiB:
        gate("root_headroom", "BLOCKED", "20 GiB protected root free reserve not proven")
    else:
        gate("root_headroom", "REPORTED_OK", "root free reserve observed; staging budget separately required")

    if inventory is None:
        gate("multi_store_inventory", "BLOCKED", "complete eight-store v2 receipt unavailable")
        gate("backup_freshness", "BLOCKED", "last complete encrypted capture unverified")
    else:
        try:
            structural_validator(inventory)
            assets = inventory.get("assets")
            if not isinstance(assets, list):
                raise HealthBlocked("asset receipt list missing")
            names = [asset.get("id") for asset in assets if isinstance(asset, dict)]
            if len(names) != len(EXPECTED) or set(names) != EXPECTED:
                raise HealthBlocked("partial or duplicate eight-store evidence")
            gate("multi_store_inventory", "UNVERIFIED", "v2 receipt structurally valid; real contents and custody not independently checked")
            observed_at = parse_utc(inventory.get("observed_at"))
            if observed_at > now + timedelta(minutes=1) or now - observed_at > timedelta(hours=26):
                gate("backup_freshness", "BLOCKED", "receipt stale or future dated; actual schedule success unknown")
            else:
                gate("backup_freshness", "UNVERIFIED", "recent attestation only; no independently inspected backup job")
        except (HealthBlocked, ValueError, TypeError, KeyError):
            gate("multi_store_inventory", "BLOCKED", "complete v2 protected receipt invalid or partial")
            gate("backup_freshness", "BLOCKED", "valid complete backup capture time not established")

    copy: dict | None = None
    if offdevice_verifier is None:
        gate("encrypted_off_device_copy", "UNVERIFIED", "claim cannot prove independent off-device encrypted custody")
    else:
        try:
            copy = offdevice_verifier()
            if not isinstance(copy, dict) or copy.get("status") != "READBACK_REVERIFIED":
                raise HealthBlocked("off-device re-verification returned no evidence")
            gate("encrypted_off_device_copy", "REPORTED_OK",
                 f"newest bundle re-read on the enrolled independent {copy.get('destination_kind')} matches its "
                 "custody receipt; key custody, offline proof and restore are NOT proven by this probe")
        except Exception:  # any failure keeps the gate closed
            copy = None
            gate("encrypted_off_device_copy", "BLOCKED", "supplied off-device destination did not re-verify")

    # #1632: only a locally re-verified site-mode receipt can open this gate; a claim never does.
    restore_evidence: dict | None = None
    if restore_verifier is None:
        gate("isolated_restore", "UNVERIFIED", "claim cannot prove actual fresh-volume isolated restore")
    elif offdevice_verifier is not None and copy is None:
        gate("isolated_restore", "BLOCKED",
             "off-device destination supplied but not re-verified; the restored copy cannot be bound to it")
    else:
        try:
            restore_evidence = restore_verifier(now=now, offdevice=copy)
            if not isinstance(restore_evidence, dict) or restore_evidence.get("accepted") is not True:
                raise HealthBlocked("restore receipt verification returned no evidence")
            gate("isolated_restore", "REPORTED_OK",
                 "site-mode isolated restore receipt re-verified locally (sidecar, schema, all checks PASS, custody "
                 "binding, age); receipt-attested only, NOT an independent proof of the physical restore")
        except HealthBlocked as exc:
            restore_evidence = None
            gate("isolated_restore", "BLOCKED", f"restore receipt rejected: {exc}")
        except Exception as exc:  # any unexpected failure keeps the gate closed
            restore_evidence = None
            gate("isolated_restore", "BLOCKED", f"restore receipt could not be verified ({type(exc).__name__})")
    gate("hardware_acceptance", "UNVERIFIED", "no real equipment evidence")
    report = {
        "status": "BLOCKED",
        "profile": "LOCAL_LAN",
        "probe": "READ_ONLY_OFFLINE",
        "gates": gates,
        "production_backup": "NOT_PERFORMED_BY_PROBE",
        "site_activation": "NOT_AUTHORIZED",
        "next_action": "independently verify all protected stores, encrypted off-device copy, isolated restore and authorized scheduler",
    }
    if restore_verifier is not None:
        report["isolated_restore_receipt"] = restore_evidence or {
            "accepted": False, "reason": gates["isolated_restore"]["reason"]}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, help="optional mode-0600 sanitized v2 DR receipt")
    parser.add_argument("--offdevice-destination", type=Path,
                        help="optional mounted #1631 destination; its newest bundle is re-read (read-only)")
    parser.add_argument("--restore-receipt", type=Path,
                        help="optional #1632 site-mode isolated restore receipt (its .sha256 sidecar must sit next to it)")
    parser.add_argument("--custody-receipt", type=Path,
                        help="#1631 custody receipt of the restored bundle (required with --restore-receipt)")
    parser.add_argument("--restore-receipt-max-age-days", type=int, default=DEFAULT_RESTORE_MAX_AGE_DAYS,
                        choices=range(1, 367), metavar="1..366",
                        help=f"maximum restore receipt age in days (default {DEFAULT_RESTORE_MAX_AGE_DAYS})")
    args = parser.parse_args()
    sys.dont_write_bytecode = True  # read-only probe: loading sibling scripts must not write __pycache__
    inventory: dict | None = None
    timer: dict[str, str] | None = None
    try:
        if args.inventory is not None:
            inventory = read_sanitized_receipt(args.inventory)
    except HealthBlocked:
        pass
    try:
        timer = read_timer()
    except HealthBlocked:
        pass
    try:
        free = shutil.disk_usage("/").free
    except OSError:
        free = None
    verifier = offdevice_reverifier(args.offdevice_destination) if args.offdevice_destination else None
    restore = None
    if args.restore_receipt is not None or args.custody_receipt is not None:
        restore = restore_receipt_reverifier(args.restore_receipt, args.custody_receipt,
                                             args.restore_receipt_max_age_days)
    print(json.dumps(assess(inventory, timer, free, offdevice_verifier=verifier, restore_verifier=restore),
                     sort_keys=True))
    return 78  # No in-chat structural evidence authorizes a real site restore.


if __name__ == "__main__":
    raise SystemExit(main())
