"""Tests for the GitHub -> GitLab fast-forward synchronization (#1713).

Runs the real synchronization against local bare repositories: no network,
no credentials. Covers every decision path, the askpass helper and static
guarantees (no force, mirror, delete or prune).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC_DIR = ROOT / "docs" / "operations" / "gitlab-sync"
SPEC = importlib.util.spec_from_file_location("nexolab_gitlab_sync", SYNC_DIR / "nexolab-gitlab-sync.py")
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SYNC
SPEC.loader.exec_module(SYNC)
ASKPASS = SYNC_DIR / "nexolab-gitlab-sync-askpass.sh"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "source.git"
        self.dest = root / "dest.git"
        self.work = root / "work"
        self.state = root / "state"
        git("init", "--quiet", "--bare", "--initial-branch=main", str(self.source))
        git("init", "--quiet", "--initial-branch=main", str(self.work))
        self.commit("c1")
        git("push", "--quiet", str(self.source), "main", cwd=self.work)
        git("clone", "--quiet", "--bare", str(self.source), str(self.dest))
        # Behave like GitLab: accept push options and record them for assertions.
        git("--git-dir", str(self.dest), "config", "receive.advertisePushOptions", "true")
        hook = self.dest / "hooks" / "pre-receive"
        hook.write_text(
            "#!/bin/sh\ni=0\nwhile [ $i -lt \"${GIT_PUSH_OPTION_COUNT:-0}\" ]; do\n"
            "  eval echo \"\\$GIT_PUSH_OPTION_$i\" >> \"$GIT_DIR/push-options.log\"\n"
            "  i=$((i + 1))\ndone\ncat >/dev/null\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

    def commit(self, name: str) -> str:
        (self.work / name).write_text(name, encoding="utf-8")
        git("add", name, cwd=self.work)
        git("commit", "--quiet", "-m", name, cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work)

    def push_source(self) -> None:
        git("push", "--quiet", str(self.source), "main", cwd=self.work)

    def sha(self, repo: Path, ref: str = "refs/heads/main") -> str:
        return git("--git-dir", str(repo), "rev-parse", ref)

    def config(self, **overrides: object) -> object:
        values = dict(
            source_url=self.source.as_uri(),
            dest_url=self.dest.as_uri(),
            state_dir=self.state,
            mode="push",
            min_free_gib=0,
            min_host_available_mib=0,
        )
        values.update(overrides)
        return SYNC.Config(**values)

    def run(self, **overrides: object) -> tuple[int, object]:
        return SYNC.run(self.config(**overrides), allow_local=True)


class GitLabSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_equal_histories_are_up_to_date_without_push(self) -> None:
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_OK)
        self.assertEqual(report.relation, "equal")
        self.assertEqual(report.result, "up_to_date")
        self.assertEqual(report.pushed, [])

    def test_fast_forward_is_pushed_and_verified(self) -> None:
        new = self.fx.commit("c2")
        self.fx.push_source()
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_OK)
        self.assertEqual(report.relation, "fast_forward")
        self.assertEqual(report.pushed, ["main"])
        self.assertEqual(report.destination_sha_after, new)
        self.assertEqual(self.fx.sha(self.fx.dest), new)
        status = json.loads((self.fx.state / "last-status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["source_sha"], new)
        options = (self.fx.dest / "push-options.log").read_text(encoding="utf-8").split()
        self.assertEqual(options, ["ci.skip"], "pushes must not start GitLab pipelines")

    def test_ci_skip_can_be_disabled_after_review(self) -> None:
        self.fx.commit("c2")
        self.fx.push_source()
        code, _report = self.fx.run(ci_skip=False)
        self.assertEqual(code, SYNC.EXIT_OK)
        self.assertFalse((self.fx.dest / "push-options.log").exists())

    def test_check_mode_reports_but_never_pushes(self) -> None:
        before = self.fx.sha(self.fx.dest)
        self.fx.commit("c2")
        self.fx.push_source()
        code, report = self.fx.run(mode="check")
        self.assertEqual(code, SYNC.EXIT_OK)
        self.assertEqual(report.result, "check_ok")
        self.assertEqual(report.relation, "fast_forward")
        self.assertEqual(report.ahead_source, 1)
        self.assertEqual(self.fx.sha(self.fx.dest), before)

    def _destination_only_commit(self) -> str:
        clone = self.fx.root / "gitlab-work"
        git("clone", "--quiet", str(self.fx.dest), str(clone))
        (clone / "gitlab-only").write_text("x", encoding="utf-8")
        git("add", "gitlab-only", cwd=clone)
        git("commit", "--quiet", "-m", "gitlab only", cwd=clone)
        git("push", "--quiet", "origin", "main", cwd=clone)
        return git("rev-parse", "HEAD", cwd=clone)

    def test_destination_ahead_fails_closed_and_keeps_gitlab_commit(self) -> None:
        gitlab_only = self._destination_only_commit()
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_DIVERGED)
        self.assertEqual(report.reason, "main_destination_ahead")
        self.assertEqual(self.fx.sha(self.fx.dest), gitlab_only)
        self.assertFalse((self.fx.state / "last-status.json").exists())
        failure = json.loads((self.fx.state / "last-failure.json").read_text(encoding="utf-8"))
        self.assertEqual(failure["reason"], "main_destination_ahead")

    def test_diverged_histories_fail_closed_without_write(self) -> None:
        gitlab_only = self._destination_only_commit()
        self.fx.commit("c2")
        self.fx.push_source()
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_DIVERGED)
        self.assertEqual(report.reason, "main_diverged")
        self.assertEqual((report.ahead_source, report.ahead_destination), (1, 1))
        self.assertEqual(self.fx.sha(self.fx.dest), gitlab_only)

    def test_rewritten_source_history_fails_closed(self) -> None:
        self.fx.commit("c2")
        self.fx.push_source()
        self.assertEqual(self.fx.run()[0], SYNC.EXIT_OK)
        synced = self.fx.sha(self.fx.dest)
        git("reset", "--quiet", "--hard", "HEAD~1", cwd=self.fx.work)
        self.fx.commit("c2-rewritten")
        git("push", "--quiet", "--force", str(self.fx.source), "main", cwd=self.fx.work)
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_DIVERGED)
        self.assertEqual(report.reason, "source_history_rewritten")
        self.assertEqual(self.fx.sha(self.fx.dest), synced)

    def test_missing_destination_main_is_not_created(self) -> None:
        git("--git-dir", str(self.fx.dest), "update-ref", "-d", "refs/heads/main")
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_DIVERGED)
        self.assertEqual(report.reason, "destination_main_missing")

    def test_disk_reserve_blocks_before_any_network_or_write(self) -> None:
        self.fx.commit("c2")
        self.fx.push_source()
        before = self.fx.sha(self.fx.dest)
        code, report = self.fx.run(min_free_gib=10**9)
        self.assertEqual(code, SYNC.EXIT_RESOURCE)
        self.assertEqual(report.reason, "free_disk_below_reserve")
        self.assertIsNone(report.source_sha)
        self.assertEqual(self.fx.sha(self.fx.dest), before)

    def test_only_explicitly_approved_tags_are_pushed(self) -> None:
        git("tag", "-a", "v1.0.0", "-m", "release", cwd=self.fx.work)
        git("tag", "unapproved", cwd=self.fx.work)
        git("push", "--quiet", str(self.fx.source), "--tags", cwd=self.fx.work)
        code, report = self.fx.run(approved_tags=("v1.0.0",))
        self.assertEqual(code, SYNC.EXIT_OK)
        self.assertEqual(report.pushed, ["tag:v1.0.0"])
        tags = git("--git-dir", str(self.fx.dest), "tag", "--list").split()
        self.assertEqual(tags, ["v1.0.0"])
        self.assertEqual(
            self.fx.sha(self.fx.dest, "refs/tags/v1.0.0"), self.fx.sha(self.fx.source, "refs/tags/v1.0.0")
        )
        code, report = self.fx.run(approved_tags=("v1.0.0",))
        self.assertEqual((code, report.tags["v1.0.0"]), (SYNC.EXIT_OK, "present"))

    def test_tag_collision_fails_closed_without_overwrite(self) -> None:
        git("tag", "v2.0.0", cwd=self.fx.work)
        git("push", "--quiet", str(self.fx.source), "v2.0.0", cwd=self.fx.work)
        clone = self.fx.root / "gitlab-tag"
        git("clone", "--quiet", str(self.fx.dest), str(clone))
        git("tag", "-a", "v2.0.0", "-m", "gitlab owned", cwd=clone)
        git("push", "--quiet", "origin", "v2.0.0", cwd=clone)
        before = self.fx.sha(self.fx.dest, "refs/tags/v2.0.0")
        code, report = self.fx.run(approved_tags=("v2.0.0",))
        self.assertEqual(code, SYNC.EXIT_TAG_COLLISION)
        self.assertEqual(report.reason, "tag_collision")
        self.assertEqual(self.fx.sha(self.fx.dest, "refs/tags/v2.0.0"), before)

    def test_concurrent_run_is_skipped(self) -> None:
        self.fx.state.mkdir(parents=True, exist_ok=True)
        with SYNC._Lock(self.fx.state / ".lock") as acquired:
            self.assertTrue(acquired)
            code, report = self.fx.run()
        self.assertEqual((code, report.result), (SYNC.EXIT_OK, "skipped_running"))

    def test_destination_only_branches_are_untouched(self) -> None:
        git("--git-dir", str(self.fx.dest), "update-ref", "refs/heads/gitlab-feature", self.fx.sha(self.fx.dest))
        self.fx.commit("c2")
        self.fx.push_source()
        code, report = self.fx.run()
        self.assertEqual(code, SYNC.EXIT_OK)
        self.assertEqual(report.destination_only_refs, 1)
        self.assertTrue(git("--git-dir", str(self.fx.dest), "rev-parse", "refs/heads/gitlab-feature"))


class ConfigTests(unittest.TestCase):
    def config(self, **overrides: object) -> object:
        values = dict(
            source_url=SYNC.CANONICAL_SOURCE,
            dest_url="https://gitlab.example.invalid/group/project.git",
            state_dir=Path("/nonexistent"),
            askpass="/usr/local/lib/nexolab-gitlab-sync/nexolab-gitlab-sync-askpass.sh",
        )
        values.update(overrides)
        return SYNC.Config(**values)

    def assertRejected(self, reason: str, **overrides: object) -> None:
        with self.assertRaises(SYNC.SyncError) as raised:
            SYNC.validate_config(self.config(**overrides))
        self.assertEqual(raised.exception.reason, reason)

    def test_valid_production_config(self) -> None:
        SYNC.validate_config(self.config())

    def test_rejects_unexpected_source(self) -> None:
        self.assertRejected("unexpected_source", source_url="https://github.com/someone/fork.git")

    def test_rejects_credentials_in_destination_url(self) -> None:
        self.assertRejected(
            "destination_url_contains_credentials",
            dest_url="https://user:secret@gitlab.example.invalid/group/project.git",
        )

    def test_rejects_non_https_destination(self) -> None:
        self.assertRejected("destination_url_not_plain_https", dest_url="http://gitlab.example.invalid/p.git")
        self.assertRejected("destination_url_not_plain_https", dest_url="file:///tmp/dest.git")

    def test_rejects_invalid_mode_and_tags(self) -> None:
        self.assertRejected("invalid_mode", mode="mirror")
        self.assertRejected("invalid_approved_tag", approved_tags=("refs/heads/main",))
        self.assertRejected("invalid_approved_tag", approved_tags=("v1..2",))

    def test_requires_askpass_outside_tests(self) -> None:
        self.assertRejected("askpass_missing", askpass=None)

    def test_redaction_removes_userinfo_and_bounds_length(self) -> None:
        text = SYNC.redact("fatal: https://oauth2:glpat-secret@gitlab.example.invalid/x " + "y" * 1000)
        self.assertNotIn("glpat-secret", text)
        self.assertNotIn("oauth2", text)
        self.assertLessEqual(len(text), SYNC.STDERR_LIMIT)

    def test_environment_defaults_to_check_mode(self) -> None:
        config = SYNC.config_from_environment(
            {"STATE_DIRECTORY": "/var/lib/nexolab-gitlab-sync", "GITLAB_SYNC_DEST_URL": "https://h/p.git"}
        )
        self.assertEqual(config.mode, "check")
        self.assertEqual(config.source_url, SYNC.CANONICAL_SOURCE)
        self.assertEqual(config.min_free_gib, 20)
        self.assertTrue(config.ci_skip)

    def test_approved_tags_file_parsing_and_unreadable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tags = Path(tmp) / "approved-tags"
            tags.write_text("# release tags\nv1.0.0\n\n  v1.1.0  \n", encoding="utf-8")
            self.assertEqual(SYNC._read_tags(str(tags)), ("v1.0.0", "v1.1.0"))
            self.assertEqual(SYNC._read_tags(str(Path(tmp) / "absent")), ())
            with self.assertRaises(SYNC.SyncError) as raised:
                SYNC._read_tags(tmp)  # a directory cannot be read as a file
            self.assertEqual(raised.exception.reason, "approved_tags_unreadable")


class AskpassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.creds = Path(self.tmp.name)
        (self.creds / "gitlab-token").write_text("fake-token-value\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def ask(self, prompt: str, host: str = "gitlab.example.invalid", creds: bool = True) -> tuple[int, str]:
        env = {"PATH": "/usr/bin:/bin", "NEXOLAB_SYNC_DEST_HOST": host}
        if creds:
            env["CREDENTIALS_DIRECTORY"] = str(self.creds)
        result = subprocess.run(["sh", str(ASKPASS), prompt], env=env, capture_output=True, text=True)
        return result.returncode, result.stdout

    def test_answers_only_the_destination_host(self) -> None:
        code, out = self.ask("Password for 'https://nexolab-gitlab-sync@gitlab.example.invalid': ")
        self.assertEqual((code, out), (0, "fake-token-value\n"))
        code, out = self.ask("Username for 'https://gitlab.example.invalid': ")
        self.assertEqual((code, out), (0, "nexolab-gitlab-sync\n"))

    def test_never_answers_other_hosts(self) -> None:
        for prompt in (
            "Password for 'https://github.com': ",
            "Password for 'https://gitlab.example.invalid.evil.example': ",
            "Username for 'https://github.com': ",
            "Password for 'https://gitlab.example.invalid@evil.example': ",
            "Password for 'http://gitlab.example.invalid': ",
            "Password for https://gitlab.example.invalid",
        ):
            code, out = self.ask(prompt)
            self.assertNotEqual(code, 0, prompt)
            self.assertEqual(out, "")

    def test_fails_without_credential_or_host(self) -> None:
        self.assertNotEqual(self.ask("Password for 'https://gitlab.example.invalid': ", creds=False)[0], 0)
        self.assertNotEqual(self.ask("Password for 'https://gitlab.example.invalid': ", host="")[0], 0)


class StaticSafetyTests(unittest.TestCase):
    def test_no_force_mirror_delete_or_prune(self) -> None:
        source = (SYNC_DIR / "nexolab-gitlab-sync.py").read_text(encoding="utf-8")
        for forbidden in ("--force", "--mirror", "--delete", "--prune", "-f\"", "push\", \"+", "--all"):
            self.assertNotIn(forbidden, source, forbidden)
        for push in re.findall(r'git\.run\(\s*"push".*?\)', source, flags=re.S):
            self.assertNotRegex(push, r'f?"\+', push)

    def test_source_commands_never_receive_the_askpass(self) -> None:
        source = (SYNC_DIR / "nexolab-gitlab-sync.py").read_text(encoding="utf-8")
        for call in re.findall(r"git\.run\([^)]*config\.source_url[^)]*\)", source, flags=re.S):
            self.assertNotIn("destination=True", call)

    def test_units_keep_isolation_credential_and_limits(self) -> None:
        service = (SYNC_DIR / "nexolab-gitlab-sync.service").read_text(encoding="utf-8")
        for setting in (
            "DynamicUser=yes",
            "LoadCredential=gitlab-token:/etc/nexolab-gitlab-sync/gitlab-token",
            "LoadCredential=approved-tags:/etc/nexolab-gitlab-sync/approved-tags",
            "GITLAB_SYNC_APPROVED_TAGS_FILE=%d/approved-tags",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "PrivateDevices=yes",
            "MemoryMax=256M",
            "CPUQuota=25%",
            "TasksMax=32",
        ):
            self.assertIn(setting, service)
        self.assertNotIn("ProcSubset=pid", service, "the memory gate reads /proc/meminfo")
        self.assertNotRegex(service, r"glpat|token=", "no secret material in the unit")
        timer = (SYNC_DIR / "nexolab-gitlab-sync.timer").read_text(encoding="utf-8")
        self.assertIn("OnUnitInactiveSec=5min", timer)
        self.assertIn("OnBootSec=10min", timer)

    def test_only_public_or_placeholder_hosts_in_public_files(self) -> None:
        # The corporate destination lives only in the owner's sync.env, never in this public repository.
        for path in [*SYNC_DIR.iterdir(), ROOT / "docs" / "operations" / "gitlab-sync.md"]:
            if not path.is_file():
                continue
            for host in re.findall(r"https?://([A-Za-z0-9][^/\s'\"`)]*)", path.read_text(encoding="utf-8")):
                host = host.rsplit("@", 1)[-1].lower()
                self.assertTrue(host == "github.com" or host.endswith(".invalid") or host == "h", f"{path.name}: {host}")


if __name__ == "__main__":
    unittest.main()
