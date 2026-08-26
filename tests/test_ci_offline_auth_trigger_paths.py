from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "offline-auth-acceptance.yml"
RUNNER = ROOT / "scripts" / "run-offline-auth-acceptance.sh"


def _pull_request_paths() -> set[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  pull_request:\n.*?^    paths:\n(?P<paths>(?:^      - .+\n)+)", text)
    if not match:
        raise AssertionError("Offline Auth pull_request.paths block not found")
    return {line.strip()[2:].strip().strip('\"') for line in match.group("paths").splitlines()}


class OfflineAuthTriggerPathTests(unittest.TestCase):
    def test_all_executed_browser_acceptance_files_are_routed(self) -> None:
        paths = _pull_request_paths()
        runner = RUNNER.read_text(encoding="utf-8")
        for relative in (
            "e2e/local-auth.production.e2e.ts",
            "e2e/local-auth-persistence.production.e2e.ts",
            "e2e/settings-version.production.e2e.ts",
        ):
            self.assertIn(relative, paths)
            self.assertIn(relative, runner)

    def test_existing_security_and_backend_routes_are_preserved(self) -> None:
        paths = _pull_request_paths()
        self.assertIn("services/telemetry-service/**", paths)
        self.assertIn("src/features/security/**", paths)
        self.assertIn("scripts/run-offline-auth-acceptance.sh", paths)

    def test_narrow_routing_does_not_expand_to_generic_state_or_docs(self) -> None:
        paths = _pull_request_paths()
        self.assertNotIn(".project/**", paths)
        self.assertNotIn("docs/**", paths)


if __name__ == "__main__":
    unittest.main()
