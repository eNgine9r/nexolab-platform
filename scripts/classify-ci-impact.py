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

AUTHENTICATED_DASHBOARD_WORKFLOW = "Authenticated Dashboard Acceptance"
OFFLINE_BUNDLE_WORKFLOW = "Offline Bundle"
REFRIGERATION_BROWSER_WORKFLOW = "Refrigeration Browser Acceptance"

DASHBOARD_EXTERNAL_TOOLCHAIN_PATHS = {
    "package.json",
    "package-lock.json",
    "next.config.ts",
    "playwright.dashboard.config.ts",
}

OFFLINE_EXTERNAL_DEPENDENCY_PATHS = {
    "package.json",
    "package-lock.json",
    "next.config.ts",
}

DASHBOARD_FOCUSED_DOMAINS = {
    "settings": (
        ("src/app/settings/**", "src/components/settings/**", "src/features/settings/**", "e2e/settings.production.e2e.ts"),
        "settings.production.e2e.ts",
    ),
    "energy": (
        ("src/app/energy/**", "src/components/energy/**", "src/features/energy/**", "src/hooks/use-energy-telemetry*", "e2e/energy.production.e2e.ts"),
        "energy.production.e2e.ts",
    ),
    "live": (
        ("src/app/live/**", "src/components/live/**", "src/components/live-dashboards/**", "src/features/live/**", "src/features/live-dashboards/**", "src/hooks/use-live-telemetry*", "src/hooks/use-live-dashboard-*", "e2e/live*.production.e2e.ts"),
        "live*.production.e2e.ts",
    ),
    "equipment": (
        ("src/app/equipment/**", "src/app/equipment-layouts/**", "src/components/equipment/**", "src/components/equipment-layouts/**", "src/features/equipment/**", "src/features/equipment-layouts/**", "src/hooks/use-equipment-*", "e2e/equipment*.production.e2e.ts"),
        "equipment*.production.e2e.ts",
    ),
    "charts": (
        ("src/components/charts/**", "src/features/charts/**", "e2e/*chart*.production.e2e.ts"),
        "*chart*.production.e2e.ts",
    ),
}

DASHBOARD_SHARED_PATTERNS = (
    "src/features/security/**",
    "src/features/acquisition/**",
    "src/components/dashboard/**",
    "src/app/api/device-agent/acquisition-cadence/**",
    "src/hooks/use-dashboard-security*",
    "src/hooks/use-dashboard-telemetry*",
    "src/lib/telemetry/**",
    "services/device-agent/**",
    "services/telemetry-service/app/**",
    "services/telemetry-service/migrations/**",
    "services/telemetry-service/requirements.txt",
    "e2e/authenticated-dashboard.production.e2e.ts",
    "e2e/telemetry-acquisition-invariant.production.e2e.ts",
    "e2e/telemetry-navigation.production.e2e.ts",
    "infrastructure/compose/compose.browser-acceptance.yaml",
    "infrastructure/compose/compose.central.yaml",
    "playwright.dashboard.config.ts",
    "scripts/run-authenticated-dashboard-acceptance.sh",
    "scripts/run-acquisition-invariant-browser-acceptance.sh",
    ".github/workflows/authenticated-dashboard-acceptance.yml",
    "scripts/classify-ci-impact.py",
    "docs/authenticated-live-telemetry.md",
)

REFRIGERATION_PATTERNS = (
    "src/components/refrigeration/**",
    "src/features/refrigeration/**",
    "services/telemetry-service/app/refrigeration/**",
    "services/telemetry-service/migrations/**",
    "e2e/refrigeration*.production.e2e.ts",
    "scripts/run-refrigeration-browser-acceptance.sh",
    "infrastructure/compose/compose.browser-acceptance.yaml",
    "infrastructure/compose/compose.central.yaml",
    ".github/workflows/refrigeration-browser-acceptance.yml",
    "scripts/classify-ci-impact.py",
    "docs/refrigeration-browser-central-acceptance.md",
)

OFFLINE_BUNDLE_PATTERNS = (
    "infrastructure/compose/**",
    "infrastructure/offline/**",
    "services/device-agent/**",
    "services/telemetry-service/**",
    "src/app/api/**",
    "scripts/build-offline-bundle.sh",
    "scripts/generate-offline-bundle-manifest.py",
    "scripts/install-offline-bundle.sh",
    "scripts/offline-bundle-smoke.sh",
    "scripts/verify-offline-bundle.py",
    "scripts/verify-offline-volume-preservation.sh",
    "docs/operations/offline-installation.md",
    ".github/workflows/offline-bundle.yml",
    "scripts/classify-ci-impact.py",
)

CI_GOVERNANCE_PATHS = {
    "PROJECT_PROFILE.yaml",
    "AGENTS.md",
    "docs/AI_DEVELOPMENT_OPERATING_STANDARD.md",
    "scripts/classify-ci-impact.py",
    "scripts/validate-project-state.py",
    "scripts/verify-pr-workflow-matrix.py",
    "scripts/prepare-clean-verification-worktree.sh",
    "tests/test_ci_change_impact.py",
    "tests/test_ci_project_state_validation.py",
    "tests/test_ci_workflow_matrix.py",
}


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_docs(path: str) -> bool:
    return path in ROOT_DOCS or path.startswith("docs/")


def _verification_for_paths(
    normalized: list[str],
    *,
    state_only: bool,
    fail_closed: bool,
) -> dict[str, object]:
    if state_only:
        return {
            "dashboard_mode": "none",
            "dashboard_test_match": None,
            "offline_bundle": False,
            "refrigeration_browser": False,
            "required_external_workflows": [],
        }

    offline_bundle = fail_closed or any(
        path in OFFLINE_EXTERNAL_DEPENDENCY_PATHS for path in normalized
    ) or any(_matches(path, OFFLINE_BUNDLE_PATTERNS) for path in normalized)
    refrigeration_dependency = any(
        path in {"package.json", "package-lock.json", "playwright.production.config.ts"}
        for path in normalized
    )
    refrigeration_browser = (
        fail_closed
        or refrigeration_dependency
        or any(_matches(path, REFRIGERATION_PATTERNS) for path in normalized)
    )

    shared_dashboard = fail_closed or any(
        path in DASHBOARD_EXTERNAL_TOOLCHAIN_PATHS for path in normalized
    ) or any(_matches(path, DASHBOARD_SHARED_PATTERNS) for path in normalized)
    focused_domains = []
    for name, (patterns, test_match) in DASHBOARD_FOCUSED_DOMAINS.items():
        if any(_matches(path, patterns) for path in normalized):
            focused_domains.append((name, test_match))

    if shared_dashboard or len(focused_domains) > 1:
        dashboard_mode = "full"
        dashboard_test_match = None
    elif len(focused_domains) == 1:
        dashboard_mode = "focused"
        dashboard_test_match = focused_domains[0][1]
    else:
        dashboard_mode = "none"
        dashboard_test_match = None

    required = []
    if dashboard_mode != "none":
        required.append(AUTHENTICATED_DASHBOARD_WORKFLOW)
    if offline_bundle:
        required.append(OFFLINE_BUNDLE_WORKFLOW)
    if refrigeration_browser:
        required.append(REFRIGERATION_BROWSER_WORKFLOW)

    return {
        "dashboard_mode": dashboard_mode,
        "dashboard_test_match": dashboard_test_match,
        "offline_bundle": offline_bundle,
        "refrigeration_browser": refrigeration_browser,
        "required_external_workflows": required,
    }


def classify(paths: Iterable[str]) -> dict[str, object]:
    normalized = sorted({PurePosixPath(path.strip()).as_posix() for path in paths if path.strip()})
    if not normalized:
        result = {
            "files": [],
            "classes": ["cross_surface_or_unknown"],
            "state_only": False,
            "docs_only": False,
            "needs_full_quality": True,
            "fail_closed": True,
        }
        result["verification"] = _verification_for_paths([], state_only=False, fail_closed=True)
        return result

    path_set = set(normalized)
    state_only = path_set <= STATE_PATHS
    docs_only = all(_is_docs(path) for path in normalized) and not state_only

    if state_only:
        result = {
            "files": normalized,
            "classes": ["state_only"],
            "state_only": True,
            "docs_only": False,
            "needs_full_quality": False,
            "fail_closed": False,
        }
        result["verification"] = _verification_for_paths(normalized, state_only=True, fail_closed=False)
        return result

    if docs_only:
        # Markdown formatting is still enforced by the repository Prettier gate.
        # Until a dependency-free formatter with equivalent semantics exists, docs
        # remain on the full quality lane rather than silently weakening formatting.
        result = {
            "files": normalized,
            "classes": ["docs_only"],
            "state_only": False,
            "docs_only": True,
            "needs_full_quality": True,
            "fail_closed": False,
        }
        result["verification"] = _verification_for_paths(normalized, state_only=False, fail_closed=False)
        return result

    classes: set[str] = set()
    unknown: list[str] = []

    for path in normalized:
        matched = False

        if (
            path in CI_GOVERNANCE_PATHS
            or path.startswith(".github/")
            or path.startswith("tests/test_ci_")
        ):
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
            or path.startswith("tests/test_container_")
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

    result = {
        "files": normalized,
        "classes": sorted(classes) or ["cross_surface_or_unknown"],
        "state_only": False,
        "docs_only": False,
        "needs_full_quality": True,
        "fail_closed": bool(unknown),
        "unknown_files": unknown,
    }
    result["verification"] = _verification_for_paths(
        normalized,
        state_only=False,
        fail_closed=bool(unknown),
    )
    return result


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
        verification = result["verification"]
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"classes={json.dumps(result['classes'], separators=(',', ':'))}\n")
            handle.write(f"state_only={str(result['state_only']).lower()}\n")
            handle.write(f"docs_only={str(result['docs_only']).lower()}\n")
            handle.write(f"needs_full_quality={str(result['needs_full_quality']).lower()}\n")
            handle.write(f"fail_closed={str(result['fail_closed']).lower()}\n")
            handle.write(f"dashboard_mode={verification['dashboard_mode']}\n")
            handle.write(f"dashboard_test_match={verification['dashboard_test_match'] or ''}\n")
            handle.write(f"offline_bundle={str(verification['offline_bundle']).lower()}\n")
            handle.write(f"refrigeration_browser={str(verification['refrigeration_browser']).lower()}\n")
            handle.write(
                "required_external_workflows="
                + json.dumps(verification["required_external_workflows"], separators=(",", ":"))
                + "\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
