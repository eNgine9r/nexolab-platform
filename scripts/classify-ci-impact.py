#!/usr/bin/env python3
"""Classify NEXOLAB changed files into deterministic CI impact classes.

The classifier is intentionally fail-closed. Unknown paths broaden verification rather
than silently skipping checks. It has no third-party dependencies so canonical state
changes can be validated without installing the frontend dependency graph.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import PurePosixPath
from typing import Iterable

STATE_PATHS = {
    ".project/CURRENT_STATE.md",
    ".project/ACTIVE_SPRINT.json",
    ".project/BLOCKERS.md",
    ".project/LAST_CHECKPOINT.json",
}

ROOT_DOCS = {"README.md"}

DEPENDENCY_TOOLCHAIN_PATHS = {
    "package.json",
    "package-lock.json",
    ".nvmrc",
    "eslint.config.mjs",
    "tsconfig.json",
    "next.config.ts",
    "postcss.config.mjs",
    "playwright.config.ts",
    "playwright.production.config.ts",
    "playwright.security.config.ts",
    "playwright.dashboard.config.ts",
    "playwright.sessions.config.ts",
    "playwright.alerts.config.ts",
    "playwright.reports.config.ts",
    "playwright.rendered-reports.config.ts",
    "playwright.nodes.config.ts",
    "vitest.config.ts",
}

CI_GOVERNANCE_PATHS = {
    "PROJECT_PROFILE.yaml",
    "AGENTS.md",
    "docs/AI_DEVELOPMENT_OPERATING_STANDARD.md",
    "scripts/classify-ci-impact.py",
    "scripts/validate-project-state.py",
    "scripts/verify-pr-workflow-matrix.py",
    "tests/test_ci_change_impact.py",
    "tests/test_ci_project_state_validation.py",
    "tests/test_ci_workflow_matrix.py",
}


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_docs(path: str) -> bool:
    return path in ROOT_DOCS or path.startswith("docs/")


def classify(paths: Iterable[str]) -> dict[str, object]:
    normalized = sorted({PurePosixPath(path.strip()).as_posix() for path in paths if path.strip()})
    if not normalized:
        return {
            "files": [],
            "classes": ["cross_surface_or_unknown"],
            "state_only": False,
            "docs_only": False,
            "needs_full_quality": True,
            "fail_closed": True,
        }

    path_set = set(normalized)
    state_only = path_set <= STATE_PATHS
    docs_only = all(_is_docs(path) for path in normalized) and not state_only

    if state_only:
        return {
            "files": normalized,
            "classes": ["state_only"],
            "state_only": True,
            "docs_only": False,
            "needs_full_quality": False,
            "fail_closed": False,
        }

    if docs_only:
        # Markdown formatting is still enforced by the repository Prettier gate.
        # Until a dependency-free formatter with equivalent semantics exists, docs
        # remain on the full quality lane rather than silently weakening formatting.
        return {
            "files": normalized,
            "classes": ["docs_only"],
            "state_only": False,
            "docs_only": True,
            "needs_full_quality": True,
            "fail_closed": False,
        }

    classes: set[str] = set()
    unknown: list[str] = []

    for path in normalized:
        matched = False

        if path in CI_GOVERNANCE_PATHS or path.startswith(".github/"):
            classes.add("ci_governance")
            matched = True

        if path in DEPENDENCY_TOOLCHAIN_PATHS:
            classes.add("dependency_toolchain")
            matched = True

        if path.startswith("src/") or path.startswith("e2e/") or path.startswith("public/"):
            classes.add("frontend")
            matched = True

        if path.startswith("services/telemetry-service/") or path.startswith("contracts/"):
            classes.add("backend")
            matched = True

        if path.startswith("services/telemetry-service/migrations/"):
            classes.add("database_migration")
            matched = True

        if path.startswith("services/device-agent/") or path.startswith("config/device-profiles/"):
            classes.add("device_agent")
            matched = True

        if (
            path.startswith("infrastructure/")
            or path.startswith("runtime/")
            or _matches(
                path,
                (
                    "scripts/deploy*",
                    "scripts/*deploy*",
                    "scripts/build-offline-bundle.sh",
                    "scripts/*runtime*",
                    "scripts/*raspberry-pi*",
                ),
            )
        ):
            classes.add("deployment_runtime")
            matched = True

        if (
            path.startswith("security/")
            or "Dockerfile" in path
            or _matches(path, ("scripts/*supply-chain*", "scripts/*security*", "scripts/*vulnerability*"))
        ):
            classes.add("security_supply_chain")
            matched = True

        # Documentation accompanying a product/engineering change is supporting
        # scope; the substantive changed paths determine the required verification.
        if _is_docs(path):
            matched = True

        # Canonical state files can accompany a product PR without broadening it.
        if path in STATE_PATHS:
            matched = True

        # Generic tests/scripts/config are deliberately fail-closed unless matched
        # above. New verification-sensitive paths therefore cannot receive a lighter
        # lane accidentally.
        if not matched:
            unknown.append(path)

    if unknown:
        classes.add("cross_surface_or_unknown")

    if len({c for c in classes if c != "cross_surface_or_unknown"}) > 1:
        classes.add("cross_surface_or_unknown")

    return {
        "files": normalized,
        "classes": sorted(classes) or ["cross_surface_or_unknown"],
        "state_only": False,
        "docs_only": False,
        "needs_full_quality": True,
        "fail_closed": bool(unknown),
        "unknown_files": unknown,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="Changed repository paths")
    parser.add_argument("--files-file", help="Newline-delimited changed paths")
    parser.add_argument("--github-output", help="Optional GitHub Actions output file")
    args = parser.parse_args()

    files = list(args.files)
    if args.files_file:
        with open(args.files_file, encoding="utf-8") as handle:
            files.extend(line.rstrip("\n") for line in handle)

    result = classify(files)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"classes={json.dumps(result['classes'], separators=(',', ':'))}\n")
            handle.write(f"state_only={str(result['state_only']).lower()}\n")
            handle.write(f"docs_only={str(result['docs_only']).lower()}\n")
            handle.write(f"needs_full_quality={str(result['needs_full_quality']).lower()}\n")
            handle.write(f"fail_closed={str(result['fail_closed']).lower()}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
