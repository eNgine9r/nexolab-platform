#!/usr/bin/env python3
"""Preserve installed non-root frontend accounts during an explicit root handoff.

No existing release, evidence, configuration, lock or volume is reowned. Git is
delegated to the repository owner; candidate ownership changes are narrowly bound
to this attempt's new release directories, without widening permission modes.
"""
from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import subprocess


def show(unit: str, field: str) -> str:
    return subprocess.run(["/usr/bin/systemctl", "show", unit, "-p", field, "--value"],
                          check=True, capture_output=True, text=True, timeout=15).stdout.strip()


def service_identity(owner) -> tuple[str, str]:
    if owner.pw_uid == 0:
        raise ValueError("non-root service owner required")
    group = grp.getgrgid(owner.pw_gid).gr_name
    for unit in ("nexolab-dashboard.service", "nexolab-external-frontend.service"):
        if (show(unit, "User") != owner.pw_name or show(unit, "Group") != group
                or show(unit, "DynamicUser") != "no" or show(unit, "DropInPaths")):
            raise ValueError("installed frontend service accounts or overrides differ")
    return owner.pw_name, group


def context(repo: Path, name: str):
    if os.geteuid() != 0 or os.environ.get("SUDO_USER") != name:
        raise ValueError("explicit sudo repository owner required")
    owner = pwd.getpwnam(name)
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", name) or owner.pw_uid == 0:
        raise ValueError("invalid non-root repository owner")
    for path in (repo, repo / ".git", repo / ".git/index"):
        if path.is_symlink() or path.stat().st_uid != owner.pw_uid:
            raise ValueError("repository and Git index must retain owner identity")
    service_identity(owner)
    return owner


def git_shim(repo: Path, owner: str, control: str, target: str,
             *, runuser: str = "/usr/sbin/runuser") -> str:
    if (not re.fullmatch(r"[a-z_][a-z0-9_-]*", owner)
            or not re.fullmatch(r"[0-9a-f]{40}", control)
            or not re.fullmatch(r"[0-9a-f]{40}", target)):
        raise ValueError("exact Git owner/source pins required")
    qrepo = shlex.quote(str(repo))
    return f'''#!/bin/sh
set -eu
if [ "${{1:-}}" = -C ]; then
  [ "${{2:-}}" = {qrepo} ] || exit 64
  shift 2
fi
case "${{1:-}}" in
  fetch) [ "$#" = 4 ] && [ "$2" = --prune ] && [ "$3" = origin ] && [ "$4" = main ] || exit 64 ;;
  merge) [ "$#" = 3 ] && [ "$2" = --ff-only ] && [ "$3" = '{control}' ] || exit 64 ;;
  switch) case "$*" in 'switch --detach {target}'|'switch main') ;; *) exit 64 ;; esac ;;
  archive) [ "$#" = 3 ] && [ "$2" = --format=tar ] && [ "$3" = '{target}' ] || exit 64 ;;
  branch) [ "$#" = 2 ] && [ "$2" = --show-current ] || exit 64 ;;
  remote) [ "$#" = 3 ] && [ "$2" = get-url ] && [ "$3" = origin ] || exit 64 ;;
  diff|status|rev-parse|merge-base|cat-file|show|ls-tree|ls-files|log) ;;
  *) exit 64 ;;
esac
exec {shlex.quote(runuser)} --user '{owner}' -- /usr/bin/git --no-optional-locks -C {qrepo} "$@"
'''


def own_new_release(repo: Path, release: Path, owner, target: str, stamp: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", target) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", stamp):
        raise ValueError("exact new release identity required")
    expected = {repo / "runtime" / name / f"{target}-{stamp}"
                for name in ("frontend-releases", "external-frontend-releases")}
    if release not in expected or not release.is_dir():
        raise ValueError("only this attempt's candidate release may be reowned")
    for parent in (release, *release.parents):
        if parent.is_symlink():
            raise ValueError("symlinked candidate ancestor rejected")
    paths = [release]
    for directory, directories, files in os.walk(release, followlinks=False):
        paths.extend(Path(directory) / name for name in directories + files)
    # Validate the entire tree before changing any ownership. Internal executable
    # symlinks are expected in node_modules; external references and hardlinks are not.
    for path in paths:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode):
            if not path.resolve().is_relative_to(release):
                raise ValueError("candidate symlink escapes release")
        elif not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)):
            raise ValueError("unexpected candidate file type")
        elif stat.S_ISREG(value.st_mode) and value.st_nlink != 1:
            raise ValueError("hardlinked candidate file rejected")
    for path in reversed(paths):
        os.chown(path, owner.pw_uid, owner.pw_gid, follow_symlinks=False)
    # Check actual traversal/reading under the service account, including private
    # identity/environment files. No chmod on candidates or existing ancestors.
    subprocess.run(["/usr/sbin/runuser", "--user", owner.pw_name, "--", "/usr/bin/python3", "-c",
                    "import os,sys; from pathlib import Path; p=Path(sys.argv[1]); "
                    "assert all(os.access(x, os.R_OK | (os.X_OK if x.is_dir() else 0)) "
                    "for x in [p, *p.rglob('*')])", str(release)], check=True, timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "release"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--control")
    parser.add_argument("--target", required=True)
    parser.add_argument("--shim", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--stamp")
    args = parser.parse_args()
    if args.action == "configure":
        owner = context(args.repo, args.owner)
        args.shim.mkdir(mode=0o700)
        path = args.shim / "git"
        with path.open("x") as stream:
            stream.write(git_shim(args.repo, owner.pw_name, args.control, args.target))
        path.chmod(0o700)
        print(grp.getgrgid(owner.pw_gid).gr_name)
    else:
        if os.geteuid() != 0:
            raise ValueError("privileged release handoff required")
        owner = context(args.repo, args.owner)
        own_new_release(args.repo, args.release, owner, args.target, args.stamp)


if __name__ == "__main__":
    main()
