#!/usr/bin/env python3
"""Validate the canonical NEXOLAB repository state without Node dependencies."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / ".project" / "ACTIVE_SPRINT.json"
CHECKPOINT = ROOT / ".project" / "LAST_CHECKPOINT.json"
CURRENT = ROOT / ".project" / "CURRENT_STATE.md"
BLOCKERS = ROOT / ".project" / "BLOCKERS.md"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def validate_identity(document: dict, path: Path) -> None:
    if document.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")
    if document.get("project") != "NEXOLAB":
        raise ValueError(f"{path}: project must be NEXOLAB")
    if document.get("profile") != "LOCAL_LAN":
        raise ValueError(f"{path}: profile must be LOCAL_LAN")


def validate_active(document: dict) -> None:
    validate_identity(document, ACTIVE)
    sprint = document.get("sprint")
    if not isinstance(sprint, dict) or not sprint.get("id") or not sprint.get("status"):
        raise ValueError(f"{ACTIVE}: sprint id/status are required")
    tasks = document.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"{ACTIVE}: tasks must be a list")
    issues: list[int] = []
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("issue"), int):
            raise ValueError(f"{ACTIVE}: every task must have an integer issue")
        issues.append(task["issue"])
    if len(issues) != len(set(issues)):
        raise ValueError(f"{ACTIVE}: duplicate issue entries are forbidden")
    policy = document.get("execution_policy")
    if not isinstance(policy, dict):
        raise ValueError(f"{ACTIVE}: execution_policy must be an object")
    if policy.get("verification_policy") != "proportional_to_changed_product_surface":
        raise ValueError(f"{ACTIVE}: verification policy must remain proportional to changed product surface")


def validate_checkpoint(document: dict) -> None:
    validate_identity(document, CHECKPOINT)
    if not document.get("timestamp"):
        raise ValueError(f"{CHECKPOINT}: timestamp is required")
    if not document.get("event"):
        raise ValueError(f"{CHECKPOINT}: event is required")
    safety = document.get("safety")
    if not isinstance(safety, dict):
        raise ValueError(f"{CHECKPOINT}: safety must be an object")
    if safety.get("modbus_write") != "none" or safety.get("hardware_write") != "none":
        raise ValueError(f"{CHECKPOINT}: Modbus/hardware write boundary must remain none")


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


def main() -> int:
    active = load_json(ACTIVE)
    checkpoint = load_json(CHECKPOINT)
    validate_active(active)
    validate_checkpoint(checkpoint)
    validate_canonical_json(ACTIVE)
    validate_canonical_json(CHECKPOINT)
    validate_markdown(CURRENT, "# NEXOLAB Current State")
    validate_markdown(BLOCKERS, "# NEXOLAB Blockers")
    print("NEXOLAB project-state integrity validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
