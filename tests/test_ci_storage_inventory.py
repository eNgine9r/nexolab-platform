"""#1710 storage inventory: cleanup candidates must never include protected assets.

Runs the real script in a fake environment: `id` reports root, `docker` is a recorder
stub, `runuser` drops straight to the command. Covers the 2026-11-25 finding that the
containerd image store lists TAGGED recovery images under `dangling=true`, and that
node_modules/.next inside release folders are the release itself, not caches.
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "operations" / "storage" / "nexolab-storage-inventory.sh"
TAGGED = "sha256:" + "a" * 64
UNTAGGED = "sha256:" + "b" * 64
USED = "sha256:" + "c" * 64

FAKE_DOCKER = textwrap.dedent(f"""\
    #!/usr/bin/env bash
    echo "$*" >> "$DOCKER_LOG"
    case "$*" in
      "images -q --filter dangling=true --no-trunc") printf '%s\\n' {TAGGED} {UNTAGGED} {USED} ;;
      "ps -aq") echo c1 ;;
      "inspect --format {{{{.Image}}}} c1") echo {USED} ;;
      "image inspect --format {{{{join .RepoTags \\" \\"}}}} {TAGGED}") echo "nexolab/dashboard:recovery-x-protected-arm64" ;;
      "image inspect --format {{{{join .RepoTags \\" \\"}}}} "*) echo "" ;;
      "image inspect --format {{{{.Size}}}} "*) echo 1048576 ;;
      "image inspect "*) echo "[]" ;;
      "image ls --no-trunc --format {{{{.ID}}}} {{{{.Repository}}}}:{{{{.Tag}}}}") echo "{UNTAGGED} <none>:<none>" ;;
      *) : ;;
    esac
    exit 0
""")


def write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


class StorageInventoryCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="nxinv-"))
        bin_dir = cls.tmp / "bin"
        bin_dir.mkdir()
        write_exec(bin_dir / "id", '#!/bin/sh\n[ "$1" = "-u" ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
        write_exec(bin_dir / "docker", FAKE_DOCKER)
        write_exec(bin_dir / "runuser", '#!/bin/sh\nshift 3\nexec "$@"\n')  # runuser -u USER -- cmd...
        home = cls.tmp / "home"
        workspaces = home / "commander-workspaces"
        release = workspaces / "nexolab-9999-release-artifacts" / "lan" / "release"
        (release / "node_modules" / "next").mkdir(parents=True)
        (release / "node_modules" / "next" / "index.js").write_text("x" * 4096)
        (release / ".next").mkdir()
        remote = cls.tmp / "remote.git"
        git("init", "-q", "--bare", str(remote), cwd=cls.tmp)
        checkout = workspaces / "nexolab-clean-checkout"
        checkout.mkdir(parents=True)
        git("init", "-q", "-b", "main", cwd=checkout)
        (checkout / ".gitignore").write_text("node_modules/\n.next/\n")
        git("add", ".gitignore", cwd=checkout)
        git("commit", "-q", "-m", "init", cwd=checkout)
        git("remote", "add", "origin", str(remote), cwd=checkout)
        git("push", "-q", "-u", "origin", "main", cwd=checkout)
        (checkout / "node_modules" / "pkg").mkdir(parents=True)
        (checkout / "node_modules" / "pkg" / "a.js").write_text("y" * 4096)
        out_dir = cls.tmp / "out"
        out_dir.mkdir()
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "NEXOLAB_OPERATOR": os.environ.get(
            "USER", "runner"), "NEXOLAB_OPERATOR_HOME": str(home), "NEXOLAB_INVENTORY_SCAN_TIMEOUT": "2",
               "DOCKER_LOG": str(cls.tmp / "docker.log")}
        result = subprocess.run(["bash", str(SCRIPT), str(out_dir)], env=env, capture_output=True, text=True,
                                timeout=180)
        assert result.returncode == 0, result.stderr
        reports = list(out_dir.glob("nexolab-storage-inventory-*.txt"))
        assert len(reports) == 1, result.stdout
        text = reports[0].read_text()
        cls.candidates = text[text.index("===== Cleanup candidates"):]
        cls.docker_calls = (cls.tmp / "docker.log").read_text()
        cls.release = release
        cls.checkout = checkout

    @classmethod
    def tearDownClass(cls) -> None:
        subprocess.run(["rm", "-rf", "--one-file-system", str(cls.tmp)], check=False)

    def test_tagged_image_listed_as_dangling_is_protected(self) -> None:
        self.assertIn(f"M4 PROTECTED {TAGGED}  (tagged: nexolab/dashboard:recovery-x-protected-arm64", self.candidates)
        self.assertNotIn(f"docker image rm {TAGGED}", self.candidates)

    def test_container_image_is_protected_and_untagged_image_is_a_candidate(self) -> None:
        self.assertIn(f"M4 PROTECTED {USED}  (used by a container)", self.candidates)
        self.assertIn(f"sudo docker image rm {UNTAGGED}", self.candidates)

    def test_release_folder_node_modules_is_review_not_clean(self) -> None:
        self.assertIn("release/runtime artifact folder, not a cache", self.candidates)
        self.assertNotIn(str(self.release / "node_modules"), self.candidates.split("M5 REVIEW")[0])
        self.assertNotRegex(self.candidates, rf"rm -rf[^\n]*{self.release}")

    def test_pushed_clean_git_checkout_cache_is_a_candidate(self) -> None:
        self.assertIn(f"rm -rf --one-file-system '{self.checkout}/node_modules'", self.candidates)

    def test_inventory_never_mutates_docker(self) -> None:
        for verb in ("rm ", "rmi", "prune", "stop", "kill", "restart", "volume rm", "network rm", "compose"):
            self.assertNotRegex(self.docker_calls, rf"(^|\n)(image |container |volume |network |builder )?{verb}")


if __name__ == "__main__":
    unittest.main()
