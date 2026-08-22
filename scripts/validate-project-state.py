#!/usr/bin/env python3
"""Validate canonical NEXOLAB State Model v2 without third-party dependencies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / ".project" / "ACTIVE_SPRINT.json"
CHECKPOINT = ROOT / ".project" / "LAST_CHECKPOINT.json"
CURRENT = ROOT / ".project" / "CURRENT_STATE.md"
BLOCKERS = ROOT / ".project" / "BLOCKERS.md"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_LIFECYCLES = {
    "queued",
    "ready",
    "in_progress",
    "review",
    "completed",
    "blocked",
    "needs_validation",
    "hardware_validation",
}
ACTIVE_LIFECYCLES = {"in_progress", "review"}
FORBIDDEN_DURABLE_KEYS = {
    "repository_main_sha",
    "last_reconciled_repository_sha",
    "repository_product_baseline_sha",
    "runtime_repository_sha",
    "deployed_repository_sha",
    "main_head_sha",
    "merge_sha",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def _require_identity(document: dict[str, Any], path: Path) -> None:
    if document.get("schema_version") != 2:
        raise ValueError(f"{path}: schema_version must be 2")
    if document.get("project") != "NEXOLAB":
        raise ValueError(f"{path}: project must be NEXOLAB")
    if document.get("profile") != "LOCAL_LAN":
        raise ValueError(f"{path}: profile must be LOCAL_LAN")


def _require_sha(value: object, label: str) -> None:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"{label}: expected lowercase 40-character git SHA")


def _is_volatile_key(key: str) -> bool:
    lowered = key.lower()
    return key in FORBIDDEN_DURABLE_KEYS or "merge_sha" in lowered or lowered in {
        "main_sha",
        "main_head",
        "current_main_sha",
        "current_main_head_sha",
    }


def _reject_volatile_invariants(value: object, path: str = "$") -> None:
    """Volatile GitHub facts may exist only inside explicit observation records."""
    if isinstance(value, dict):
        if path.endswith(".observations") or ".observations[" in path:
            return
        for key, child in value.items():
            if _is_volatile_key(key):
                raise ValueError(
                    f"{path}.{key}: volatile GitHub/repository observation cannot be a durable invariant"
                )
            _reject_volatile_invariants(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_volatile_invariants(child, f"{path}[{index}]")


def _validate_baselines(document: dict[str, Any], path: Path) -> None:
    baselines = document.get("baselines")
    if not isinstance(baselines, dict):
        raise ValueError(f"{path}: baselines must be an object")
    _require_sha(baselines.get("accepted_product_sha"), f"{path}: accepted_product_sha")
    _require_sha(baselines.get("deployed_product_sha"), f"{path}: deployed_product_sha")


def _validate_safety(document: dict[str, Any], path: Path) -> None:
    safety = document.get("safety")
    if not isinstance(safety, dict):
        raise ValueError(f"{path}: safety must be an object")
    if safety.get("modbus_write") != "none" or safety.get("hardware_write") != "none":
        raise ValueError(f"{path}: Modbus/hardware write boundary must remain none")
    if safety.get("production_cutover_authorized") is not False:
        raise ValueError(f"{path}: production cutover must remain unauthorized in repository state")


def _validate_observations(document: dict[str, Any], path: Path) -> None:
    observations = document.get("observations", [])
    if not isinstance(observations, list):
        raise ValueError(f"{path}: observations must be a list")
    for index, observation in enumerate(observations):
        label = f"{path}: observations[{index}]"
        if not isinstance(observation, dict):
            raise ValueError(f"{label} must be an object")
        if observation.get("source") != "github":
            raise ValueError(f"{label}: source must be github")
        if not isinstance(observation.get("observed_at"), str) or not observation["observed_at"]:
            raise ValueError(f"{label}: observed_at is required")
        if not isinstance(observation.get("kind"), str) or not observation["kind"]:
            raise ValueError(f"{label}: kind is required")
        if not isinstance(observation.get("data"), dict):
            raise ValueError(f"{label}: data must be an object")


def validate_active(document: dict[str, Any]) -> None:
    _require_identity(document, ACTIVE)
    _reject_volatile_invariants(document)
    _validate_baselines(document, ACTIVE)
    _validate_safety(document, ACTIVE)
    _validate_observations(document, ACTIVE)

    sprint = document.get("sprint")
    if not isinstance(sprint, dict) or not sprint.get("id") or not sprint.get("status"):
        raise ValueError(f"{ACTIVE}: sprint id/status are required")

    policy = document.get("execution_policy")
    if not isinstance(policy, dict):
        raise ValueError(f"{ACTIVE}: execution_policy must be an object")
    if policy.get("verification_policy") != "proportional_to_changed_product_surface":
        raise ValueError(
            f"{ACTIVE}: verification policy must remain proportional to changed product surface"
        )

    work_packages = document.get("work_packages")
    if not isinstance(work_packages, list):
        raise ValueError(f"{ACTIVE}: work_packages must be a list")

    issues: list[int] = []
    by_issue: dict[int, dict[str, Any]] = {}
    for index, work_package in enumerate(work_packages):
        label = f"{ACTIVE}: work_packages[{index}]"
        if not isinstance(work_package, dict) or not isinstance(work_package.get("issue"), int):
            raise ValueError(f"{label}: integer issue is required")
        if not isinstance(work_package.get("title"), str) or not work_package["title"]:
            raise ValueError(f"{label}: title is required")
        lifecycle = work_package.get("lifecycle")
        if lifecycle not in ALLOWED_LIFECYCLES:
            raise ValueError(f"{label}: unsupported lifecycle {lifecycle!r}")
        issue = work_package["issue"]
        issues.append(issue)
        by_issue[issue] = work_package

        evidence = work_package.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError(f"{label}: evidence must be an object")
        for key in ("verified_head_sha", "hardware_evidence_sha"):
            if key in evidence and evidence[key] is not None:
                _require_sha(evidence[key], f"{label}.{key}")
        checks = evidence.get("checks", {})
        if not isinstance(checks, dict):
            raise ValueError(f"{label}: evidence.checks must be an object")
        depends_on = work_package.get("depends_on", [])
        if not isinstance(depends_on, list) or any(not isinstance(value, int) for value in depends_on):
            raise ValueError(f"{label}: depends_on must be a list of integer Issue numbers")

    if len(issues) != len(set(issues)):
        raise ValueError(f"{ACTIVE}: duplicate issue entries are forbidden")

    for work_package in work_packages:
        issue = work_package["issue"]
        for dependency in work_package.get("depends_on", []):
            if dependency == issue or dependency not in by_issue:
                raise ValueError(f"{ACTIVE}: Issue {issue} has invalid dependency {dependency}")

    selection = document.get("selection")
    if not isinstance(selection, dict):
        raise ValueError(f"{ACTIVE}: selection must be an object")
    active = selection.get("active_work_package")
    if active is not None:
        if not isinstance(active, dict) or not isinstance(active.get("issue"), int):
            raise ValueError(f"{ACTIVE}: active_work_package must contain integer issue")
        issue = active["issue"]
        if issue not in by_issue:
            raise ValueError(f"{ACTIVE}: active issue {issue} is absent from work_packages")
        if by_issue[issue].get("lifecycle") not in ACTIVE_LIFECYCLES:
            raise ValueError(
                f"{ACTIVE}: active issue {issue} must have lifecycle in_progress or review"
            )
    next_work = selection.get("next_work_package")
    if next_work is not None:
        if not isinstance(next_work, dict) or not isinstance(next_work.get("issue"), int):
            raise ValueError(f"{ACTIVE}: next_work_package must contain integer issue")
        if next_work["issue"] not in by_issue:
            raise ValueError(
                f"{ACTIVE}: next issue {next_work['issue']} is absent from work_packages"
            )

    maintenance = document.get("maintenance_actions")
    if not isinstance(maintenance, list):
        raise ValueError(f"{ACTIVE}: maintenance_actions must be a list")


def validate_checkpoint(document: dict[str, Any]) -> None:
    _require_identity(document, CHECKPOINT)
    _reject_volatile_invariants(document)
    _validate_baselines(document, CHECKPOINT)
    _validate_safety(document, CHECKPOINT)
    _validate_observations(document, CHECKPOINT)

    if not isinstance(document.get("timestamp"), str) or not document["timestamp"]:
        raise ValueError(f"{CHECKPOINT}: timestamp is required")
    if not isinstance(document.get("event"), str) or not document["event"]:
        raise ValueError(f"{CHECKPOINT}: event is required")
    if not isinstance(document.get("next_action"), str) or not document["next_action"]:
        raise ValueError(f"{CHECKPOINT}: next_action is required")

    active = document.get("active_work")
    if active is not None:
        if not isinstance(active, dict) or not isinstance(active.get("issue"), int):
            raise ValueError(f"{CHECKPOINT}: active_work must contain integer issue")


def validate_markdown(path: Path, required_heading: str) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        raise ValueError(f"{path}: final newline is required")
    if required_heading not in text:
        raise ValueError(f"{path}: missing required heading {required_heading!r}")


def validate_canonical_json(path: Path) -> None:
    document = load_json(path)
    canonical = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    actual = path.read_text(encoding="utf-8")
    if actual != canonical:
        raise ValueError(f"{path}: JSON is not in canonical two-space format")


def validate_repository(root: Path = ROOT) -> None:
    active_path = root / ".project" / "ACTIVE_SPRINT.json"
    checkpoint_path = root / ".project" / "LAST_CHECKPOINT.json"
    current_path = root / ".project" / "CURRENT_STATE.md"
    blockers_path = root / ".project" / "BLOCKERS.md"

    active = load_json(active_path)
    checkpoint = load_json(checkpoint_path)
    validate_active(active)
    validate_checkpoint(checkpoint)
    validate_canonical_json(active_path)
    validate_canonical_json(checkpoint_path)
    validate_markdown(current_path, "# NEXOLAB Current State")
    validate_markdown(blockers_path, "# NEXOLAB Blockers")


def main() -> int:
    validate_repository(ROOT)
    print("NEXOLAB State Model v2 integrity validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
