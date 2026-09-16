#!/usr/bin/env python3
"""Adopt a verified live compatibility runtime as deployment recovery authority.

This bridge exists for a runtime that was promoted through a bounded compatibility
release rather than the generic source deployment pipeline. It is intentionally
read-only with respect to running services and product data. Execute mode writes
only sanitized, ignored authority evidence under runtime/deployments/.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import uuid4
import urllib.request

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
STAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")
EXPECTED_REPOSITORY = "eNgine9r/nexolab-platform"
RESULT_NAME = "compatibility-runtime-authority.json"
SUMMARY_NAME = "summary.txt"
DEVICE_AGENT_URL = "http://127.0.0.1:8081/health"


class AuthorityFailure(RuntimeError):
    pass


def run(*command: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorityFailure(f"command failed safely: {' '.join(command)}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise AuthorityFailure(f"command failed safely: {' '.join(command)}: {detail}")
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run("git", "-C", str(repo), *args)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise AuthorityFailure(f"{label} is missing or unsafe: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    safe_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityFailure(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise AuthorityFailure(f"{label} must be a JSON object")
    return value


def parse_key_values(path: Path, label: str) -> dict[str, str]:
    safe_file(path, label)
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def normalized_repository(remote: str) -> str | None:
    value = remote.strip().removesuffix(".git")
    for prefix in ("git@github.com:", "ssh://git@github.com/", "https://github.com/"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def valid_stamp(name: str) -> bool:
    if not STAMP_RE.fullmatch(name):
        return False
    try:
        datetime.strptime(name, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def latest_formal_success(repo: Path, *, before_stamp: str | None = None) -> tuple[Path, str, str | None]:
    root = repo / "runtime" / "deployments"
    rows: list[tuple[str, Path, str, str | None]] = []
    if not root.is_dir():
        raise AuthorityFailure("deployment evidence root is unavailable")
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not valid_stamp(directory.name):
            continue
        if before_stamp is not None and directory.name >= before_stamp:
            continue
        summary = directory / SUMMARY_NAME
        final_state = directory / "final-state.txt"
        if not summary.is_file() or not final_state.is_file():
            continue
        if "DEPLOYMENT PASSED" not in summary.read_text(encoding="utf-8", errors="replace"):
            continue
        facts = parse_key_values(final_state, "formal deployment final state")
        source = facts.get("commit", "")
        image = facts.get("deployed_device_agent_image_id")
        if SHA_RE.fullmatch(source):
            if image is not None and not IMAGE_RE.fullmatch(image):
                raise AuthorityFailure(f"formal deployment Device Agent image is invalid: {directory}")
            rows.append((directory.name, directory, source, image))
    if not rows:
        raise AuthorityFailure("no formal successful deployment authority is available")
    _stamp, directory, source, image = max(rows, key=lambda row: row[0])
    return directory, source, image


def verify_checksum_manifest(directory: Path) -> None:
    manifest = safe_file(directory / "SHA256SUMS", "acceptance checksum manifest")
    seen = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise AuthorityFailure("acceptance checksum manifest contains an invalid row")
        expected, recorded_path = match.groups()
        candidate = Path(recorded_path)
        if not candidate.is_absolute():
            candidate = directory / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise AuthorityFailure(f"acceptance checksum target is unavailable: {recorded_path}") from exc
        if resolved.parent != directory.resolve() or candidate.is_symlink() or not resolved.is_file():
            raise AuthorityFailure("acceptance checksum target escapes the evidence directory")
        if sha256_file(resolved) != expected:
            raise AuthorityFailure(f"acceptance checksum mismatch: {resolved.name}")
        seen += 1
    if seen < 2:
        raise AuthorityFailure("acceptance checksum manifest is unexpectedly small")


def resolve_evidence_dir(repo: Path, value: Path, root_name: str) -> Path:
    root = (repo / "runtime" / root_name).resolve()
    resolved = value.resolve()
    if resolved.parent != root or value.is_symlink() or not resolved.is_dir():
        raise AuthorityFailure(f"evidence must be a direct directory under runtime/{root_name}")
    return resolved


def http_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - loopback constant only
            payload = json.load(response)
    except Exception as exc:  # bounded local operational probe
        raise AuthorityFailure(f"local health endpoint is unavailable: {url}") from exc
    if not isinstance(payload, dict):
        raise AuthorityFailure(f"local health endpoint returned a non-object: {url}")
    return payload


def unique_container(project: str, service: str) -> str:
    output = run(
        "docker", "ps", "-q",
        "--filter", f"label=com.docker.compose.project={project}",
        "--filter", f"label=com.docker.compose.service={service}",
    )
    rows = [row for row in output.splitlines() if row]
    if len(rows) != 1:
        raise AuthorityFailure(f"expected exactly one running {project}/{service} container")
    return run("docker", "inspect", "--format", "{{.Id}}", rows[0])


def container_image(container_id: str) -> str:
    image = run("docker", "inspect", "--format", "{{.Image}}", container_id)
    if not IMAGE_RE.fullmatch(image):
        raise AuthorityFailure("container image identity is invalid")
    run("docker", "image", "inspect", image)
    return image


def published_http_url(container_id: str, internal_port: int, path: str) -> str:
    raw = run("docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", container_id)
    try:
        ports = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthorityFailure("container published-port metadata is invalid") from exc
    bindings = ports.get(f"{internal_port}/tcp") if isinstance(ports, dict) else None
    if not isinstance(bindings, list) or len(bindings) != 1 or not isinstance(bindings[0], dict):
        raise AuthorityFailure(f"expected exactly one published TCP binding for port {internal_port}")
    host = bindings[0].get("HostIp")
    port = bindings[0].get("HostPort")
    if not isinstance(host, str) or not isinstance(port, str) or not port.isdigit():
        raise AuthorityFailure("container published-port binding is incomplete")
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    suffix = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{suffix}"


def dashboard_working_directory() -> Path:
    value = run("systemctl", "show", "nexolab-dashboard.service", "-p", "WorkingDirectory", "--value")
    if not value:
        raise AuthorityFailure("dashboard WorkingDirectory is unavailable")
    path = Path(value)
    if not path.is_dir():
        raise AuthorityFailure("dashboard release directory is unavailable")
    return path.resolve()


def build_context(
    repo: Path,
    acceptance_dir: Path,
    rollback_dir: Path,
    compatibility_source: str,
    formal_base_source: str,
) -> dict[str, Any]:
    repo = repo.resolve()
    if normalized_repository(git(repo, "remote", "get-url", "origin")) != EXPECTED_REPOSITORY:
        raise AuthorityFailure("configured origin is not the canonical NEXOLAB repository")
    if not SHA_RE.fullmatch(compatibility_source) or not SHA_RE.fullmatch(formal_base_source):
        raise AuthorityFailure("source identities must be full lowercase commit SHAs")
    git(repo, "cat-file", "-e", f"{compatibility_source}^{{commit}}")
    git(repo, "cat-file", "-e", f"{formal_base_source}^{{commit}}")
    parents = git(repo, "show", "-s", "--format=%P", compatibility_source).split()
    if parents != [formal_base_source]:
        raise AuthorityFailure("compatibility source must have the formal deployed source as its sole parent")

    acceptance_dir = resolve_evidence_dir(repo, acceptance_dir, "evidence")
    rollback_dir = resolve_evidence_dir(repo, rollback_dir, "evidence")
    verify_checksum_manifest(acceptance_dir)
    acceptance = read_json(acceptance_dir / "acceptance.json", "compatibility acceptance")
    if acceptance.get("schema_version") != 1:
        raise AuthorityFailure("compatibility acceptance schema is unsupported")
    if acceptance.get("compatibility_source") != compatibility_source:
        raise AuthorityFailure("compatibility acceptance source mismatch")
    if acceptance.get("base_deployed_source") != formal_base_source:
        raise AuthorityFailure("compatibility acceptance formal base mismatch")
    invariants = acceptance.get("invariants")
    if not isinstance(invariants, dict) or invariants.get("modbus_writes") != "none" or invariants.get("hardware_writes") != "none":
        raise AuthorityFailure("compatibility acceptance safety invariants are incomplete")
    if invariants.get("production_akcc25_polling") != "disabled":
        raise AuthorityFailure("compatibility acceptance does not prove AK-CC25 polling disabled")

    formal_dir, formal_source, formal_image = latest_formal_success(repo)
    if formal_source != formal_base_source:
        raise AuthorityFailure("requested formal base is not the latest formal successful deployment")

    rollback = parse_key_values(rollback_dir / "rollback-authority.txt", "pre-cutover rollback authority")
    if rollback.get("approved_from") != compatibility_source:
        raise AuthorityFailure("rollback evidence does not match compatibility source")
    approved_target_source = rollback.get("approved_to", "")
    if not SHA_RE.fullmatch(approved_target_source):
        raise AuthorityFailure("rollback evidence has no valid approved target source")
    git(repo, "cat-file", "-e", f"{approved_target_source}^{{commit}}")
    try:
        run("git", "-C", str(repo), "merge-base", "--is-ancestor", formal_base_source, approved_target_source)
    except AuthorityFailure as exc:
        raise AuthorityFailure("approved target is not a descendant of the formal base source") from exc
    device_acceptance = acceptance.get("device_agent") if isinstance(acceptance.get("device_agent"), dict) else {}
    telemetry_acceptance = acceptance.get("telemetry_service") if isinstance(acceptance.get("telemetry_service"), dict) else {}
    frontend_acceptance = acceptance.get("frontend") if isinstance(acceptance.get("frontend"), dict) else {}
    expected_da_image = str(device_acceptance.get("candidate_image", ""))
    expected_telemetry_image = str(telemetry_acceptance.get("candidate_image", ""))
    if rollback.get("device_agent_image") != expected_da_image or rollback.get("telemetry_image") != expected_telemetry_image:
        raise AuthorityFailure("rollback image evidence does not match accepted compatibility runtime")
    if not IMAGE_RE.fullmatch(expected_da_image) or not IMAGE_RE.fullmatch(expected_telemetry_image):
        raise AuthorityFailure("accepted compatibility image identity is invalid")

    da_container = unique_container("nexolab-edge", "device-agent")
    telemetry_container = unique_container("nexolab-central", "telemetry-service")
    da_image = container_image(da_container)
    telemetry_image = container_image(telemetry_container)
    if da_image != expected_da_image or telemetry_image != expected_telemetry_image:
        raise AuthorityFailure("live container image does not match accepted compatibility runtime")

    device_url = published_http_url(da_container, 8081, "/health")
    telemetry_url = published_http_url(telemetry_container, 8082, "/health/ready")
    health = http_json(device_url)
    if health.get("status") != "ok" or health.get("mqtt_connected") is not True or health.get("queue_depth") != 0:
        raise AuthorityFailure("Device Agent health is not safe for authority adoption")
    acquisition = health.get("acquisition") if isinstance(health.get("acquisition"), dict) else {}
    configured_targets = health.get("configured_logical_targets", acquisition.get("configured_logical_targets"))
    if configured_targets != 53:
        raise AuthorityFailure("Device Agent target count is not the accepted 53-target baseline")
    scheduler = acquisition.get("scheduler") if isinstance(acquisition.get("scheduler"), dict) else {}
    expected_workers = scheduler.get("expected_bus_workers")
    active_workers = scheduler.get("active_bus_workers")
    workers_healthy = scheduler.get("workers_healthy")
    if expected_workers is not None and (active_workers != expected_workers or workers_healthy is not True):
        raise AuthorityFailure("Device Agent bus workers are not all healthy")

    telemetry_health = http_json(telemetry_url)
    if telemetry_health.get("status") not in {"ready", "ok"}:
        raise AuthorityFailure("Telemetry Service is not ready")

    release = dashboard_working_directory()
    accepted_release = Path(str(frontend_acceptance.get("active_release", ""))).resolve()
    if release != accepted_release or rollback.get("frontend_release") != str(accepted_release):
        raise AuthorityFailure("live Dashboard release does not match compatibility acceptance")
    build_id_path = safe_file(release / ".next" / "BUILD_ID", "Dashboard BUILD_ID")
    build_id = build_id_path.read_text(encoding="utf-8").strip()
    if build_id != frontend_acceptance.get("build_id") or rollback.get("frontend_build_id") != build_id:
        raise AuthorityFailure("Dashboard BUILD_ID does not match compatibility acceptance")

    if formal_image is None:
        raise AuthorityFailure("formal base has no Device Agent recovery image authority")

    return {
        "repo": repo,
        "acceptance_dir": acceptance_dir,
        "rollback_dir": rollback_dir,
        "formal_dir": formal_dir,
        "compatibility_source": compatibility_source,
        "formal_base_source": formal_base_source,
        "approved_target_source": approved_target_source,
        "formal_base_device_agent_image_id": formal_image,
        "device_agent_container_id": da_container,
        "device_agent_image_id": da_image,
        "telemetry_container_id": telemetry_container,
        "telemetry_image_id": telemetry_image,
        "dashboard_release_dir": str(release),
        "dashboard_build_id": build_id,
        "acceptance_json_sha256": sha256_file(acceptance_dir / "acceptance.json"),
        "acceptance_checksums_sha256": sha256_file(acceptance_dir / "SHA256SUMS"),
        "rollback_authority_sha256": sha256_file(rollback_dir / "rollback-authority.txt"),
        "formal_summary_sha256": sha256_file(formal_dir / "summary.txt"),
        "formal_final_state_sha256": sha256_file(formal_dir / "final-state.txt"),
        "device_health": {
            "status": health.get("status"),
            "mqtt_connected": health.get("mqtt_connected"),
            "queue_depth": health.get("queue_depth"),
            "configured_logical_targets": configured_targets,
        },
        "telemetry_status": telemetry_health.get("status"),
    }


def relative_to_repo(repo: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError as exc:
        raise AuthorityFailure(f"evidence path is outside repository runtime: {path}") from exc


def make_result(context: dict[str, Any], stamp: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "nexolab-compatibility-runtime-authority",
        "status": "established",
        "authority_id": stamp,
        "created_at": datetime.now(UTC).isoformat(),
        "compatibility_source": context["compatibility_source"],
        "formal_base_source": context["formal_base_source"],
        "approved_target_source": context["approved_target_source"],
        "formal_base_evidence": relative_to_repo(context["repo"], context["formal_dir"]),
        "formal_base_device_agent_image_id": context["formal_base_device_agent_image_id"],
        "acceptance_evidence": relative_to_repo(context["repo"], context["acceptance_dir"]),
        "rollback_evidence": relative_to_repo(context["repo"], context["rollback_dir"]),
        "device_agent_container_id": context["device_agent_container_id"],
        "device_agent_image_id": context["device_agent_image_id"],
        "telemetry_container_id": context["telemetry_container_id"],
        "telemetry_image_id": context["telemetry_image_id"],
        "dashboard_release_dir": context["dashboard_release_dir"],
        "dashboard_build_id": context["dashboard_build_id"],
        "device_health": context["device_health"],
        "telemetry_status": context["telemetry_status"],
        "evidence_hashes": {
            "acceptance_json": context["acceptance_json_sha256"],
            "acceptance_checksums": context["acceptance_checksums_sha256"],
            "rollback_authority": context["rollback_authority_sha256"],
            "formal_summary": context["formal_summary_sha256"],
            "formal_final_state": context["formal_final_state_sha256"],
        },
        "safety": {
            "runtime_mutation": "none",
            "service_restart": "none",
            "modbus_write": "none",
            "hardware_write": "none",
            "product_data_deletion": "none",
            "named_volume_deletion": "none",
        },
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def validate_result(repo: Path, directory: Path, document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schema_version") != 1 or document.get("kind") != "nexolab-compatibility-runtime-authority" or document.get("status") != "established":
        raise AuthorityFailure("compatibility runtime authority contract is invalid")
    if document.get("authority_id") != directory.name:
        raise AuthorityFailure("compatibility runtime authority id mismatch")
    source = document.get("compatibility_source")
    base = document.get("formal_base_source")
    image = document.get("device_agent_image_id")
    approved_target = document.get("approved_target_source")
    if not isinstance(source, str) or not SHA_RE.fullmatch(source) or not isinstance(base, str) or not SHA_RE.fullmatch(base):
        raise AuthorityFailure("compatibility runtime authority source identity is invalid")
    if not isinstance(image, str) or not IMAGE_RE.fullmatch(image):
        raise AuthorityFailure("compatibility runtime authority Device Agent image is invalid")
    parents = git(repo, "show", "-s", "--format=%P", source).split()
    if parents != [base]:
        raise AuthorityFailure("published compatibility source lineage is invalid")

    acceptance_dir = (repo / str(document.get("acceptance_evidence", ""))).resolve()
    rollback_dir = (repo / str(document.get("rollback_evidence", ""))).resolve()
    formal_dir = (repo / str(document.get("formal_base_evidence", ""))).resolve()
    if acceptance_dir.parent != (repo / "runtime" / "evidence").resolve() or rollback_dir.parent != (repo / "runtime" / "evidence").resolve():
        raise AuthorityFailure("published compatibility evidence path is outside runtime/evidence")
    if formal_dir.parent != (repo / "runtime" / "deployments").resolve() or not valid_stamp(formal_dir.name):
        raise AuthorityFailure("published formal deployment evidence path is invalid")
    acceptance = read_json(acceptance_dir / "acceptance.json", "published compatibility acceptance")
    if acceptance.get("compatibility_source") != source or acceptance.get("base_deployed_source") != base:
        raise AuthorityFailure("published compatibility acceptance lineage mismatch")
    verify_checksum_manifest(acceptance_dir)
    rollback = parse_key_values(rollback_dir / "rollback-authority.txt", "published rollback authority")
    rollback_target = rollback.get("approved_to", "")
    if not SHA_RE.fullmatch(rollback_target):
        raise AuthorityFailure("published rollback authority has no valid approved target")
    if approved_target is None:
        approved_target = rollback_target
    elif not isinstance(approved_target, str) or not SHA_RE.fullmatch(approved_target):
        raise AuthorityFailure("compatibility runtime authority approved target is invalid")
    elif approved_target != rollback_target:
        raise AuthorityFailure("published rollback authority approved target mismatch")
    git(repo, "cat-file", "-e", f"{approved_target}^{{commit}}")
    try:
        run("git", "-C", str(repo), "merge-base", "--is-ancestor", base, approved_target)
    except AuthorityFailure as exc:
        raise AuthorityFailure("published approved target is not a descendant of the formal base source") from exc
    if rollback.get("approved_from") != source or rollback.get("device_agent_image") != image:
        raise AuthorityFailure("published rollback authority mismatch")

    formal_facts = parse_key_values(formal_dir / "final-state.txt", "published formal deployment final state")
    if formal_facts.get("commit") != base or "DEPLOYMENT PASSED" not in safe_file(formal_dir / "summary.txt", "published formal deployment summary").read_text(encoding="utf-8", errors="replace"):
        raise AuthorityFailure("published formal deployment authority mismatch")
    hashes = document.get("evidence_hashes")
    expected_hashes = {
        "acceptance_json": sha256_file(acceptance_dir / "acceptance.json"),
        "acceptance_checksums": sha256_file(acceptance_dir / "SHA256SUMS"),
        "rollback_authority": sha256_file(rollback_dir / "rollback-authority.txt"),
        "formal_summary": sha256_file(formal_dir / "summary.txt"),
        "formal_final_state": sha256_file(formal_dir / "final-state.txt"),
    }
    if hashes != expected_hashes:
        raise AuthorityFailure("published compatibility runtime authority evidence hash mismatch")
    safety = document.get("safety")
    if not isinstance(safety, dict) or any(safety.get(key) != "none" for key in ("runtime_mutation", "service_restart", "modbus_write", "hardware_write", "product_data_deletion", "named_volume_deletion")):
        raise AuthorityFailure("published compatibility runtime authority safety contract is invalid")
    validated = dict(document)
    validated["approved_target_source"] = approved_target
    return validated


def load_published_authority(repo: Path, directory: Path) -> dict[str, Any]:
    repo = repo.resolve()
    root = (repo / "runtime" / "deployments").resolve()
    resolved = directory.resolve()
    if resolved.parent != root or directory.is_symlink() or not valid_stamp(resolved.name):
        raise AuthorityFailure("compatibility runtime authority directory is unsafe")
    return validate_result(repo, resolved, read_json(resolved / RESULT_NAME, "compatibility runtime authority"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--rollback-evidence", type=Path, required=True)
    parser.add_argument("--expected-compatibility-source", required=True)
    parser.add_argument("--expected-formal-base-source", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    try:
        context = build_context(
            repo,
            args.acceptance_evidence,
            args.rollback_evidence,
            args.expected_compatibility_source,
            args.expected_formal_base_source,
        )
        if args.check_only:
            print("COMPATIBILITY_RUNTIME_AUTHORITY_PREFLIGHT_OK")
            print(json.dumps({
                "compatibility_source": context["compatibility_source"],
                "formal_base_source": context["formal_base_source"],
                "device_agent_image_id": context["device_agent_image_id"],
                "telemetry_image_id": context["telemetry_image_id"],
                "dashboard_release_dir": context["dashboard_release_dir"],
                "dashboard_build_id": context["dashboard_build_id"],
            }, sort_keys=True))
            return 0
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        directory = repo / "runtime" / "deployments" / stamp
        if directory.exists():
            raise AuthorityFailure(f"authority evidence directory already exists: {directory}")
        directory.mkdir(parents=True, mode=0o700)
        result = make_result(context, stamp)
        atomic_json(directory / RESULT_NAME, result)
        summary = (
            f"[{datetime.now().astimezone().isoformat()}] COMPATIBILITY RUNTIME AUTHORITY ADOPTED\n"
            f"compatibility_source={context['compatibility_source']}\n"
            f"formal_base_source={context['formal_base_source']}\n"
            "runtime_mutation=none\nservice_restart=none\nmodbus_write=none\nhardware_write=none\n"
        )
        (directory / SUMMARY_NAME).write_text(summary, encoding="utf-8")
        os.chmod(directory / SUMMARY_NAME, 0o600)
        validate_result(repo, directory, result)
        print("COMPATIBILITY_RUNTIME_AUTHORITY_ESTABLISHED")
        print(f"evidence={directory}")
        print(f"source={context['compatibility_source']}")
        return 0
    except AuthorityFailure as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
