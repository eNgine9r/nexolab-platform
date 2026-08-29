from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ADOPTER_SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-adopt-source-deployment.py"
ADOPTER_SPEC = importlib.util.spec_from_file_location(
    "nexolab_adopt_source_deployment", ADOPTER_SCRIPT
)
assert ADOPTER_SPEC and ADOPTER_SPEC.loader
adopter = importlib.util.module_from_spec(ADOPTER_SPEC)
ADOPTER_SPEC.loader.exec_module(adopter)

ORCHESTRATOR_SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-update-orchestrator.py"
ORCHESTRATOR_SPEC = importlib.util.spec_from_file_location(
    "nexolab_update_orchestrator_adoption", ORCHESTRATOR_SCRIPT
)
assert ORCHESTRATOR_SPEC and ORCHESTRATOR_SPEC.loader
orchestrator = importlib.util.module_from_spec(ORCHESTRATOR_SPEC)
ORCHESTRATOR_SPEC.loader.exec_module(orchestrator)


def make_deployment_fixture(
    tmp_path: Path,
    *,
    commit: str = "a" * 40,
    evidence_commit: str | None = None,
    auth_mode: str = "jwt",
    requested_source_ref: str | None = None,
    control_origin_main: str | None = None,
    expected_deployed_source: str | None = None,
) -> tuple[Path, Path, Path, argparse.Namespace]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / "runtime").mkdir()
    (repo / "runtime" / "runtime-mode").write_text("lan\n", encoding="utf-8")
    evidence = repo / "runtime" / "deployments" / "20260818T131726Z"
    evidence.mkdir(parents=True)
    (evidence / "summary.txt").write_text("DEPLOYMENT PASSED\n", encoding="utf-8")
    final_state_lines = [
        "deployed_at=2026-08-18T16:22:48+03:00",
        f"commit={evidence_commit or commit}",
        "runtime_mode=lan",
        "dashboard=http://172.18.48.34:3000",
        "api=http://172.18.48.34:8082",
        f"auth_mode={auth_mode}",
        "local_auth_overlay=true",
        "dashboard_auth_provider=local",
    ]
    if requested_source_ref is not None:
        final_state_lines.append(f"requested_source_ref={requested_source_ref}")
    if control_origin_main is not None:
        final_state_lines.append(f"control_origin_main={control_origin_main}")
    if expected_deployed_source is not None:
        final_state_lines.append(f"expected_deployed_source={expected_deployed_source}")
    (evidence / "final-state.txt").write_text(
        "\n".join(final_state_lines) + "\n",
        encoding="utf-8",
    )
    root = tmp_path / "versions"
    args = argparse.Namespace(root=root, repo=repo, evidence_dir=evidence)
    return repo, root, evidence, args


def install_verified_runtime_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    commit: str,
    origin_commit: str | None = None,
    health: str = "degraded",
) -> None:
    origin = origin_commit or commit

    def fake_git(_repo: Path, *arguments: str) -> str:
        table = {
            ("remote", "get-url", "origin"): "git@github.com:eNgine9r/nexolab-platform.git",
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("status", "--porcelain", "--untracked-files=no"): "",
            ("rev-parse", "HEAD"): commit,
            ("rev-parse", "origin/main"): origin,
            ("merge-base", "--is-ancestor", commit, origin): "",
            ("cat-file", "-e", f"{commit}^{{commit}}"): "",
            ("show", "-s", "--format=%cI", commit): "2026-08-18T13:07:32+00:00",
        }
        return table[arguments]

    monkeypatch.setattr(adopter, "git", fake_git)
    monkeypatch.setattr(adopter, "repository_schema_head", lambda _repo, _commit=None: "20260818_0026")
    monkeypatch.setattr(adopter, "verify_live_schema", lambda _head: None)
    monkeypatch.setattr(adopter, "verify_live_runtime", lambda _url: health)
    monkeypatch.setattr(adopter, "host_platform", lambda: "linux/arm64")


def test_adoption_records_exact_source_lineage_without_package_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    repo, root, _, args = make_deployment_fixture(tmp_path, commit=commit)
    install_verified_runtime_mocks(monkeypatch, commit=commit)

    result = adopter.adopt(args)

    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert result["status"] == "recorded"
    assert result["source_commit"] == commit
    assert result["known_packaged_release"] is False
    assert current["source_commit"] == commit
    assert current["deployment_authority"] == "controlled_source_deployment"
    assert current["known_packaged_release"] is False
    assert current["bundle_id"] == f"source-main-{commit[:12]}"
    assert current["runtime_state_known"] is True
    assert current["health"] == "degraded"
    assert current["source_deployment_evidence"] == "runtime/deployments/20260818T131726Z"
    assert current["source_dashboard_origin"] == "http://172.18.48.34:3000"
    assert current["source_auth_mode"] == "jwt"
    assert current["source_local_auth_overlay"] is True
    assert current["source_dashboard_auth_provider"] == "local"
    assert not (root / "catalog").exists()

    assert orchestrator.current_source_commit(root) == commit
    bundle_id, reason = orchestrator.validated_candidate_bundle(root, "b" * 40)
    assert bundle_id is None
    assert reason == "current_release_unverified"

    def discovery_git(_repo: Path, *arguments: str, **_: object) -> str:
        table = {
            ("remote", "get-url", "origin"): "git@github.com:eNgine9r/nexolab-platform.git",
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("status", "--porcelain", "--untracked-files=no"): "",
            ("rev-parse", "origin/main"): commit,
        }
        return table[arguments]

    monkeypatch.setattr(orchestrator, "git", discovery_git)
    discovery = orchestrator.discover(root, repo, actor="administrator", fetch_remote=False)
    assert discovery["status"] == "completed"
    assert discovery["result_code"] == "up_to_date"
    assert discovery["current_commit"] == commit
    assert discovery["target_commit"] == commit
    assert discovery["activation_eligible"] is False


def test_adoption_accepts_deployed_commit_that_is_ancestor_of_newer_origin_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    newer = "b" * 40
    _, root, _, args = make_deployment_fixture(tmp_path, commit=commit)
    install_verified_runtime_mocks(
        monkeypatch,
        commit=commit,
        origin_commit=newer,
        health="ready",
    )

    result = adopter.adopt(args)

    assert result["status"] == "recorded"
    assert result["source_commit"] == commit
    assert json.loads((root / "current.json").read_text(encoding="utf-8"))[
        "source_commit"
    ] == commit


def test_adoption_refuses_unbound_historical_deployment_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    _, root, _, args = make_deployment_fixture(
        tmp_path,
        commit=commit,
        evidence_commit="b" * 40,
    )
    install_verified_runtime_mocks(monkeypatch, commit=commit)

    with pytest.raises(adopter.AdoptionFailure, match="not bound to its requested source commit"):
        adopter.adopt(args)

    assert not (root / "current.json").exists()


def test_historical_adoption_uses_evidence_commit_while_checkout_stays_control_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "a" * 40
    previous = "9" * 40
    control = "b" * 40
    origin = "c" * 40
    repo, root, _, args = make_deployment_fixture(
        tmp_path,
        commit=control,
        evidence_commit=source,
        requested_source_ref=source,
        control_origin_main=control,
        expected_deployed_source=previous,
    )

    def fake_git(_repo: Path, *arguments: str) -> str:
        table = {
            ("remote", "get-url", "origin"): "git@github.com:eNgine9r/nexolab-platform.git",
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("status", "--porcelain", "--untracked-files=no"): "",
            ("rev-parse", "HEAD"): control,
            ("rev-parse", "origin/main"): origin,
            ("merge-base", "--is-ancestor", control, origin): "",
            ("cat-file", "-e", f"{source}^{{commit}}"): "",
            ("cat-file", "-e", f"{control}^{{commit}}"): "",
            ("merge-base", "--is-ancestor", previous, source): "",
            ("merge-base", "--is-ancestor", source, control): "",
            ("merge-base", "--is-ancestor", control, control): "",
            ("merge-base", "--is-ancestor", source, origin): "",
            ("show", "-s", "--format=%cI", source): "2026-08-27T14:10:00+00:00",
        }
        return table[arguments]

    schema_calls: list[str] = []
    verified_heads: list[str] = []
    monkeypatch.setattr(adopter, "git", fake_git)
    monkeypatch.setattr(
        adopter,
        "repository_schema_head",
        lambda _repo, source_commit=None: schema_calls.append(source_commit) or "20260820_0026",
    )
    monkeypatch.setattr(adopter, "verify_live_schema", verified_heads.append)
    monkeypatch.setattr(adopter, "verify_live_runtime", lambda _url: "ready")
    monkeypatch.setattr(adopter, "host_platform", lambda: "linux/arm64")

    result = adopter.adopt(args)
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))

    assert result["status"] == "recorded"
    assert result["source_commit"] == source
    assert result["schema_head"] == "20260820_0026"
    assert schema_calls == [source]
    assert verified_heads == ["20260820_0026"]
    assert current["source_commit"] == source
    assert current["source_historical_main"] is True
    assert current["source_control_checkout_commit"] == control
    assert current["source_control_origin_main"] == origin
    assert current["source_deployment_control_main"] == control
    assert current["bundle_id"] == f"source-main-{source[:12]}"


def test_repository_schema_head_reads_migrations_from_exact_source_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "d" * 40
    migration_root = "services/telemetry-service/migrations/versions"
    first = f"{migration_root}/001_first.py"
    second = f"{migration_root}/002_second.py"

    def fake_git(_repo: Path, *arguments: str) -> str:
        table = {
            ("ls-tree", "-r", "--name-only", commit, "--", migration_root): f"{first}\n{second}",
            ("show", f"{commit}:{first}"): 'revision = "001"\ndown_revision = None\n',
            ("show", f"{commit}:{second}"): 'revision = "002"\ndown_revision = "001"\n',
        }
        return table[arguments]

    monkeypatch.setattr(adopter, "git", fake_git)
    assert adopter.repository_schema_head(tmp_path, commit) == "002"


def test_historical_adoption_refuses_evidence_control_main_outside_checkout_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "a" * 40
    previous = "9" * 40
    control = "b" * 40
    checkout = "c" * 40
    origin = "d" * 40
    _, root, _, args = make_deployment_fixture(
        tmp_path,
        commit=checkout,
        evidence_commit=source,
        requested_source_ref=source,
        control_origin_main=control,
        expected_deployed_source=previous,
    )

    def fake_git(_repo: Path, *arguments: str) -> str:
        if arguments == ("merge-base", "--is-ancestor", control, checkout):
            raise adopter.AdoptionFailure("command failed safely: control main is not an ancestor")
        table = {
            ("remote", "get-url", "origin"): "git@github.com:eNgine9r/nexolab-platform.git",
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("status", "--porcelain", "--untracked-files=no"): "",
            ("rev-parse", "HEAD"): checkout,
            ("rev-parse", "origin/main"): origin,
            ("merge-base", "--is-ancestor", checkout, origin): "",
            ("cat-file", "-e", f"{source}^{{commit}}"): "",
            ("cat-file", "-e", f"{control}^{{commit}}"): "",
            ("merge-base", "--is-ancestor", previous, source): "",
            ("merge-base", "--is-ancestor", source, control): "",
        }
        return table[arguments]

    monkeypatch.setattr(adopter, "git", fake_git)
    with pytest.raises(adopter.AdoptionFailure, match="control main is not an ancestor"):
        adopter.adopt(args)
    assert not (root / "current.json").exists()


def test_adoption_refuses_disabled_auth_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    _, root, _, args = make_deployment_fixture(tmp_path, commit=commit, auth_mode="disabled")
    install_verified_runtime_mocks(monkeypatch, commit=commit)

    with pytest.raises(adopter.AdoptionFailure, match="AUTH_MODE=disabled"):
        adopter.adopt(args)

    assert not (root / "current.json").exists()


def test_adoption_never_replaces_existing_packaged_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    _, root, _, args = make_deployment_fixture(tmp_path, commit=commit)
    root.mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps(
            {
                "bundle_id": "validated-release-1",
                "source_commit": commit,
                "deployment_authority": "validated_package",
            }
        ),
        encoding="utf-8",
    )
    install_verified_runtime_mocks(monkeypatch, commit=commit)

    with pytest.raises(adopter.AdoptionFailure, match="refusing to replace"):
        adopter.adopt(args)

    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert current["bundle_id"] == "validated-release-1"


def test_source_adoption_is_idempotent_for_same_verified_deployment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    _, root, _, args = make_deployment_fixture(tmp_path, commit=commit)
    install_verified_runtime_mocks(monkeypatch, commit=commit)

    first = adopter.adopt(args)
    second = adopter.adopt(args)

    assert first["status"] == "recorded"
    assert second["status"] == "already_recorded"
    assert second["source_commit"] == commit
