#!/usr/bin/env python3
"""Wait for and verify all other GitHub Actions PR workflows on one exact head.

This script is used by the stable NEXOLAB Merge Gate after its own Core lane is
GREEN. It intentionally has no third-party dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PENDING_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}
SUCCESS_CONCLUSIONS = {"success"}


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    workflow_id: int
    name: str
    status: str
    conclusion: str | None
    created_at: str
    run_attempt: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "WorkflowRun":
        return cls(
            id=int(raw["id"]),
            workflow_id=int(raw["workflow_id"]),
            name=str(raw.get("name") or raw["workflow_id"]),
            status=str(raw.get("status") or "unknown"),
            conclusion=raw.get("conclusion"),
            created_at=str(raw.get("created_at") or ""),
            run_attempt=int(raw.get("run_attempt") or 1),
        )


def latest_by_workflow(runs: Iterable[WorkflowRun], current_run_id: int) -> list[WorkflowRun]:
    latest: dict[int, WorkflowRun] = {}
    for run in runs:
        existing = latest.get(run.workflow_id)
        marker = (run.created_at, run.run_attempt, run.id)
        existing_marker = (
            (existing.created_at, existing.run_attempt, existing.id) if existing else ("", 0, 0)
        )
        if existing is None or marker > existing_marker:
            latest[run.workflow_id] = run

    return sorted(
        (run for run in latest.values() if run.id != current_run_id),
        key=lambda run: (run.name, run.workflow_id),
    )


def missing_required_workflows(
    runs: Iterable[WorkflowRun],
    required_names: Iterable[str],
) -> list[str]:
    observed = {run.name for run in runs}
    return sorted({name for name in required_names if name and name not in observed})


def evaluate_runs(runs: Iterable[WorkflowRun]) -> tuple[list[WorkflowRun], list[WorkflowRun]]:
    pending: list[WorkflowRun] = []
    failed: list[WorkflowRun] = []
    for run in runs:
        if run.status != "completed" or run.status in PENDING_STATUSES:
            pending.append(run)
            continue
        if run.conclusion not in SUCCESS_CONCLUSIONS:
            failed.append(run)
    return pending, failed


def _request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nexolab-merge-gate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub Actions API returned HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub Actions API request failed: {exc.reason}") from exc


def fetch_runs(api_url: str, repository: str, head_sha: str, token: str) -> list[WorkflowRun]:
    query = urllib.parse.urlencode(
        {
            "head_sha": head_sha,
            "event": "pull_request",
            "per_page": 100,
        }
    )
    payload = _request_json(f"{api_url}/repos/{repository}/actions/runs?{query}", token)
    raw_runs = payload.get("workflow_runs")
    if not isinstance(raw_runs, list):
        raise RuntimeError("GitHub Actions API response did not contain workflow_runs")
    return [WorkflowRun.from_api(raw) for raw in raw_runs]


def format_runs(runs: Iterable[WorkflowRun]) -> str:
    rows = [
        f"{run.name}#{run.id}: status={run.status}, conclusion={run.conclusion}, attempt={run.run_attempt}"
        for run in runs
    ]
    return "\n".join(rows) if rows else "(none)"


def wait_for_green_matrix(
    *,
    api_url: str,
    repository: str,
    head_sha: str,
    current_run_id: int,
    token: str,
    poll_seconds: int,
    timeout_seconds: int,
    stable_rounds_required: int,
    required_workflows: tuple[str, ...] = (),
) -> list[WorkflowRun]:
    deadline = time.monotonic() + timeout_seconds
    stable_rounds = 0
    previous_ids: tuple[int, ...] | None = None
    latest_external: list[WorkflowRun] = []

    while True:
        all_runs = fetch_runs(api_url, repository, head_sha, token)
        latest_external = latest_by_workflow(all_runs, current_run_id)
        pending, failed = evaluate_runs(latest_external)
        missing = missing_required_workflows(latest_external, required_workflows)

        if failed:
            raise RuntimeError(
                "Exact-head PR workflow matrix contains non-GREEN workflow(s):\n"
                + format_runs(failed)
            )

        current_ids = tuple(run.id for run in latest_external)
        if pending:
            stable_rounds = 0
        elif current_ids == previous_ids:
            stable_rounds += 1
        else:
            stable_rounds = 1

        print(
            f"Observed {len(latest_external)} external exact-head PR workflow(s); "
            f"pending={len(pending)}; missing_required={len(missing)}; "
            f"registration_stability={stable_rounds}/{stable_rounds_required}",
            flush=True,
        )
        if pending:
            print(format_runs(pending), flush=True)
        if missing:
            print("Missing required workflow(s): " + ", ".join(missing), flush=True)

        if not pending and stable_rounds >= stable_rounds_required:
            if missing:
                raise RuntimeError(
                    "Exact-head PR workflow registration stabilized without required workflow(s): "
                    + ", ".join(missing)
                )
            return latest_external

        if time.monotonic() >= deadline:
            missing_detail = (
                "\nMissing required workflow(s): " + ", ".join(missing) if missing else ""
            )
            raise TimeoutError(
                "Timed out waiting for the exact-head PR workflow matrix. Latest observed runs:\n"
                + format_runs(latest_external)
                + missing_detail
            )

        previous_ids = current_ids
        time.sleep(poll_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--current-run-id", type=int, default=int(os.environ.get("GITHUB_RUN_ID", "0")))
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--stable-rounds", type=int, default=2)
    parser.add_argument(
        "--required-workflows-json",
        default="[]",
        help="JSON array of workflow names that must be registered for this exact head",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not args.repository:
        print("Repository is required.", file=sys.stderr)
        return 2
    if not token:
        print("GITHUB_TOKEN is required for exact-head workflow aggregation.", file=sys.stderr)
        return 2
    if args.current_run_id <= 0:
        print("A positive current GitHub Actions run ID is required.", file=sys.stderr)
        return 2

    try:
        parsed_required = json.loads(args.required_workflows_json)
        if not isinstance(parsed_required, list) or not all(
            isinstance(item, str) and item.strip() for item in parsed_required
        ):
            raise ValueError("required workflows must be a JSON array of non-empty strings")
        required_workflows = tuple(dict.fromkeys(item.strip() for item in parsed_required))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid --required-workflows-json: {exc}", file=sys.stderr)
        return 2

    try:
        runs = wait_for_green_matrix(
            api_url=args.api_url,
            repository=args.repository,
            head_sha=args.head_sha,
            current_run_id=args.current_run_id,
            token=token,
            poll_seconds=max(1, args.poll_seconds),
            timeout_seconds=max(1, args.timeout_seconds),
            stable_rounds_required=max(1, args.stable_rounds),
            required_workflows=required_workflows,
        )
    except (RuntimeError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("All observed external exact-head PR workflows are GREEN:")
    print(format_runs(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
