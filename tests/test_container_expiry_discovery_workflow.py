from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/container-supply-chain.yml").read_text(encoding="utf-8")


def test_workflow_collects_fresh_scan_evidence_before_expiry_policy_gate() -> None:
    assert "  inventory:" in WORKFLOW
    assert "  evidence:" in WORKFLOW
    assert "    needs: inventory" in WORKFLOW
    assert "  policy:" in WORKFLOW
    assert "    needs: [inventory, evidence]" in WORKFLOW
    assert "Upload raw image evidence for policy review" in WORKFLOW
    assert "Download fresh image evidence" in WORKFLOW
    assert "Enforce vulnerability policy against fresh reports" in WORKFLOW
    assert "    needs: [policy, evidence]" in WORKFLOW
    assert "    needs: [inventory, policy]" in WORKFLOW

    evidence_section = WORKFLOW.split("  evidence:", 1)[1].split("  policy:", 1)[0]
    policy_section = WORKFLOW.split("  policy:", 1)[1].split("  aggregate:", 1)[0]
    assert "Generate vulnerability report" in evidence_section
    assert "Upload raw image evidence for policy review" in evidence_section
    assert "Validate supply-chain policy" not in evidence_section
    assert "evaluate-container-vulnerabilities.py" not in evidence_section
    assert "Validate supply-chain policy" in policy_section
    assert "evaluate-container-vulnerabilities.py" in policy_section


def test_container_publish_stays_downstream_of_acceptance_policy() -> None:
    publish_section = WORKFLOW.split("  publish:", 1)[1]
    assert "if: github.event_name == 'push'" in publish_section
    assert "needs: [inventory, policy]" in publish_section
    assert "fromJSON(needs.inventory.outputs.matrix)" in publish_section
