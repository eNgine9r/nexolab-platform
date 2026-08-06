from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate-dependency-policy.py"
SPEC = importlib.util.spec_from_file_location("validate_dependency_policy", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DependencyPolicyError = MODULE.DependencyPolicyError

VALID_DEPENDABOT = """version: 2
updates:
  - package-ecosystem: npm
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "04:00"
      timezone: Europe/Kyiv
    open-pull-requests-limit: 10
    rebase-strategy: disabled
    commit-message:
      prefix: "chore(deps)"
    labels:
      - "area:devops"
    groups:
      development-test-patch-minor:
        dependency-type: development
        patterns:
          - "@testing-library/jest-dom"
          - "@testing-library/react"
          - "@vitejs/plugin-react"
          - "jsdom"
          - "vitest"
        update-types:
          - patch
          - minor
      development-quality-patch-minor:
        dependency-type: development
        patterns:
          - "@commitlint/cli"
          - "@commitlint/config-conventional"
          - "eslint"
          - "eslint-config-next"
          - "husky"
          - "lint-staged"
          - "prettier"
          - "prettier-plugin-tailwindcss"
        update-types:
          - patch
          - minor
      development-build-patch-minor:
        dependency-type: development
        patterns:
          - "@tailwindcss/postcss"
          - "tailwindcss"
        update-types:
          - patch
          - minor
      development-react-types-patch-minor:
        dependency-type: development
        patterns:
          - "@types/react"
          - "@types/react-dom"
        update-types:
          - patch
          - minor
    ignore:
      - dependency-name: "*"
        update-types:
          - "version-update:semver-major"
      - dependency-name: "@types/node"
        versions:
          - ">=23"
      - dependency-name: "@playwright/test"
        versions:
          - ">=1.56"
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: monthly
"""

POLICY_DOC = """# NEXOLAB Dependency Update Policy

Production runtime updates are individual Pull Requests.
Major version updates are disabled in Dependabot version-update automation.
Playwright >=1.56 is held for focused Issue #254.
Node 22 and @types/node remain aligned.
PR #272 was platform-closed; PR #341 is its open individual replacement.
The offline bundle verification and rollback are required.

lint-staged 17 -> #252
jsdom 30 -> #253
@playwright/test 1.62.x -> #254
TypeScript 6 -> #255
TypeScript 7 -> #256
ESLint 10 -> #257
"""

PACKAGE = {
    "dependencies": {
        "@supabase/supabase-js": "^2.112.0",
        "clsx": "^2.1.1",
        "lucide-react": "^1.25.0",
        "next": "16.2.12",
        "react": "19.2.8",
        "react-dom": "19.2.8",
    },
    "devDependencies": {
        "@commitlint/cli": "^21.2.1",
        "@commitlint/config-conventional": "^21.2.0",
        "@playwright/test": "1.55.0",
        "@tailwindcss/postcss": "^4",
        "@testing-library/jest-dom": "^7.0.0",
        "@testing-library/react": "^16.3.2",
        "@types/node": "^22.20.1",
        "@types/react": "^19",
        "@types/react-dom": "^19",
        "@vitejs/plugin-react": "^6.0.3",
        "eslint": "^9",
        "eslint-config-next": "16.2.12",
        "husky": "^9.1.7",
        "jsdom": "^29.1.1",
        "lint-staged": "^16.4.0",
        "prettier": "^3.9.6",
        "prettier-plugin-tailwindcss": "^0.8.1",
        "tailwindcss": "^4",
        "typescript": "^5",
        "vitest": "^4.1.10",
    },
}


class DependencyPolicyTests(unittest.TestCase):
    def make_fixture(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "docs/maintenance").mkdir(parents=True)
        (root / ".github/dependabot.yml").write_text(
            VALID_DEPENDABOT,
            encoding="utf-8",
        )
        (root / "package.json").write_text(
            json.dumps(PACKAGE, indent=2),
            encoding="utf-8",
        )
        (root / ".nvmrc").write_text("22.23.1\n", encoding="utf-8")
        (root / "docs/maintenance/dependency-update-policy.md").write_text(
            POLICY_DOC,
            encoding="utf-8",
        )
        (root / ".github/workflows/ci.yml").write_text(
            "name: CI\n",
            encoding="utf-8",
        )
        return root

    def test_valid_policy_passes(self) -> None:
        MODULE.validate(self.make_fixture())

    def test_legacy_broad_group_fails(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "development-test-patch-minor:",
                "development-dependencies:",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "legacy broad"):
            MODULE.validate(root)

    def test_major_update_in_group_fails(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "          - minor\n      development-quality-patch-minor:",
                "          - minor\n          - major\n"
                "      development-quality-patch-minor:",
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "patch and minor"):
            MODULE.validate(root)

    def test_global_major_ignore_is_required(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                '      - dependency-name: "*"\n'
                "        update-types:\n"
                '          - "version-update:semver-major"\n',
                "",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "global SemVer-major"):
            MODULE.validate(root)

    def test_node_types_guard_is_required(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                '      - dependency-name: "@types/node"\n'
                "        versions:\n"
                '          - ">=23"\n',
                "",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "@types/node"):
            MODULE.validate(root)

    def test_playwright_guard_is_required(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                '      - dependency-name: "@playwright/test"\n'
                "        versions:\n"
                '          - ">=1.56"\n',
                "",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "migration-grade"):
            MODULE.validate(root)

    def test_playwright_cannot_enter_test_group(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                '          - "@testing-library/jest-dom"\n',
                '          - "@playwright/test"\n'
                '          - "@testing-library/jest-dom"\n',
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "migration-grade"):
            MODULE.validate(root)

    def test_node_types_must_match_runtime_major(self) -> None:
        root = self.make_fixture()
        package_path = root / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["devDependencies"]["@types/node"] = "^26.0.0"
        package_path.write_text(json.dumps(package, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(DependencyPolicyError, "does not match runtime"):
            MODULE.validate(root)

    def test_production_dependency_cannot_enter_dev_group(self) -> None:
        root = self.make_fixture()
        config = root / ".github/dependabot.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                '          - "vitest"\n',
                '          - "vitest"\n          - "lucide-react"\n',
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "pattern mismatch"):
            MODULE.validate(root)

    def test_dependabot_auto_merge_workflow_fails(self) -> None:
        root = self.make_fixture()
        (root / ".github/workflows/dependabot-auto.yml").write_text(
            "name: dependabot auto merge\n"
            "jobs:\n"
            "  merge:\n"
            "    steps:\n"
            "      - run: gh pr merge --auto --squash\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "auto-merge path"):
            MODULE.validate(root)

    def test_migration_mapping_document_is_required(self) -> None:
        root = self.make_fixture()
        policy = root / "docs/maintenance/dependency-update-policy.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                "TypeScript 6 -> #255\n",
                "",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DependencyPolicyError, "TypeScript 6"):
            MODULE.validate(root)


if __name__ == "__main__":
    unittest.main()
