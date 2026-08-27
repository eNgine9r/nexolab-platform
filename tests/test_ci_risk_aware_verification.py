from __future__ import annotations

import fnmatch
import importlib.util
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = (ROOT / '.github/workflows/offline-bundle.yml').read_text(encoding='utf-8')
REFRIGERATION = (ROOT / '.github/workflows/refrigeration-browser-acceptance.yml').read_text(encoding='utf-8')
DASHBOARD = (ROOT / '.github/workflows/authenticated-dashboard-acceptance.yml').read_text(encoding='utf-8')
CORE = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
CLEAN_HELPER = ROOT / 'scripts/prepare-clean-verification-worktree.sh'

SPEC = importlib.util.spec_from_file_location('classify_ci_impact', ROOT / 'scripts/classify-ci-impact.py')
assert SPEC and SPEC.loader
CLASSIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLASSIFIER)
classify = CLASSIFIER.classify


def pull_request_paths(workflow_text: str) -> list[str]:
    paths: list[str] = []
    in_paths = False
    for line in workflow_text.splitlines():
        if line == '    paths:':
            in_paths = True
            continue
        if not in_paths:
            continue
        if line.startswith('      - "') and line.endswith('"'):
            paths.append(line[len('      - "'):-1])
            continue
        if line.startswith('  workflow_dispatch:'):
            break
        if line and not line.startswith('      '):
            break
    return paths


class RiskAwareVerificationContractTests(unittest.TestCase):
    def test_all_known_tracked_routes_have_matching_workflow_trigger_coverage(self) -> None:
        workflow_paths = {
            'Authenticated Dashboard Acceptance': pull_request_paths(DASHBOARD),
            'Offline Bundle': pull_request_paths(OFFLINE),
            'Refrigeration Browser Acceptance': pull_request_paths(REFRIGERATION),
        }
        tracked = subprocess.check_output(
            ['git', 'ls-files'], cwd=ROOT, text=True
        ).splitlines()
        mismatches: list[tuple[str, str]] = []
        for path in tracked:
            result = classify([path])
            if result['fail_closed']:
                continue
            for required in result['verification']['required_external_workflows']:
                patterns = workflow_paths.get(required)
                if patterns is None:
                    continue
                if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
                    mismatches.append((path, required))
        self.assertEqual(mismatches, [])

    def test_offline_bundle_does_not_trigger_for_generic_frontend_sources(self) -> None:
        trigger = OFFLINE.split('workflow_dispatch:', 1)[0]
        self.assertNotIn('- "src/**"', trigger)
        self.assertNotIn('- "public/**"', trigger)
        self.assertIn('- "src/app/api/**"', trigger)

    def test_refrigeration_browser_uses_explicit_refrigeration_e2e_paths(self) -> None:
        trigger = REFRIGERATION.split('workflow_dispatch:', 1)[0]
        self.assertNotIn('- "e2e/**"', trigger)
        self.assertIn('- "e2e/refrigeration*.production.e2e.ts"', trigger)

    def test_dashboard_trigger_covers_settings_feature_domain(self) -> None:
        trigger = DASHBOARD.split("workflow_dispatch:", 1)[0]
        self.assertIn('- "src/features/settings/**"', trigger)

    def test_dashboard_trigger_includes_next_runtime_config(self) -> None:
        trigger = DASHBOARD.split("workflow_dispatch:", 1)[0]
        self.assertIn('- "next.config.ts"', trigger)

    def test_authenticated_dashboard_routes_exact_pr_diff_before_acceptance(self) -> None:
        self.assertIn('name: Resolve dashboard verification route', DASHBOARD)
        self.assertIn('scripts/classify-ci-impact.py', DASHBOARD)
        self.assertIn('NEXOLAB_DASHBOARD_TEST_MATCH:', DASHBOARD)
        self.assertIn('needs.route.outputs.test_match', DASHBOARD)

    def test_core_merge_gate_passes_required_external_workflow_contract(self) -> None:
        self.assertIn('required_external_workflows:', CORE)
        self.assertIn('REQUIRED_EXTERNAL_WORKFLOWS:', CORE)
        self.assertIn('--required-workflows-json "$REQUIRED_EXTERNAL_WORKFLOWS"', CORE)

    def test_clean_candidate_helper_uses_detached_git_worktree(self) -> None:
        self.assertTrue(CLEAN_HELPER.is_file())
        helper = CLEAN_HELPER.read_text(encoding='utf-8')
        self.assertIn('worktree add --detach', helper)
        self.assertIn('status --porcelain', helper)
        self.assertNotIn('runtime/evidence', helper)


if __name__ == '__main__':
    unittest.main()
