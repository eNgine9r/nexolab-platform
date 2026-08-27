from __future__ import annotations

import fnmatch
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "authenticated-dashboard-acceptance.yml"
PLAYWRIGHT_CONFIG = ROOT / "playwright.dashboard.config.ts"


def _pull_request_paths() -> set[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  pull_request:\n.*?^    paths:\n(?P<paths>(?:^      - .+\n)+)", text)
    if not match:
        raise AssertionError("Authenticated Dashboard pull_request.paths block not found")
    return {line.strip()[2:].strip().strip('"') for line in match.group("paths").splitlines()}


class AuthenticatedDashboardTriggerPathTests(unittest.TestCase):
    def test_canonical_chart_sources_trigger_dashboard_acceptance(self) -> None:
        paths = _pull_request_paths()
        self.assertIn("src/features/charts/**", paths)
        self.assertIn("src/components/charts/**", paths)

    def test_canonical_chart_e2e_files_are_routed_and_executed(self) -> None:
        paths = _pull_request_paths()
        config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
        for relative in (
            "e2e/live-chart-system.production.e2e.ts",
            "e2e/equipment-multi-axis-chart.production.e2e.ts",
        ):
            self.assertTrue(any(fnmatch.fnmatchcase(relative, pattern) for pattern in paths))
            self.assertIn(f'"{Path(relative).name}"', config)

    def test_existing_dashboard_path_is_preserved_without_broad_state_or_docs_trigger(self) -> None:
        paths = _pull_request_paths()
        self.assertIn("src/components/live/**", paths)
        self.assertNotIn(".project/**", paths)
        self.assertNotIn("docs/**", paths)


if __name__ == "__main__":
    unittest.main()
