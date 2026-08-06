#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path

DEPENDABOT_PATH = Path(".github/dependabot.yml")
PACKAGE_JSON_PATH = Path("package.json")
NVMRC_PATH = Path(".nvmrc")
POLICY_DOC_PATH = Path("docs/maintenance/dependency-update-policy.md")
WORKFLOWS_DIR = Path(".github/workflows")

MIGRATION_GRADE_GUARDS = {
    "@playwright/test": ">=1.56",
}

EXPECTED_GROUPS = {
    "development-test-patch-minor": {
        "@testing-library/jest-dom",
        "@testing-library/react",
        "@vitejs/plugin-react",
        "jsdom",
        "vitest",
    },
    "development-quality-patch-minor": {
        "@commitlint/cli",
        "@commitlint/config-conventional",
        "eslint",
        "eslint-config-next",
        "husky",
        "lint-staged",
        "prettier",
        "prettier-plugin-tailwindcss",
    },
    "development-build-patch-minor": {
        "@tailwindcss/postcss",
        "tailwindcss",
    },
    "development-react-types-patch-minor": {
        "@types/react",
        "@types/react-dom",
    },
}

REQUIRED_MAJOR_MIGRATION_ISSUES = {
    "lint-staged": "#252",
    "jsdom": "#253",
    "@playwright/test": "#254",
    "TypeScript 6": "#255",
    "TypeScript 7": "#256",
    "ESLint 10": "#257",
}

AUTO_MERGE_MARKERS = (
    "gh pr merge",
    "enablepullrequestautomerge",
    "merge-pull-request",
    "dependabot-automerge",
    "dependabot automerge",
    "auto-merge dependabot",
)


class DependencyPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Group:
    dependency_type: str | None
    patterns: tuple[str, ...]
    update_types: tuple[str, ...]


@dataclass(frozen=True)
class IgnoreRule:
    dependency_name: str
    update_types: tuple[str, ...]
    versions: tuple[str, ...]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DependencyPolicyError(f"cannot read {path}") from exc


def strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def extract_npm_block(text: str) -> list[str]:
    lines = text.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if line.strip() == "- package-ecosystem: npm"
    ]
    if len(starts) != 1:
        raise DependencyPolicyError(
            f"expected exactly one npm update block, found {len(starts)}"
        )
    start = starts[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - package-ecosystem:"):
            end = index
            break
    return lines[start:end]


def section(block: list[str], heading: str) -> list[str]:
    marker = f"    {heading}:"
    matches = [index for index, line in enumerate(block) if line == marker]
    if len(matches) != 1:
        raise DependencyPolicyError(
            f"expected one {heading} section in npm update block, found {len(matches)}"
        )
    start = matches[0] + 1
    end = len(block)
    for index in range(start, len(block)):
        line = block[index]
        if line and not line.startswith("      "):
            end = index
            break
    return block[start:end]


def list_values(lines: list[str], start_index: int) -> tuple[tuple[str, ...], int]:
    values: list[str] = []
    index = start_index
    while index < len(lines):
        match = re.fullmatch(r"\s{10}-\s+(.+)", lines[index])
        if not match:
            break
        values.append(strip_scalar(match.group(1)))
        index += 1
    return tuple(values), index


def parse_groups(block: list[str]) -> dict[str, Group]:
    lines = section(block, "groups")
    groups: dict[str, Group] = {}
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        header = re.fullmatch(r"\s{6}([a-z0-9-]+):", lines[index])
        if not header:
            raise DependencyPolicyError(f"invalid group declaration: {lines[index]}")
        name = header.group(1)
        if name in groups:
            raise DependencyPolicyError(f"duplicate dependency group: {name}")
        index += 1
        dependency_type: str | None = None
        patterns: tuple[str, ...] = ()
        update_types: tuple[str, ...] = ()
        while index < len(lines) and not re.fullmatch(
            r"\s{6}[a-z0-9-]+:", lines[index]
        ):
            line = lines[index]
            if match := re.fullmatch(r"\s{8}dependency-type:\s+(.+)", line):
                dependency_type = strip_scalar(match.group(1))
                index += 1
                continue
            if line == "        patterns:":
                patterns, index = list_values(lines, index + 1)
                continue
            if line == "        update-types:":
                update_types, index = list_values(lines, index + 1)
                continue
            if line.strip():
                raise DependencyPolicyError(
                    f"unsupported field in dependency group {name}: {line.strip()}"
                )
            index += 1
        groups[name] = Group(
            dependency_type=dependency_type,
            patterns=patterns,
            update_types=update_types,
        )
    return groups


def parse_ignore_rules(block: list[str]) -> list[IgnoreRule]:
    lines = section(block, "ignore")
    rules: list[IgnoreRule] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        header = re.fullmatch(r"\s{6}-\s+dependency-name:\s+(.+)", lines[index])
        if not header:
            raise DependencyPolicyError(f"invalid ignore rule: {lines[index]}")
        dependency_name = strip_scalar(header.group(1))
        index += 1
        update_types: tuple[str, ...] = ()
        versions: tuple[str, ...] = ()
        while index < len(lines) and not re.fullmatch(
            r"\s{6}-\s+dependency-name:\s+(.+)", lines[index]
        ):
            line = lines[index]
            if line == "        update-types:":
                update_types, index = list_values(lines, index + 1)
                continue
            if line == "        versions:":
                versions, index = list_values(lines, index + 1)
                continue
            if line.strip():
                raise DependencyPolicyError(
                    f"unsupported field in ignore rule {dependency_name}: {line.strip()}"
                )
            index += 1
        rules.append(
            IgnoreRule(
                dependency_name=dependency_name,
                update_types=update_types,
                versions=versions,
            )
        )
    return rules


def validate_groups(groups: dict[str, Group], package: dict[str, object]) -> None:
    if set(groups) != set(EXPECTED_GROUPS):
        raise DependencyPolicyError(
            "dependency group set mismatch; "
            f"actual={sorted(groups)}, expected={sorted(EXPECTED_GROUPS)}"
        )

    production = set(package.get("dependencies", {}))
    development = set(package.get("devDependencies", {}))
    seen_patterns: set[str] = set()

    for name, expected_patterns in EXPECTED_GROUPS.items():
        group = groups[name]
        if group.dependency_type != "development":
            raise DependencyPolicyError(
                f"group {name} must be development-only, got {group.dependency_type}"
            )
        if set(group.update_types) != {"patch", "minor"}:
            raise DependencyPolicyError(
                f"group {name} must contain patch and minor updates only"
            )
        if "major" in group.update_types:
            raise DependencyPolicyError(f"group {name} must not include major updates")

        migration_grade = set(group.patterns) & set(MIGRATION_GRADE_GUARDS)
        if migration_grade:
            raise DependencyPolicyError(
                f"migration-grade dependencies must not enter grouped updates: "
                f"{sorted(migration_grade)}"
            )

        if set(group.patterns) != expected_patterns:
            raise DependencyPolicyError(
                f"group {name} pattern mismatch; "
                f"actual={sorted(group.patterns)}, expected={sorted(expected_patterns)}"
            )
        overlaps = seen_patterns & set(group.patterns)
        if overlaps:
            raise DependencyPolicyError(
                f"dependency patterns overlap between groups: {sorted(overlaps)}"
            )
        seen_patterns.update(group.patterns)

        matched_production = {
            dependency
            for dependency in production
            if any(fnmatch.fnmatchcase(dependency, pattern) for pattern in group.patterns)
        }
        if matched_production:
            raise DependencyPolicyError(
                f"production dependencies entered development group {name}: "
                f"{sorted(matched_production)}"
            )
        unknown = {
            pattern
            for pattern in group.patterns
            if not any(
                fnmatch.fnmatchcase(dependency, pattern) for dependency in development
            )
        }
        if unknown:
            raise DependencyPolicyError(
                f"group {name} contains patterns without current dev dependencies: "
                f"{sorted(unknown)}"
            )


def validate_ignore_rules(rules: list[IgnoreRule]) -> None:
    global_major = [
        rule
        for rule in rules
        if rule.dependency_name == "*"
        and "version-update:semver-major" in rule.update_types
    ]
    if len(global_major) != 1:
        raise DependencyPolicyError(
            "npm automation must contain exactly one global SemVer-major ignore rule"
        )

    node_guard = [
        rule
        for rule in rules
        if rule.dependency_name == "@types/node" and ">=23" in rule.versions
    ]
    if len(node_guard) != 1:
        raise DependencyPolicyError(
            "@types/node must have an explicit >=23 ignore guard for the Node 22 baseline"
        )

    for dependency_name, required_version in MIGRATION_GRADE_GUARDS.items():
        matching = [
            rule
            for rule in rules
            if rule.dependency_name == dependency_name
            and required_version in rule.versions
        ]
        if len(matching) != 1:
            raise DependencyPolicyError(
                f"{dependency_name} must have an explicit {required_version} "
                "migration-grade version guard"
            )


def major_from_range(value: str) -> int:
    match = re.search(r"(\d+)", value)
    if not match:
        raise DependencyPolicyError(f"cannot determine major version from {value!r}")
    return int(match.group(1))


def validate_node_boundary(root: Path, package: dict[str, object]) -> None:
    nvmrc = read_text(root / NVMRC_PATH).strip()
    runtime_major = major_from_range(nvmrc)
    if runtime_major != 22:
        raise DependencyPolicyError(
            f"current dependency policy is defined for Node 22, got Node {runtime_major}"
        )
    dev_dependencies = package.get("devDependencies", {})
    if not isinstance(dev_dependencies, dict) or "@types/node" not in dev_dependencies:
        raise DependencyPolicyError("@types/node is missing from devDependencies")
    type_major = major_from_range(str(dev_dependencies["@types/node"]))
    if type_major != runtime_major:
        raise DependencyPolicyError(
            f"@types/node major {type_major} does not match runtime major {runtime_major}"
        )


def validate_policy_document(root: Path) -> None:
    text = read_text(root / POLICY_DOC_PATH)
    for migration, issue in REQUIRED_MAJOR_MIGRATION_ISSUES.items():
        if migration not in text or issue not in text:
            raise DependencyPolicyError(
                f"maintenance policy is missing mapping {migration} -> {issue}"
            )
    required_phrases = (
        "Production runtime updates are individual Pull Requests",
        "Major version updates are disabled in Dependabot version-update automation",
        "Playwright >=1.56",
        "Node 22",
        "@types/node",
        "PR #272",
        "PR #341",
        "offline bundle",
        "rollback",
    )
    for phrase in required_phrases:
        if phrase not in text:
            raise DependencyPolicyError(
                f"maintenance policy is missing required contract phrase: {phrase}"
            )


def validate_no_dependabot_auto_merge(root: Path) -> None:
    workflows = root / WORKFLOWS_DIR
    if not workflows.is_dir():
        raise DependencyPolicyError(f"workflow directory is missing: {WORKFLOWS_DIR}")
    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        text = read_text(path).lower()
        if "dependabot" not in text:
            continue
        markers = [marker for marker in AUTO_MERGE_MARKERS if marker in text]
        if markers:
            raise DependencyPolicyError(
                f"Dependabot auto-merge path detected in {path.relative_to(root)}: "
                f"{markers}"
            )


def validate(root: Path) -> None:
    root = root.resolve()
    dependabot_text = read_text(root / DEPENDABOT_PATH)
    if re.search(r"^\s+development-dependencies:\s*$", dependabot_text, re.MULTILINE):
        raise DependencyPolicyError("legacy broad development-dependencies group remains")
    if re.search(r"^\s+production-dependencies:\s*$", dependabot_text, re.MULTILINE):
        raise DependencyPolicyError("legacy broad production-dependencies group remains")

    package = json.loads(read_text(root / PACKAGE_JSON_PATH))
    if not isinstance(package, dict):
        raise DependencyPolicyError("package.json root must be an object")

    npm_block = extract_npm_block(dependabot_text)
    groups = parse_groups(npm_block)
    rules = parse_ignore_rules(npm_block)
    validate_groups(groups, package)
    validate_ignore_rules(rules)
    validate_node_boundary(root, package)
    validate_policy_document(root)
    validate_no_dependabot_auto_merge(root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the NEXOLAB dependency automation policy"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    validate(args.root)
    print("Dependency update policy validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DependencyPolicyError, json.JSONDecodeError) as exc:
        print(f"Dependency update policy validation failed: {exc}")
        raise SystemExit(1) from exc
