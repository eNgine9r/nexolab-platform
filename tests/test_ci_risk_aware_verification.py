from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = (ROOT / '.github/workflows/offline-bundle.yml').read_text(encoding='utf-8')
REFRIGERATION = (ROOT / '.github/workflows/refrigeration-browser-acceptance.yml').read_text(encoding='utf-8')
DASHBOARD = (ROOT / '.github/workflows/authenticated-dashboard-acceptance.yml').read_text(encoding='utf-8')
CORE = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
CLEAN_HELPER = ROOT / 'scripts/prepare-clean-verification-worktree.sh'


class RiskAwareVerificationContractTests(unittest.TestCase):
    def test_offline_bundle_does_not_trigger_for_generic_frontend_sources(self) -> None:
        trigger = OFFLINE.split('workflow_dispatch:', 1)[0]
        self.assertNotIn('- "src/**"', trigger)
        self.assertNotIn('- "public/**"', trigger)
        self.assertIn('- "src/app/api/**"', trigger)

    def test_refrigeration_browser_uses_explicit_refrigeration_e2e_paths(self) -> None:
        trigger = REFRIGERATION.split('workflow_dispatch:', 1)[0]
        self.assertNotIn('- "e2e/**"', trigger)
        self.assertIn('- "e2e/refrigeration-layout.production.e2e.ts"', trigger)

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
