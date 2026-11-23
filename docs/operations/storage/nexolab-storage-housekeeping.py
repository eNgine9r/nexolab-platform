#!/usr/bin/env python3
"""NEXOLAB storage housekeeping and disk guard (#1710, #1551).

Owner-installed to /usr/local/lib/nexolab-storage/ and run as root by
nexolab-storage-housekeeping.service (weekly, report only) and
nexolab-storage-guard.service (every 15 minutes, ``--guard-only``).

Report (default) plans and writes a manifest; nothing is changed. Apply runs
only with ``--apply-manifest PATH --manifest-sha256 HEX``: the manifest must
match the hash exactly, every entry is planned again, and only entries that
are still eligible are executed. There is no unattended apply.

Candidates (reproducible artifacts only):
- APT downloaded packages (``apt-get clean``), never while apt/dpkg runs;
- Docker build cache older than 7 days;
- dangling images older than 7 days;
- frontend release directories named ``<40-hex>-<YYYYMMDDTHHMMSSZ>`` directly
  under a configured release root, outside the newest ``keep_releases`` and
  older than ``min_release_age_days``.

Fail closed: image and release candidates are dropped entirely when a protected
inventory file is missing or unreadable, when Docker containers cannot be
listed or inspected, or when a reference root cannot be read. A release or
image is never a candidate when it is protected, used by a container (image or
bind mount), referenced by a systemd unit, used by a running process, or named
in any recovery/deployment/rollback/offline-bundle record under the reference
roots; those are reported as REVIEW with the reason.

Never touched: Docker volumes, containers, tagged images, PostgreSQL, SQLite,
deployment evidence, backups, offline bundles, Commander workspaces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

RELEASE_NAME = re.compile(r"^(?P<sha>[0-9a-f]{40})-(?P<stamp>\d{8}T\d{6}Z)$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
UNIT_DIRS = ("/etc/systemd/system", "/run/systemd/system", "/lib/systemd/system")
REFERENCE_SUFFIXES = {".json", ".txt", ".env", ".conf", ".yaml", ".yml", ".sha256", ".manifest", ".log", ".md", ".sh", ".service"}
REFERENCE_MAX_BYTES = 8 * 1024 * 1024
GIB = 1024**3


class FailClosed(Exception):
    """A safety input is unavailable; image and release candidates are withheld."""


@dataclass
class Config:
    release_roots: tuple[str, ...] = ()
    reference_roots: tuple[str, ...] = ()
    keep_releases: int = 3
    min_release_age_days: int = 14
    min_image_age_days: int = 7
    build_cache_age_hours: int = 168
    warn_gib: float = 40.0
    critical_gib: float = 20.0
    protected_paths: tuple[str, ...] = ()
    protected_images: tuple[str, ...] = ()
    protected_inventories_ok: bool = True
    protected_inventory_error: str | None = None
    unit_dirs: tuple[str, ...] = UNIT_DIRS
    user_unit_globs: tuple[str, ...] = ("/home/*/.config/systemd/user",)
    status_dir: str = "/var/lib/nexolab-storage"
    filesystem: str = "/"


@dataclass
class Action:
    kind: str
    target: str
    reason: str
    bytes: int = 0
    command: list[str] = field(default_factory=list)
    applied: bool = False
    error: str | None = None


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)


def _required_lines(path: str | None, label: str) -> tuple[str, ...]:
    if not path:
        raise FailClosed(f"{label} inventory is not configured")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise FailClosed(f"{label} inventory unreadable: {error.__class__.__name__}") from error
    values = tuple(line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))
    if not values:
        raise FailClosed(f"{label} inventory is empty")
    return values


def read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def config_from_env(environ: dict[str, str] | os._Environ[str] = os.environ) -> Config:
    config = Config(
        release_roots=tuple(r for r in environ.get("STORAGE_RELEASE_ROOTS", "").split(":") if r),
        reference_roots=tuple(r for r in environ.get("STORAGE_REFERENCE_ROOTS", "").split(":") if r),
        keep_releases=max(2, int(environ.get("STORAGE_KEEP_RELEASES", "3"))),
        min_release_age_days=max(1, int(environ.get("STORAGE_MIN_RELEASE_AGE_DAYS", "14"))),
        min_image_age_days=max(1, int(environ.get("STORAGE_MIN_IMAGE_AGE_DAYS", "7"))),
        build_cache_age_hours=max(24, int(environ.get("STORAGE_BUILD_CACHE_AGE_HOURS", "168"))),
        warn_gib=float(environ.get("STORAGE_WARN_GIB", "40")),
        critical_gib=float(environ.get("STORAGE_CRITICAL_GIB", "20")),
        status_dir=environ.get("STATE_DIRECTORY", "/var/lib/nexolab-storage").split(":")[0],
    )
    try:
        config.protected_images = _required_lines(environ.get("STORAGE_PROTECTED_IMAGES_FILE"), "protected-images")
        config.protected_paths = _required_lines(environ.get("STORAGE_PROTECTED_PATHS_FILE"), "protected-paths")
    except FailClosed as error:
        config.protected_inventories_ok = False
        config.protected_inventory_error = str(error)
    return config


def disk_state(config: Config) -> dict[str, object]:
    usage = shutil.disk_usage(config.filesystem)
    free_gib = usage.free / GIB
    level = "critical" if free_gib < config.critical_gib else "warning" if free_gib < config.warn_gib else "ok"
    return {
        "filesystem": config.filesystem,
        "free_gib": round(free_gib, 2),
        "total_gib": round(usage.total / GIB, 2),
        "warn_gib": config.warn_gib,
        "critical_gib": config.critical_gib,
        "level": level,
    }


def _dir_bytes(path: Path) -> int:
    total = 0
    device = path.lstat().st_dev
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [
            d for d in dirs
            if not os.path.islink(os.path.join(root, d)) and os.lstat(os.path.join(root, d)).st_dev == device
        ]
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


def _unit_text(config: Config) -> str:
    chunks: list[str] = []
    directories = [Path(d) for d in config.unit_dirs]
    for pattern in config.user_unit_globs:
        directories.extend(Path("/").glob(pattern.lstrip("/")))
    for directory in directories:
        if not directory.is_dir():
            continue
        for unit in directory.rglob("*"):
            if unit.is_file() and unit.suffix in {".service", ".conf", ".socket", ".timer", ".mount", ".path"}:
                try:
                    chunks.append(unit.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
    return "\n".join(chunks)


def _process_paths() -> set[str]:
    paths: set[str] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        for link in ("cwd", "exe"):
            try:
                paths.add(os.readlink(entry / link))
            except OSError:
                pass
    return paths


def reference_index(config: Config, needles: Iterable[str]) -> dict[str, list[str]]:
    """Map each needle to the record files (under reference roots) that mention it."""
    wanted = {needle for needle in needles if needle}
    hits: dict[str, list[str]] = {needle: [] for needle in wanted}
    if not wanted:
        return hits
    skip = {str(Path(root).resolve()) for root in config.release_roots}
    for root_text in config.reference_roots:
        root = Path(root_text)
        if not root.exists():
            continue
        if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
            raise FailClosed(f"reference root unreadable: {root_text}")
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if str(Path(directory, d).resolve()) not in skip and d not in {"node_modules", ".next", ".git"}]
            for name in files:
                path = Path(directory, name)
                if path.suffix.lower() not in REFERENCE_SUFFIXES:
                    continue
                try:
                    if path.is_symlink() or path.stat().st_size > REFERENCE_MAX_BYTES:
                        continue
                    data = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for needle in wanted:
                    if needle in data:
                        hits[needle].append(str(path))
    return hits


def docker_usage(run: Runner) -> tuple[set[str], set[str]]:
    """Images used by any container and every container bind-mount source. Fails closed."""
    listed = run(["docker", "ps", "-aq", "--no-trunc"])
    if listed.returncode != 0:
        raise FailClosed("docker ps failed")
    ids = listed.stdout.split()
    images: set[str] = set()
    mounts: set[str] = set()
    if ids:
        inspected = run(["docker", "inspect", "--format", "{{.Image}}|{{range .Mounts}}{{.Source}};{{end}}", *ids])
        if inspected.returncode != 0:
            raise FailClosed("docker inspect of containers failed")
        lines = [line for line in inspected.stdout.splitlines() if line.strip()]
        if len(lines) != len(ids):
            raise FailClosed("docker inspect returned an incomplete container list")
        for line in lines:
            image, _, sources = line.partition("|")
            images.add(image.strip())
            mounts.update(source for source in sources.split(";") if source)
    return images, mounts


def _inside(path: str, others: Iterable[str]) -> bool:
    """True when ``path`` itself or something inside it appears in ``others``."""
    path = path.rstrip("/")
    return any(o.rstrip("/") == path or o.startswith(path + "/") for o in others if o and o != "/")


def _related(path: str, others: Iterable[str]) -> bool:
    """``_inside`` or ``path`` lies under one of ``others`` (never under "/" alone)."""
    path = path.rstrip("/")
    for other in others:
        other = other.rstrip("/")
        if not other:
            continue
        if other == path or other.startswith(path + "/") or path.startswith(other + "/"):
            return True
    return False


def plan_releases(
    config: Config,
    *,
    now: float | None = None,
    unit_text: str | None = None,
    process_paths: set[str] | None = None,
    mount_sources: set[str] | None = None,
    references: dict[str, list[str]] | None = None,
) -> tuple[list[Action], list[dict[str, str]]]:
    now = time.time() if now is None else now
    unit_text = _unit_text(config) if unit_text is None else unit_text
    process_paths = _process_paths() if process_paths is None else process_paths
    mount_sources = set() if mount_sources is None else mount_sources
    actions: list[Action] = []
    kept: list[dict[str, str]] = []
    candidates: list[tuple[Path, int]] = []
    for root_text in config.release_roots:
        root = Path(root_text)
        if not root.is_dir() or root.is_symlink():
            kept.append({"target": root_text, "reason": "release root missing or symlink; skipped"})
            continue
        releases = sorted(
            (child for child in root.iterdir() if RELEASE_NAME.match(child.name)),
            key=lambda child: RELEASE_NAME.match(child.name).group("stamp"),  # type: ignore[union-attr]
            reverse=True,
        )
        candidates.extend((release, index) for index, release in enumerate(releases))
    if references is None:
        references = reference_index(config, (release.name for release, _ in candidates))
    for release, index in candidates:
        resolved = str(release)
        reason = None
        if release.is_symlink() or not release.is_dir():
            reason = "symlink or not a directory"
        elif index < config.keep_releases:
            reason = f"among the newest {config.keep_releases}"
        elif _related(resolved, config.protected_paths):
            reason = "listed as protected"
        elif resolved in unit_text or release.name in unit_text:
            reason = "referenced by a systemd unit"
        elif _inside(resolved, process_paths):
            reason = "in use by a running process"
        elif _inside(resolved, mount_sources):
            reason = "bind-mounted into a container"
        elif references.get(release.name):
            files = references[release.name]
            reason = f"referenced by {len(files)} record(s), e.g. {files[0]}"
        elif now - release.lstat().st_mtime < config.min_release_age_days * 86400:
            reason = f"younger than {config.min_release_age_days} days"
        if reason:
            kept.append({"target": resolved, "reason": reason})
        else:
            actions.append(
                Action("frontend_release", resolved, "superseded release", _dir_bytes(release),
                       ["rm", "-rf", "--one-file-system", "--", resolved])
            )
    return actions, kept


def plan_docker(
    config: Config,
    run: Runner,
    *,
    now: datetime | None = None,
    in_use: set[str] | None = None,
    references: dict[str, list[str]] | None = None,
) -> tuple[list[Action], list[dict[str, str]]]:
    actions: list[Action] = [
        Action("docker_build_cache", f"older than {config.build_cache_age_hours}h", "reproducible build cache", 0,
               ["docker", "builder", "prune", "--force", "--filter", f"until={config.build_cache_age_hours}h"])
    ]
    kept: list[dict[str, str]] = []
    if in_use is None:
        in_use, _mounts = docker_usage(run)
    dangling = run(["docker", "images", "--filter", "dangling=true", "--no-trunc", "--quiet"])
    if dangling.returncode != 0:
        raise FailClosed("docker images failed")
    image_ids = sorted({image for image in dangling.stdout.split() if IMAGE_ID.match(image)})
    if references is None:
        needles = [needle for image in image_ids for needle in (image, image[7:19])]
        references = reference_index(config, needles)
    now = now or datetime.now(UTC)
    for image_id in image_ids:
        reason = None
        if image_id in config.protected_images:
            reason = "listed as protected"
        elif image_id in in_use:
            reason = "used by a container"
        else:
            files = references.get(image_id, []) + references.get(image_id[7:19], [])
            if files:
                reason = f"referenced by {len(files)} record(s), e.g. {files[0]}"
        if reason:
            kept.append({"target": image_id, "reason": reason})
            continue
        info = run(["docker", "image", "inspect", "--format", "{{.Created}}|{{.Size}}", image_id])
        try:
            created_text, size_text = info.stdout.strip().split("|")
            created = datetime.fromisoformat(created_text.replace("Z", "+00:00")[:32])
            size = int(size_text)
        except (ValueError, TypeError):
            kept.append({"target": image_id, "reason": "could not inspect; skipped"})
            continue
        if (now - created).total_seconds() < config.min_image_age_days * 86400:
            kept.append({"target": image_id, "reason": f"younger than {config.min_image_age_days} days"})
            continue
        actions.append(Action("dangling_image", image_id, "unused dangling image", size, ["docker", "image", "rm", image_id]))
    return actions, kept


def plan_apt(run: Runner) -> tuple[list[Action], list[dict[str, str]]]:
    busy = run(["pgrep", "-x", "apt|apt-get|dpkg|unattended-upgr"])
    if busy.returncode == 0:
        return [], [{"target": "/var/cache/apt/archives", "reason": "apt or dpkg is running"}]
    archives = Path("/var/cache/apt/archives")
    size = sum(p.stat().st_size for p in archives.glob("*.deb")) if archives.is_dir() else 0
    return [Action("apt_cache", str(archives), "downloaded packages", size, ["apt-get", "clean"])], []


def plan_all(config: Config, run: Runner) -> tuple[list[Action], list[dict[str, str]], list[str]]:
    actions, kept = plan_apt(run)
    withheld: list[str] = []
    if not config.protected_inventories_ok:
        withheld.append(f"image and release candidates withheld: {config.protected_inventory_error}")
        return actions, kept, withheld
    try:
        in_use, mounts = docker_usage(run)
        docker_actions, docker_kept = plan_docker(config, run, in_use=in_use)
        release_actions, release_kept = plan_releases(config, mount_sources=mounts)
    except FailClosed as error:
        withheld.append(f"image and release candidates withheld: {error}")
        return actions, kept, withheld
    return actions + docker_actions + release_actions, kept + docker_kept + release_kept, withheld


def manifest_document(actions: list[Action], disk: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nexolab-storage-cleanup-manifest",
        "created_at": datetime.now(UTC).isoformat(),
        "disk": disk,
        "entries": [
            {"kind": a.kind, "target": a.target, "bytes": a.bytes, "command": a.command} for a in actions
        ],
        "estimated_bytes": sum(a.bytes for a in actions),
    }


def load_manifest(path: str, expected_sha256: str) -> dict[str, object]:
    data = Path(path).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") or actual != expected_sha256:
        raise FailClosed("manifest SHA-256 does not match the approved value")
    document = json.loads(data)
    if document.get("schema_version") != 1 or document.get("kind") != "nexolab-storage-cleanup-manifest":
        raise FailClosed("not a NEXOLAB storage cleanup manifest")
    return document


def select_approved(actions: list[Action], manifest: dict[str, object]) -> tuple[list[Action], list[dict[str, str]]]:
    approved = {(entry["kind"], entry["target"]) for entry in manifest["entries"]}  # type: ignore[index]
    chosen = [a for a in actions if (a.kind, a.target) in approved]
    still = {(a.kind, a.target) for a in chosen}
    skipped = [
        {"target": f"{kind}:{target}", "reason": "no longer eligible; skipped"}
        for kind, target in sorted(approved - still)
    ]
    return chosen, skipped


def execute(actions: list[Action], run: Runner) -> None:
    for action in actions:
        result = run(action.command)
        action.applied = result.returncode == 0
        if not action.applied:
            action.error = (result.stderr or result.stdout or "").strip()[:300]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None, *, run: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(description="NEXOLAB storage housekeeping and disk guard")
    parser.add_argument("--guard-only", action="store_true", help="only measure free space and report the level")
    parser.add_argument("--env-file", help="read settings from this file (for manual runs)")
    parser.add_argument("--apply-manifest", help="apply this reviewed manifest (requires --manifest-sha256)")
    parser.add_argument("--manifest-sha256", help="approved SHA-256 of the manifest")
    args = parser.parse_args(argv)
    environ: dict[str, str] = dict(os.environ)
    if args.env_file:
        environ.update(read_env_file(args.env_file))
    config = config_from_env(environ)
    status = Path(config.status_dir)
    before = disk_state(config)
    report: dict[str, object] = {"time": datetime.now(UTC).isoformat(), "disk_before": before}
    if args.guard_only:
        report["mode"] = "guard"
        level = before["level"]
        _safe_write(status / "guard.json", json.dumps(report, indent=2) + "\n")
        print(_prefix(level) + json.dumps(report, sort_keys=True), flush=True)
        return 2 if level == "critical" else 0

    actions, kept, withheld = plan_all(config, run)
    if args.apply_manifest:
        report["mode"] = "apply"
        try:
            manifest = load_manifest(args.apply_manifest, args.manifest_sha256 or "")
        except (FailClosed, OSError, ValueError) as error:
            print(f"REFUSED: {error}", flush=True)
            return 3
        actions, skipped = select_approved(actions, manifest)
        kept.extend(skipped)
        execute(actions, run)
    else:
        report["mode"] = "report"
        document = manifest_document(actions, before)
        text = json.dumps(document, indent=2, sort_keys=True) + "\n"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        name = f"manifest-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        _safe_write(status / name, text)
        report["manifest"] = {"path": str(status / name), "sha256": digest}
    report["actions"] = [asdict(action) for action in actions]
    report["kept"] = kept
    report["withheld"] = withheld
    report["estimated_bytes"] = sum(action.bytes for action in actions)
    report["disk_after"] = disk_state(config)
    _safe_write(status / "housekeeping.json", json.dumps(report, indent=2) + "\n")
    level = report["disk_after"]["level"]  # type: ignore[index]
    summary = {key: report[key] for key in ("mode", "disk_before", "estimated_bytes", "disk_after", "manifest") if key in report}
    print(_prefix(level) + json.dumps(summary, sort_keys=True), flush=True)
    for line in withheld:
        print("<4>WITHHELD " + line, flush=True)
    for action in report["actions"]:  # type: ignore[union-attr]
        state = "planned" if report["mode"] == "report" else "applied" if action["applied"] else "FAILED " + str(action["error"])
        print(f"{state}: {action['kind']} {action['target']} ({action['bytes']} bytes) :: {' '.join(action['command'])}", flush=True)
    for item in kept:
        print(f"kept: {item['target']} ({item['reason']})", flush=True)
    if report["mode"] == "apply" and any(not a.applied for a in actions):
        return 1
    return 2 if level == "critical" else 0


def _prefix(level: object) -> str:
    return {"ok": "", "warning": "<4>WARNING ", "critical": "<2>CRITICAL "}.get(str(level), "")


def _safe_write(path: Path, text: str) -> None:
    try:
        _write(path, text)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
