#!/usr/bin/env python3
"""Deterministic dependency-free mutation and migration tooling for NEXOLAB State Model v2."""

from __future__ import annotations

import argparse
import copy
import difflib
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_REL = Path(".project/ACTIVE_SPRINT.json")
CHECKPOINT_REL = Path(".project/LAST_CHECKPOINT.json")
VALIDATOR_PATH = Path(__file__).with_name("validate-project-state.py")

_SPEC = importlib.util.spec_from_file_location("validate_project_state", VALIDATOR_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load {VALIDATOR_PATH}")
_VALIDATOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VALIDATOR)


def canonical(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def _lifecycle_from_v1(status: object) -> str:
    value = str(status or "").lower()
    if "completed" in value or "green_merged" in value:
        return "completed"
    if "blocked" in value:
        return "blocked"
    if "needs_validation" in value:
        return "needs_validation"
    if "hardware_validation" in value:
        return "hardware_validation"
    if "in_progress" in value or "candidate" in value:
        return "in_progress"
    return "queued"


def _first_sha(task: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = task.get(key)
        if isinstance(value, str) and _VALIDATOR.SHA_RE.fullmatch(value):
            return value
    return None


def _checks_from_v1(task: dict[str, Any]) -> dict[str, str]:
    checks: dict[str, str] = {}
    for key, value in task.items():
        lower = key.lower()
        if (
            key
            in {
                "exact_head_ci",
                "core_ci",
                "external_telemetry_ci",
                "all_exact_head_workflows",
                "review_threads",
                "fresh_codex_review",
                "team_lead_final_review",
                "state_only_fast_lane",
                "stable_merge_gate",
                "external_exact_head_workflow_aggregation",
                "deterministic_npm_ci",
            }
            or lower.endswith("_ci")
            or lower.endswith("_workflows")
        ):
            if isinstance(value, (str, int, float, bool)):
                checks[key] = str(value)
    return checks


def migrate_active_v1(document: dict[str, Any], *, observed_at: str) -> dict[str, Any]:
    if document.get("schema_version") != 1:
        raise ValueError("migrate_active_v1 requires schema_version 1")

    accepted = document.get("accepted_product_sha") or document.get(
        "repository_product_baseline_sha"
    )
    deployed = document.get("deployed_product_sha")
    _VALIDATOR._require_sha(accepted, "v1 accepted product SHA")
    _VALIDATOR._require_sha(deployed, "v1 deployed product SHA")

    work_packages: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    for task in document.get("tasks", []):
        if not isinstance(task, dict) or not isinstance(task.get("issue"), int):
            raise ValueError("v1 task must contain integer issue")
        evidence: dict[str, Any] = {}
        if isinstance(task.get("pull_request"), int):
            evidence["pull_request"] = task["pull_request"]
        verified = _first_sha(task, "final_pr_head_sha", "final_software_head_sha")
        if verified:
            evidence["verified_head_sha"] = verified
        hardware = _first_sha(task, "hardware_accepted_head_sha")
        if hardware:
            evidence["hardware_evidence_sha"] = hardware
        checks = _checks_from_v1(task)
        if checks:
            evidence["checks"] = checks

        item: dict[str, Any] = {
            "issue": task["issue"],
            "title": str(task.get("title") or f"Issue #{task['issue']}"),
            "priority": str(task.get("priority") or "unspecified"),
            "lifecycle": _lifecycle_from_v1(task.get("status")),
            "legacy_status": str(task.get("status") or ""),
            "evidence": evidence,
        }
        if isinstance(task.get("branch"), str):
            item["branch"] = task["branch"]
        work_packages.append(item)

        merge_sha = task.get("merge_sha")
        if isinstance(merge_sha, str) and _VALIDATOR.SHA_RE.fullmatch(merge_sha):
            observations.append(
                {
                    "source": "github",
                    "observed_at": observed_at,
                    "kind": "historical_merge",
                    "data": {"issue": task["issue"], "merge_sha": merge_sha},
                }
            )

    selected_issue = None
    selection_state = document.get("selection_state")
    if isinstance(selection_state, dict) and isinstance(selection_state.get("selected_issue"), int):
        selected_issue = selection_state["selected_issue"]
    active_v1 = document.get("active_work_package")
    if selected_issue is None and isinstance(active_v1, dict) and isinstance(
        active_v1.get("issue"), int
    ):
        selected_issue = active_v1["issue"]

    active = None
    if selected_issue is not None:
        matching = next((item for item in work_packages if item["issue"] == selected_issue), None)
        if matching is not None and matching["lifecycle"] == "in_progress":
            active = {
                "issue": matching["issue"],
                "title": matching["title"],
                "branch": matching.get("branch"),
            }

    result: dict[str, Any] = {
        "schema_version": 2,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": copy.deepcopy(document.get("sprint", {})),
        "execution_policy": copy.deepcopy(document.get("execution_policy", {})),
        "baselines": {
            "accepted_product_sha": accepted,
            "deployed_product_sha": deployed,
        },
        "selection": {
            "active_work_package": active,
            "next_work_package": None,
        },
        "work_packages": work_packages,
        "maintenance_actions": copy.deepcopy(document.get("maintenance_actions", [])),
        "observations": observations,
        "safety": copy.deepcopy(document.get("safety", {})),
    }
    _VALIDATOR.validate_active(result)
    return result


def migrate_checkpoint_v1(document: dict[str, Any], *, observed_at: str) -> dict[str, Any]:
    if document.get("schema_version") != 1:
        raise ValueError("migrate_checkpoint_v1 requires schema_version 1")
    accepted = document.get("accepted_product_sha")
    deployed = document.get("deployed_repository_sha")
    _VALIDATOR._require_sha(accepted, "v1 checkpoint accepted product SHA")
    _VALIDATOR._require_sha(deployed, "v1 checkpoint deployed product SHA")

    active_v1 = document.get("active_work")
    active = None
    if isinstance(active_v1, dict) and isinstance(active_v1.get("issue"), int):
        active = {
            "issue": active_v1["issue"],
            "branch": active_v1.get("branch"),
            "status": str(active_v1.get("status") or ""),
        }

    observations: list[dict[str, Any]] = []
    completed = document.get("completed_work", {})
    completed_evidence: dict[str, Any] = {}
    if isinstance(completed, dict):
        for key, item in completed.items():
            if not isinstance(item, dict):
                continue
            preserved = {k: copy.deepcopy(v) for k, v in item.items() if k != "merge_sha"}
            completed_evidence[key] = preserved
            merge_sha = item.get("merge_sha")
            if isinstance(merge_sha, str) and _VALIDATOR.SHA_RE.fullmatch(merge_sha):
                observations.append(
                    {
                        "source": "github",
                        "observed_at": observed_at,
                        "kind": "historical_merge",
                        "data": {"record": key, "merge_sha": merge_sha},
                    }
                )

    result: dict[str, Any] = {
        "schema_version": 2,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": str(document.get("sprint") or ""),
        "timestamp": str(document.get("timestamp") or ""),
        "actor": str(document.get("actor") or ""),
        "event": str(document.get("event") or "v1_migration"),
        "baselines": {
            "accepted_product_sha": accepted,
            "deployed_product_sha": deployed,
        },
        "active_work": active,
        "evidence_snapshot": {
            "completed_work": completed_evidence,
            "maintenance_actions": copy.deepcopy(document.get("maintenance_actions", {})),
            "blocked_work": copy.deepcopy(document.get("blocked_work", {})),
        },
        "observations": observations,
        "next_action": str(document.get("next_action") or "Resume from ACTIVE_SPRINT.json"),
        "safety": copy.deepcopy(document.get("safety", {})),
    }
    _VALIDATOR.validate_checkpoint(result)
    return result


def find_work_package(active: dict[str, Any], issue: int) -> dict[str, Any]:
    for item in active.get("work_packages", []):
        if item.get("issue") == issue:
            return item
    raise ValueError(f"Issue #{issue} is absent from work_packages")


def begin_work(active: dict[str, Any], *, issue: int, title: str, branch: str) -> dict[str, Any]:
    result = copy.deepcopy(active)
    current = result["selection"].get("active_work_package")
    if current is not None and current.get("issue") != issue:
        current_item = find_work_package(result, current["issue"])
        if current_item.get("lifecycle") == "in_progress":
            raise ValueError(f"Issue #{current['issue']} is still active")

    try:
        item = find_work_package(result, issue)
        item["title"] = title
        item["branch"] = branch
        item["lifecycle"] = "in_progress"
    except ValueError:
        item = {
            "issue": issue,
            "title": title,
            "priority": "unspecified",
            "lifecycle": "in_progress",
            "branch": branch,
            "evidence": {},
        }
        result["work_packages"].append(item)

    result["selection"]["active_work_package"] = {
        "issue": issue,
        "title": title,
        "branch": branch,
    }
    result["selection"]["next_work_package"] = None
    _VALIDATOR.validate_active(result)
    return result


def record_evidence(
    active: dict[str, Any],
    *,
    issue: int,
    verified_head_sha: str,
    pull_request: int | None,
    checks: list[str],
    hardware_evidence_sha: str | None,
) -> dict[str, Any]:
    _VALIDATOR._require_sha(verified_head_sha, "verified_head_sha")
    if hardware_evidence_sha is not None:
        _VALIDATOR._require_sha(hardware_evidence_sha, "hardware_evidence_sha")
    result = copy.deepcopy(active)
    item = find_work_package(result, issue)
    evidence = item.setdefault("evidence", {})
    evidence["verified_head_sha"] = verified_head_sha
    if pull_request is not None:
        evidence["pull_request"] = pull_request
    if hardware_evidence_sha is not None:
        evidence["hardware_evidence_sha"] = hardware_evidence_sha
    if checks:
        parsed: dict[str, str] = dict(evidence.get("checks", {}))
        for entry in checks:
            if "=" not in entry:
                raise ValueError("--check values must use NAME=VALUE")
            name, value = entry.split("=", 1)
            if not name or not value:
                raise ValueError("--check values must use non-empty NAME=VALUE")
            parsed[name] = value
        evidence["checks"] = parsed
    _VALIDATOR.validate_active(result)
    return result


def complete_work(active: dict[str, Any], *, issue: int) -> dict[str, Any]:
    result = copy.deepcopy(active)
    item = find_work_package(result, issue)
    verified = item.get("evidence", {}).get("verified_head_sha")
    if verified is None:
        raise ValueError("Work Package cannot complete without verified_head_sha evidence")
    item["lifecycle"] = "completed"
    current = result["selection"].get("active_work_package")
    if isinstance(current, dict) and current.get("issue") == issue:
        result["selection"]["active_work_package"] = None
    _VALIDATOR.validate_active(result)
    return result


def make_checkpoint(
    *,
    active: dict[str, Any],
    current: dict[str, Any] | None,
    event: str,
    next_action: str,
    timestamp: str,
    actor: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 2,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": active["sprint"]["id"],
        "timestamp": timestamp,
        "actor": actor,
        "event": event,
        "baselines": copy.deepcopy(active["baselines"]),
        "active_work": copy.deepcopy(active["selection"].get("active_work_package")),
        "evidence_snapshot": {
            "active_issue_evidence": (
                copy.deepcopy(find_work_package(active, current["issue"]).get("evidence", {}))
                if current is not None
                else {}
            )
        },
        "observations": [],
        "next_action": next_action,
        "safety": copy.deepcopy(active["safety"]),
    }
    _VALIDATOR.validate_checkpoint(result)
    return result


def _write_or_preview(
    path: Path, old: dict[str, Any], new: dict[str, Any], *, dry_run: bool
) -> None:
    before = canonical(old).splitlines(keepends=True)
    after = canonical(new).splitlines(keepends=True)
    if dry_run:
        print(
            "".join(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=str(path),
                    tofile=str(path),
                )
            ),
            end="",
        )
        return
    path.write_text(canonical(new), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate")

    migrate = sub.add_parser("migrate-v1")
    migrate.add_argument("--observed-at", required=True)
    migrate.add_argument("--dry-run", action="store_true")

    begin = sub.add_parser("begin")
    begin.add_argument("--issue", type=int, required=True)
    begin.add_argument("--title", required=True)
    begin.add_argument("--branch", required=True)
    begin.add_argument("--dry-run", action="store_true")

    evidence = sub.add_parser("record-evidence")
    evidence.add_argument("--issue", type=int, required=True)
    evidence.add_argument("--verified-head-sha", required=True)
    evidence.add_argument("--pull-request", type=int)
    evidence.add_argument("--check", action="append", default=[])
    evidence.add_argument("--hardware-evidence-sha")
    evidence.add_argument("--dry-run", action="store_true")

    complete = sub.add_parser("complete")
    complete.add_argument("--issue", type=int, required=True)
    complete.add_argument("--dry-run", action="store_true")

    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--event", required=True)
    checkpoint.add_argument("--next-action", required=True)
    checkpoint.add_argument("--timestamp", required=True)
    checkpoint.add_argument("--actor", default="ChatGPT")
    checkpoint.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    active_path = args.root / ACTIVE_REL
    checkpoint_path = args.root / CHECKPOINT_REL

    if args.command == "validate":
        _VALIDATOR.validate_repository(args.root)
        print("NEXOLAB State Model v2 validation passed.")
        return 0

    active = load(active_path)
    checkpoint = load(checkpoint_path)

    if args.command == "migrate-v1":
        new_active = migrate_active_v1(active, observed_at=args.observed_at)
        new_checkpoint = migrate_checkpoint_v1(checkpoint, observed_at=args.observed_at)
        _write_or_preview(active_path, active, new_active, dry_run=args.dry_run)
        _write_or_preview(checkpoint_path, checkpoint, new_checkpoint, dry_run=args.dry_run)
        return 0

    if active.get("schema_version") != 2:
        raise ValueError("Mutation commands require State Model v2; run migrate-v1 first")

    if args.command == "begin":
        updated = begin_work(active, issue=args.issue, title=args.title, branch=args.branch)
        _write_or_preview(active_path, active, updated, dry_run=args.dry_run)
        return 0

    if args.command == "record-evidence":
        updated = record_evidence(
            active,
            issue=args.issue,
            verified_head_sha=args.verified_head_sha,
            pull_request=args.pull_request,
            checks=args.check,
            hardware_evidence_sha=args.hardware_evidence_sha,
        )
        _write_or_preview(active_path, active, updated, dry_run=args.dry_run)
        return 0

    if args.command == "complete":
        updated = complete_work(active, issue=args.issue)
        _write_or_preview(active_path, active, updated, dry_run=args.dry_run)
        return 0

    if args.command == "checkpoint":
        current = active["selection"].get("active_work_package")
        updated = make_checkpoint(
            active=active,
            current=current,
            event=args.event,
            next_action=args.next_action,
            timestamp=args.timestamp,
            actor=args.actor,
        )
        _write_or_preview(checkpoint_path, checkpoint, updated, dry_run=args.dry_run)
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
