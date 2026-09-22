# 2026-09-22 container expiry discovery gate repair

Issue: #1106.

## Problem

The container exception registry intentionally expired on 2026-09-21. On 2026-09-22, PR #1105 exact-head Container Supply Chain run `35703511465` correctly failed closed with `exceptions[0] expired on 2026-09-21`.

The workflow performed that expiry validation before image build and Trivy scanning. As a result, every evidence job was skipped and the repository could not obtain the fresh no-cache evidence required by its own exception-renewal runbook after the deadline had already been reached.

## Corrected workflow contract

The workflow is split into four acceptance phases:

1. `inventory` resolves the controlled image matrix and performs bounded secret-pattern screening.
2. `evidence` builds every exact-commit image with `pull: true` and `no-cache: true`, generates SBOMs and the full Trivy JSON report, and uploads raw candidate evidence.
3. `policy` downloads those fresh reports, validates the current exception registry, runs the existing policy regression suite, and evaluates every report against exact HIGH/CRITICAL policy.
4. `aggregate` and `publish` remain downstream of successful `policy`.

This allows an expired or stale registry to produce evidence for triage while keeping the workflow failed and non-publishable until the exact registry is accepted.

## Security boundary

- Expired exceptions remain invalid.
- No exception date is extended by #1106.
- New/unmatched HIGH findings remain blocking.
- CRITICAL findings remain unexceptable.
- Raw candidate manifests are not aggregate release evidence until `policy` passes.
- Publication still requires `policy` success.
- Production/runtime services are not changed.

## Follow-up

After #1106 is merged, use the repaired workflow to obtain fresh 2026-09-22 no-cache evidence and perform a separate tuple-by-tuple HIGH exception review. That review must remove stale findings and may retain an exact HIGH tuple only with current fix/reachability evidence and a new short expiry.
