from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-version-manager.py"
SPEC = importlib.util.spec_from_file_location("nexolab_version_manager_runtime", SCRIPT)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


def test_package_worker_rejects_unsynchronized_protected_frontend_before_mutation(tmp_path, monkeypatch):
    unit = tmp_path / "nexolab-external-frontend.service"
    monkeypatch.setattr(manager, "PROTECTED_FRONTEND_UNIT", unit)
    manager.require_supported_frontend_topology()
    unit.write_text("[Service]\nWorkingDirectory=/old-external-release\n")
    with pytest.raises(manager.VersionManagerFailure, match="protected_frontend_package_required"):
        manager.require_supported_frontend_topology()
    manager.require_supported_frontend_topology({"external_frontend": {"profile": "google_https"}})


def health_payload(
    *,
    expected: int = 1,
    active: int = 1,
    workers_healthy: bool = True,
    last_attempt_at: str | None = "2026-08-18T10:00:00+00:00",
) -> dict[str, object]:
    return {
        "status": "ok",
        "acquisition": {
            "scheduler": {
                "expected_bus_workers": expected,
                "active_bus_workers": active,
                "workers_healthy": workers_healthy,
            }
        },
        "latest_values": {
            "last_attempt_at": last_attempt_at,
            "last_success_at": last_attempt_at,
        },
    }


def test_device_agent_facts_require_exact_worker_health() -> None:
    expected, active, workers_healthy, last_attempt = manager._device_agent_facts(
        health_payload()
    )

    assert (expected, active, workers_healthy) == (1, 1, True)
    assert last_attempt == "2026-08-18T10:00:00+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        health_payload(expected=1, active=0, workers_healthy=False),
        health_payload(expected=2, active=1, workers_healthy=False),
        {**health_payload(), "status": "error"},
    ],
)
def test_device_agent_facts_fail_closed_on_unhealthy_runtime(payload: dict[str, object]) -> None:
    with pytest.raises(manager.VersionManagerFailure):
        manager._device_agent_facts(payload)


def test_verify_device_agent_progress_requires_timestamp_advance(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = iter(
        [
            health_payload(last_attempt_at="2026-08-18T10:00:00+00:00"),
            health_payload(last_attempt_at="2026-08-18T10:00:03+00:00"),
        ]
    )
    clock = {"value": 0.0}
    monkeypatch.setattr(manager, "read_local_json", lambda _url: next(samples))
    monkeypatch.setattr(manager.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        manager.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + seconds),
    )

    result = manager.verify_device_agent_progress(observation_seconds=10, poll_seconds=3)

    assert result == {
        "status": "verified",
        "expected_bus_workers": 1,
        "active_bus_workers": 1,
        "workers_healthy": True,
        "baseline_last_attempt_at": "2026-08-18T10:00:00+00:00",
        "advanced_last_attempt_at": "2026-08-18T10:00:03+00:00",
    }


def test_verify_device_agent_progress_fails_when_telemetry_does_not_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"value": 0.0}
    monkeypatch.setattr(
        manager,
        "read_local_json",
        lambda _url: health_payload(last_attempt_at="2026-08-18T10:00:00+00:00"),
    )
    monkeypatch.setattr(manager.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        manager.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + seconds),
    )

    with pytest.raises(manager.VersionManagerFailure, match="telemetry did not advance"):
        manager.verify_device_agent_progress(observation_seconds=5, poll_seconds=2)


UNIT = Path(__file__).resolve().parents[2] / "infrastructure/offline/nexolab-version-manager.service"


def git(repository: Path, *arguments: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def graph(tmp_path: Path):
    environment = {"PATH": os.environ.get("PATH", os.defpath)}
    global_config = tmp_path / "global.conf"
    global_config.write_text("[safe]\n\tdirectory = *\n")
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(global_config),
        GIT_TERMINAL_PROMPT="0",
    )
    repository = tmp_path / "approved site"
    repository.mkdir()
    assert git(repository, "init", "-q", environment=environment).returncode == 0
    for message in ("ancestor", "target"):
        result = git(
            repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-q", "--allow-empty", "-m", message, environment=environment,
        )
        assert result.returncode == 0, result.stderr
    ancestor = git(repository, "rev-parse", "HEAD~1", environment=environment).stdout.strip()
    target = git(repository, "rev-parse", "HEAD", environment=environment).stdout.strip()
    # Git's own test switch exercises the ownership guard without privileged chown.
    environment["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
    return repository, ancestor, target, environment


def worker_git(configured_repository: Path, repository: Path, ancestor: str, target: str, environment):
    launch = next(line.split("=", 1)[1] for line in UNIT.read_text().splitlines() if line.startswith("ExecStart="))
    arguments = shlex.split(launch)
    # systemd expands ${VAR} after tokenization, retaining spaces in one argument.
    arguments = [argument.replace("${NEXOLAB_REPOSITORY_PATH}", str(configured_repository)) for argument in arguments]
    prefix = arguments[:arguments.index("/usr/bin/python3")]
    # Exercise the launch followed by the manager's actual child environment.
    program = """
import argparse, importlib.util, subprocess, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('worker', sys.argv[1])
worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
environment = worker.package_subprocess_env(argparse.Namespace(local_auth=False, source_repo=Path(sys.argv[2])))
sys.exit(subprocess.run(['git', '-C', sys.argv[3], 'merge-base', '--is-ancestor', sys.argv[4], sys.argv[5]], env=environment).returncode)
"""
    return subprocess.run(
        [*prefix, sys.executable, "-c", program, str(SCRIPT), str(configured_repository), str(repository), ancestor, target],
        env=environment, capture_output=True, text=True, timeout=10,
    )


def test_worker_accepts_real_ancestor_in_exact_foreign_owned_site(graph):
    repository, ancestor, target, environment = graph
    environment = {**environment, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": ""}
    baseline = git(repository, "merge-base", "--is-ancestor", ancestor, target, environment=environment)
    assert baseline.returncode == 128 and "dubious ownership" in baseline.stderr
    result = worker_git(repository, repository, ancestor, target, environment)
    assert result.returncode == 0, result.stderr


def test_worker_canonicalizes_existing_symlinked_site_configuration(graph, tmp_path, monkeypatch):
    repository, ancestor, target, environment = graph
    logical = tmp_path / "logical site"
    logical.symlink_to(repository, target_is_directory=True)
    from argparse import Namespace
    with monkeypatch.context() as patch:
        patch.setattr(manager.os, "environ", environment)
        actual = manager.package_subprocess_env(Namespace(local_auth=False, source_repo=logical))
    assert actual["NEXOLAB_REPO"] == str(repository.resolve())
    assert actual["GIT_CONFIG_VALUE_1"] == actual["NEXOLAB_REPO"]
    result = worker_git(logical, repository, ancestor, target, environment)
    assert result.returncode == 0, result.stderr


def test_worker_rejects_unapproved_repository_despite_inherited_wildcard_and_parameters(graph, tmp_path):
    repository, ancestor, target, environment = graph
    unapproved = tmp_path / "unapproved"
    subprocess.run(["git", "clone", "-q", str(repository), str(unapproved)],
                   env={**environment, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "0"}, check=True, capture_output=True)
    environment.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0="*",
                       GIT_CONFIG_PARAMETERS="'safe.directory=*'", SUDO_UID="0")
    result = worker_git(repository, unapproved, ancestor, target, environment)
    assert result.returncode == 128 and "dubious ownership" in result.stderr


@pytest.mark.parametrize("revision_case", ["reversed", "missing"])
def test_worker_still_rejects_invalid_lineage(graph, revision_case):
    repository, ancestor, target, environment = graph
    if revision_case == "reversed":
        ancestor, target = target, ancestor
    else:
        target = "f" * 40
    result = worker_git(repository, repository, ancestor, target, environment)
    assert result.returncode == (1 if revision_case == "reversed" else 128)
    assert "dubious ownership" not in result.stderr


def test_worker_preserves_filesystem_and_startup_boundaries():
    facts = dict(line.split("=", 1) for line in UNIT.read_text().splitlines() if "=" in line)
    assert facts["ProtectSystem"] == "strict"
    assert facts["ProtectHome"] == "read-only"
    assert facts["PrivateTmp"] == "true"
    assert facts["NoNewPrivileges"] == "true"
    assert facts["ReadWritePaths"].split() == [
        "/var/lib/nexolab/version-management", "/var/backups/nexolab",
        "-/opt/nexolab-external/releases", "-/etc/systemd/system/nexolab-external-frontend.service",
    ]
    assert "NEXOLAB_STARTUP_EVIDENCE_ROOT=/var/backups/nexolab/device-agent-startup" in facts["ExecStart"]
