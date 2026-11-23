#!/usr/bin/env python3
"""NEXOLAB storage housekeeping and disk guard (#1710, #1551).

Owner-installed to /usr/local/lib/nexolab-storage/ and run as root by
nexolab-storage-housekeeping.service (weekly) and nexolab-storage-guard.service
(every 15 minutes, ``--guard-only``).

Housekeeping touches only reproducible artifacts, and only in ``apply`` mode
(default ``report`` prints the exact plan):

- APT downloaded packages (``apt-get clean``), never while apt/dpkg runs;
- Docker build cache older than 7 days (``docker builder prune --filter until``);
- dangling images older than 7 days that no container uses and that are not
  listed as protected (``docker image rm <id>``, never forced);
- frontend release directories named ``<40-hex>-<YYYYMMDDTHHMMSSZ>`` directly
  under a configured release root, never a symlink, outside the newest
  ``keep_releases``, older than ``min_release_age_days``, not referenced by any
  systemd unit, not a running process' directory, not listed as protected.

It never touches Docker volumes, containers, tagged images, PostgreSQL,
deployment evidence, backups, Commander workspaces or anything outside the
configured roots. The guard only measures free space: WARNING below
``warn_gib`` (40), CRITICAL below ``critical_gib`` (20).
"""

from __future__ import annotations

import argparse
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
from typing import Callable

RELEASE_NAME = re.compile(r"^(?P<sha>[0-9a-f]{40})-(?P<stamp>\d{8}T\d{6}Z)$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
UNIT_DIRS = ("/etc/systemd/system", "/run/systemd/system", "/lib/systemd/system")
GIB = 1024**3


@dataclass
class Config:
    mode: str = "report"
    release_roots: tuple[str, ...] = ()
    keep_releases: int = 3
    min_release_age_days: int = 14
    min_image_age_days: int = 7
    build_cache_age_hours: int = 168
    warn_gib: float = 40.0
    critical_gib: float = 20.0
    protected_paths: tuple[str, ...] = ()
    protected_images: tuple[str, ...] = ()
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


def _lines(path: str | None) -> tuple[str, ...]:
    if not path:
        return ()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    return tuple(line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def config_from_env(environ: dict[str, str] | os._Environ[str] = os.environ) -> Config:
    mode = environ.get("STORAGE_HOUSEKEEPING_MODE", "report")
    if mode not in {"report", "apply"}:
        raise SystemExit(f"invalid STORAGE_HOUSEKEEPING_MODE {mode!r}")
    roots = tuple(root for root in environ.get("STORAGE_RELEASE_ROOTS", "").split(":") if root)
    return Config(
        mode=mode,
        release_roots=roots,
        keep_releases=max(2, int(environ.get("STORAGE_KEEP_RELEASES", "3"))),
        min_release_age_days=max(1, int(environ.get("STORAGE_MIN_RELEASE_AGE_DAYS", "14"))),
        min_image_age_days=max(1, int(environ.get("STORAGE_MIN_IMAGE_AGE_DAYS", "7"))),
        build_cache_age_hours=max(24, int(environ.get("STORAGE_BUILD_CACHE_AGE_HOURS", "168"))),
        warn_gib=float(environ.get("STORAGE_WARN_GIB", "40")),
        critical_gib=float(environ.get("STORAGE_CRITICAL_GIB", "20")),
        protected_paths=_lines(environ.get("STORAGE_PROTECTED_PATHS_FILE")),
        protected_images=_lines(environ.get("STORAGE_PROTECTED_IMAGES_FILE")),
        status_dir=environ.get("STATE_DIRECTORY", "/var/lib/nexolab-storage").split(":")[0],
    )


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
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and os.lstat(os.path.join(root, d)).st_dev == device]
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
            if unit.is_file() and unit.suffix in {".service", ".conf", ".socket", ".timer"}:
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


def plan_releases(
    config: Config,
    *,
    now: float | None = None,
    unit_text: str | None = None,
    process_paths: set[str] | None = None,
) -> tuple[list[Action], list[dict[str, str]]]:
    now = time.time() if now is None else now
    unit_text = _unit_text(config) if unit_text is None else unit_text
    process_paths = _process_paths() if process_paths is None else process_paths
    actions: list[Action] = []
    kept: list[dict[str, str]] = []
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
        for index, release in enumerate(releases):
            resolved = str(release)
            reason = None
            if release.is_symlink() or not release.is_dir():
                reason = "symlink or not a directory"
            elif index < config.keep_releases:
                reason = f"among the newest {config.keep_releases}"
            elif any(resolved == p or resolved.startswith(p.rstrip("/") + "/") or p.startswith(resolved + "/") for p in config.protected_paths):
                reason = "listed as protected"
            elif resolved in unit_text or release.name in unit_text:
                reason = "referenced by a systemd unit"
            elif any(p == resolved or p.startswith(resolved + "/") for p in process_paths):
                reason = "in use by a running process"
            elif now - release.lstat().st_mtime < config.min_release_age_days * 86400:
                reason = f"younger than {config.min_release_age_days} days"
            if reason:
                kept.append({"target": resolved, "reason": reason})
            else:
                actions.append(
                    Action("frontend_release", resolved, "superseded release", _dir_bytes(release), ["rm", "-rf", "--one-file-system", "--", resolved])
                )
    return actions, kept


def plan_docker(config: Config, run: Runner, *, now: datetime | None = None) -> tuple[list[Action], list[dict[str, str]]]:
    actions: list[Action] = []
    kept: list[dict[str, str]] = []
    if shutil.which("docker") is None and run is default_runner:
        return actions, [{"target": "docker", "reason": "docker not installed"}]
    actions.append(
        Action("docker_build_cache", f"older than {config.build_cache_age_hours}h", "reproducible build cache", 0,
               ["docker", "builder", "prune", "--force", "--filter", f"until={config.build_cache_age_hours}h"])
    )
    used = run(["docker", "ps", "-aq", "--no-trunc"])
    container_ids = used.stdout.split() if used.returncode == 0 else []
    in_use: set[str] = set()
    if container_ids:
        inspected = run(["docker", "inspect", "--format", "{{.Image}}", *container_ids])
        if inspected.returncode != 0:
            return actions, [{"target": "dangling images", "reason": "container inspection failed; skipped"}]
        in_use = set(inspected.stdout.split())
    dangling = run(["docker", "images", "--filter", "dangling=true", "--no-trunc", "--quiet"])
    if dangling.returncode != 0:
        return actions, [{"target": "dangling images", "reason": "listing failed; skipped"}]
    now = now or datetime.now(UTC)
    for image_id in sorted(set(dangling.stdout.split())):
        if not IMAGE_ID.match(image_id):
            continue
        if image_id in config.protected_images:
            kept.append({"target": image_id, "reason": "listed as protected"})
            continue
        if image_id in in_use:
            kept.append({"target": image_id, "reason": "used by a container"})
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


def execute(actions: list[Action], run: Runner) -> None:
    for action in actions:
        result = run(action.command)
        action.applied = result.returncode == 0
        if not action.applied:
            action.error = (result.stderr or result.stdout or "").strip()[:300]


def main(argv: list[str] | None = None, *, run: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(description="NEXOLAB storage housekeeping and disk guard")
    parser.add_argument("--guard-only", action="store_true", help="only measure free space and report the level")
    args = parser.parse_args(argv)
    config = config_from_env()
    before = disk_state(config)
    report: dict[str, object] = {"time": datetime.now(UTC).isoformat(), "mode": config.mode, "disk_before": before}
    if not args.guard_only:
        actions: list[Action] = []
        kept: list[dict[str, str]] = []
        for planned, protected in (plan_apt(run), plan_docker(config, run), plan_releases(config)):
            actions.extend(planned)
            kept.extend(protected)
        if config.mode == "apply":
            execute(actions, run)
        report["actions"] = [asdict(action) for action in actions]
        report["kept"] = kept
        report["estimated_bytes"] = sum(action.bytes for action in actions)
        report["disk_after"] = disk_state(config)
    level = (report.get("disk_after") or before)["level"]  # type: ignore[index]
    try:
        Path(config.status_dir).mkdir(parents=True, exist_ok=True)
        name = "guard.json" if args.guard_only else "housekeeping.json"
        (Path(config.status_dir) / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    summary = {key: report[key] for key in ("mode", "disk_before", "estimated_bytes", "disk_after") if key in report}
    prefix = {"ok": "", "warning": "<4>WARNING ", "critical": "<2>CRITICAL "}[str(level)]
    print(prefix + json.dumps(summary, sort_keys=True), flush=True)
    if not args.guard_only:
        for action in report["actions"]:  # type: ignore[union-attr]
            state = "applied" if action["applied"] else ("FAILED " + str(action["error"])) if config.mode == "apply" else "planned"
            print(f"{state}: {action['kind']} {action['target']} ({action['bytes']} bytes) :: {' '.join(action['command'])}", flush=True)
        for item in report["kept"]:  # type: ignore[union-attr]
            print(f"kept: {item['target']} ({item['reason']})", flush=True)
    return 2 if level == "critical" else 0


if __name__ == "__main__":
    sys.exit(main())
