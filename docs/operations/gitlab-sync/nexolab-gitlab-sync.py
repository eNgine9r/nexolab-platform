#!/usr/bin/env python3
"""NEXOLAB GitHub -> corporate GitLab fast-forward synchronization (#1713).

Owner-installed to /usr/local/lib/nexolab-gitlab-sync/ and run by
nexolab-gitlab-sync.service under an isolated DynamicUser identity.

Safety contract:
- GitHub (public, canonical) is only ever fetched, never authenticated.
- The GitLab destination receives fast-forward pushes of ``main`` and of
  explicitly approved release tags only. No force, mirror, delete or prune.
- Diverged or GitLab-ahead ``main``, rewritten source history and tag
  collisions fail closed without writing anything.
- The pushed commit SHA is verified on the destination afterwards.
- The token is never read by this script: git obtains it through the
  askpass helper from the systemd credential, only for the destination host.
- Output is one bounded JSON status line; URLs are reduced to host names.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

CANONICAL_SOURCE = "https://github.com/eNgine9r/nexolab-platform.git"
BRANCH = "main"
GIT_TIMEOUT_SECONDS = 300
STDERR_LIMIT = 400

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_RESOURCE = 3
EXIT_DIVERGED = 4
EXIT_REMOTE = 5
EXIT_TAG_COLLISION = 6
EXIT_VERIFY = 7

_TAG_RE = re.compile(r"^v?[0-9A-Za-z][0-9A-Za-z._-]{0,99}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SyncError(Exception):
    def __init__(self, code: int, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Config:
    source_url: str
    dest_url: str
    state_dir: Path
    mode: str = "check"
    approved_tags: tuple[str, ...] = ()
    min_free_gib: int = 20
    min_host_available_mib: int = 400
    askpass: str | None = None
    ci_skip: bool = True


@dataclass
class Report:
    result: str = "unknown"
    mode: str = "check"
    destination_host: str = ""
    source_sha: str | None = None
    destination_sha_before: str | None = None
    destination_sha_after: str | None = None
    relation: str | None = None
    ahead_source: int | None = None
    ahead_destination: int | None = None
    pushed: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    destination_only_refs: int | None = None
    reason: str | None = None
    detail: str | None = None
    duration_seconds: float | None = None


def redact(text: str) -> str:
    """Remove any URL userinfo and bound the length."""
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1", text)
    text = " ".join(text.split())
    return text[:STDERR_LIMIT]


def _host(url: str) -> str:
    return urlsplit(url).hostname or "local"


def validate_config(config: Config, *, allow_local: bool = False) -> None:
    if config.mode not in {"check", "push"}:
        raise SyncError(EXIT_CONFIG, "invalid_mode")
    if not allow_local and config.source_url != CANONICAL_SOURCE:
        raise SyncError(EXIT_CONFIG, "unexpected_source")
    for name, url in (("source", config.source_url), ("destination", config.dest_url)):
        parts = urlsplit(url)
        if parts.username or parts.password or "@" in parts.netloc:
            raise SyncError(EXIT_CONFIG, f"{name}_url_contains_credentials")
        if allow_local and parts.scheme == "file":
            continue
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
            raise SyncError(EXIT_CONFIG, f"{name}_url_not_plain_https")
    if config.source_url == config.dest_url:
        raise SyncError(EXIT_CONFIG, "source_equals_destination")
    for tag in config.approved_tags:
        if not _TAG_RE.match(tag) or ".." in tag or tag.endswith((".lock", ".")):
            raise SyncError(EXIT_CONFIG, "invalid_approved_tag")
    if not allow_local and config.askpass is None:
        raise SyncError(EXIT_CONFIG, "askpass_missing")


class Git:
    def __init__(self, repo: Path, config: Config) -> None:
        self.repo = repo
        self.config = config

    def _env(self, *, destination: bool) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.repo),
            "LANG": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        if destination and self.config.askpass:
            env["GIT_ASKPASS"] = self.config.askpass
            env["NEXOLAB_SYNC_DEST_HOST"] = _host(self.config.dest_url)
            if "CREDENTIALS_DIRECTORY" in os.environ:
                env["CREDENTIALS_DIRECTORY"] = os.environ["CREDENTIALS_DIRECTORY"]
        return env

    def run(self, *args: str, destination: bool = False, check: bool = True) -> str:
        command = [
            "git",
            "-c", "credential.helper=",
            "-c", "core.askPass=",
            "-c", "protocol.version=2",
            "-C", str(self.repo),
            *args,
        ]
        try:
            completed = subprocess.run(
                command,
                env=self._env(destination=destination),
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SyncError(EXIT_REMOTE, "git_timeout", args[0]) from error
        if check and completed.returncode != 0:
            raise SyncError(EXIT_REMOTE, f"git_{args[0]}_failed", redact(completed.stderr))
        return completed.stdout.strip()

    def is_ancestor(self, older: str, newer: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(self.repo), "merge-base", "--is-ancestor", older, newer],
            env=self._env(destination=False),
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise SyncError(EXIT_VERIFY, "ancestry_check_failed")
        return result.returncode == 0

    def rev(self, ref: str) -> str | None:
        value = self.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        return value if _SHA_RE.match(value or "") else None

    def count(self, spec: str) -> int:
        return int(self.run("rev-list", "--count", spec) or 0)

    def remote_refs(self, url: str, *patterns: str, destination: bool) -> dict[str, str]:
        output = self.run("ls-remote", "--refs", url, *patterns, destination=destination)
        refs: dict[str, str] = {}
        for line in output.splitlines():
            sha, _, ref = line.partition("\t")
            if _SHA_RE.match(sha):
                refs[ref] = sha
        return refs


def free_gib(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)


def host_available_mib() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 1 << 30


class _Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> bool:
        self.handle = open(self.path, "w", encoding="ascii")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def __exit__(self, *_exc: object) -> None:
        if self.handle:
            self.handle.close()


def _read_last_source(state_dir: Path) -> str | None:
    try:
        value = json.loads((state_dir / "last-status.json").read_text(encoding="utf-8")).get("source_sha")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and _SHA_RE.match(value) else None


def synchronize(config: Config, report: Report, *, allow_local: bool = False) -> None:
    validate_config(config, allow_local=allow_local)
    report.mode = config.mode
    report.destination_host = _host(config.dest_url)
    config.state_dir.mkdir(parents=True, exist_ok=True)

    if free_gib(config.state_dir) < config.min_free_gib:
        raise SyncError(EXIT_RESOURCE, "free_disk_below_reserve")
    if host_available_mib() < config.min_host_available_mib:
        raise SyncError(EXIT_RESOURCE, "host_memory_pressure")

    repo = config.state_dir / "repository.git"
    if not (repo / "HEAD").exists():
        subprocess.run(["git", "init", "--quiet", "--bare", str(repo)], check=True, timeout=60,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(config.state_dir)})
    git = Git(repo, config)
    previous_source = _read_last_source(config.state_dir)

    # 1. Source (public, unauthenticated): main and approved tags into private refs.
    git.run("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", config.source_url,
            f"+refs/heads/{BRANCH}:refs/sync/source/{BRANCH}")
    source = git.rev(f"refs/sync/source/{BRANCH}")
    if source is None:
        raise SyncError(EXIT_REMOTE, "source_main_missing")
    report.source_sha = source
    if previous_source and git.rev(previous_source) and not git.is_ancestor(previous_source, source):
        raise SyncError(EXIT_DIVERGED, "source_history_rewritten")

    # 2. Destination (authenticated read): main and approved tags, plus a ref inventory.
    destination_refs = git.remote_refs(config.dest_url, destination=True)
    report.destination_only_refs = len(
        [ref for ref in destination_refs if ref not in {f"refs/heads/{BRANCH}"} and not ref.startswith("refs/tags/")]
    )
    destination = destination_refs.get(f"refs/heads/{BRANCH}")
    if destination is None:
        raise SyncError(EXIT_DIVERGED, "destination_main_missing")
    report.destination_sha_before = destination
    git.run("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", config.dest_url,
            f"+refs/heads/{BRANCH}:refs/sync/destination/{BRANCH}", destination=True)
    if git.rev(f"refs/sync/destination/{BRANCH}") != destination:
        raise SyncError(EXIT_VERIFY, "destination_changed_during_fetch")

    # 3. Relation of the two histories.
    if destination == source:
        report.relation = "equal"
    elif git.is_ancestor(destination, source):
        report.relation = "fast_forward"
    elif git.is_ancestor(source, destination):
        report.relation = "destination_ahead"
    else:
        report.relation = "diverged"
    report.ahead_source = git.count(f"{destination}..{source}")
    report.ahead_destination = git.count(f"{source}..{destination}")
    if report.relation in {"destination_ahead", "diverged"}:
        raise SyncError(EXIT_DIVERGED, f"main_{report.relation}")

    # 4. Approved tags: present on source, absent or identical on destination.
    tag_plan: list[tuple[str, str]] = []
    for tag in config.approved_tags:
        git.run("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", config.source_url,
                f"+refs/tags/{tag}:refs/sync/source-tags/{tag}")
        source_tag = git.run("rev-parse", "--verify", f"refs/sync/source-tags/{tag}")
        if not git.is_ancestor(f"refs/sync/source-tags/{tag}^{{commit}}", source):
            report.tags[tag] = "not_on_source_main"
            raise SyncError(EXIT_TAG_COLLISION, "approved_tag_not_on_main", tag)
        existing = destination_refs.get(f"refs/tags/{tag}")
        if existing is None:
            report.tags[tag] = "to_push"
            tag_plan.append((tag, source_tag))
        elif existing == source_tag:
            report.tags[tag] = "present"
        else:
            report.tags[tag] = "collision"
            raise SyncError(EXIT_TAG_COLLISION, "tag_collision", tag)

    if config.mode == "check":
        report.result = "check_ok"
        return

    # 5. Fast-forward push (no force); git itself also rejects any non-fast-forward.
    # ci.skip keeps mirror pushes from starting GitLab pipelines until they are reviewed (#1633).
    push_options = ("--push-option=ci.skip",) if config.ci_skip else ()
    if report.relation == "fast_forward":
        git.run("push", "--quiet", "--porcelain", "--no-verify", *push_options, config.dest_url,
                f"{source}:refs/heads/{BRANCH}", destination=True)
        report.pushed.append(BRANCH)
    for tag, _object in tag_plan:
        git.run("push", "--quiet", "--porcelain", "--no-verify", *push_options, config.dest_url,
                f"refs/sync/source-tags/{tag}:refs/tags/{tag}", destination=True)
        report.pushed.append(f"tag:{tag}")

    # 6. Verify the destination now carries exactly the source SHA and tag objects.
    after = git.remote_refs(config.dest_url, f"refs/heads/{BRANCH}", "refs/tags/*", destination=True)
    report.destination_sha_after = after.get(f"refs/heads/{BRANCH}")
    if report.destination_sha_after != source:
        raise SyncError(EXIT_VERIFY, "destination_sha_mismatch")
    for tag, object_id in tag_plan:
        if after.get(f"refs/tags/{tag}") != object_id:
            raise SyncError(EXIT_VERIFY, "destination_tag_mismatch", tag)
    report.result = "synchronized" if report.pushed else "up_to_date"


def _write_json(path: Path, report: Report) -> None:
    try:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(report.__dict__, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def run(config: Config, *, allow_local: bool = False) -> tuple[int, Report]:
    """Run one synchronization; success updates last-status.json, failure last-failure.json."""
    report = Report(mode=config.mode)
    started = time.monotonic()
    code = EXIT_OK
    config.state_dir.mkdir(parents=True, exist_ok=True)
    with _Lock(config.state_dir / ".lock") as acquired:
        if not acquired:
            report.result = "skipped_running"
            return EXIT_OK, report
        try:
            synchronize(config, report, allow_local=allow_local)
        except SyncError as error:
            code = error.code
            report.result = "failed"
            report.reason = error.reason
            report.detail = redact(error.detail) or None
        report.duration_seconds = round(time.monotonic() - started, 2)
        name = "last-status.json" if code == EXIT_OK else "last-failure.json"
        _write_json(config.state_dir / name, report)
    return code, report


def _read_tags(path: str | None) -> tuple[str, ...]:
    if not path:
        return ()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError) as error:
        raise SyncError(EXIT_CONFIG, "approved_tags_unreadable") from error
    return tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))


def config_from_environment(environ: dict[str, str] | os._Environ[str] = os.environ) -> Config:
    state = environ.get("STATE_DIRECTORY") or environ.get("GITLAB_SYNC_STATE_DIR")
    if not state:
        raise SyncError(EXIT_CONFIG, "state_directory_missing")
    return Config(
        source_url=environ.get("GITLAB_SYNC_SOURCE_URL", CANONICAL_SOURCE),
        dest_url=environ.get("GITLAB_SYNC_DEST_URL", ""),
        state_dir=Path(state.split(":")[0]),
        mode=environ.get("GITLAB_SYNC_MODE", "check"),
        approved_tags=_read_tags(environ.get("GITLAB_SYNC_APPROVED_TAGS_FILE")),
        min_free_gib=int(environ.get("GITLAB_SYNC_MIN_FREE_GIB", "20")),
        min_host_available_mib=int(environ.get("GITLAB_SYNC_MIN_HOST_AVAILABLE_MIB", "400")),
        askpass=environ.get("GITLAB_SYNC_ASKPASS"),
        ci_skip=environ.get("GITLAB_SYNC_CI_SKIP", "1") != "0",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare histories only; never push")
    args = parser.parse_args(argv)
    try:
        config = config_from_environment()
    except (SyncError, ValueError) as error:
        reason = error.reason if isinstance(error, SyncError) else "invalid_number"
        print(json.dumps({"result": "failed", "reason": reason}), flush=True)
        return EXIT_CONFIG
    if args.check:
        config = Config(**{**config.__dict__, "mode": "check"})
    code, report = run(config)
    print(json.dumps(report.__dict__, sort_keys=True), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
