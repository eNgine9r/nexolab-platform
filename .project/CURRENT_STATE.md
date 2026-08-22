# NEXOLAB Current State

Updated: 2026-08-22

## Repository baseline

Repository `main` is `bd2a0a56b8c3e67cdf960419076b154302da9e2f`, the GREEN state-only squash merge of PR #645 / Issue #644 after completion of Issue #633.

The accepted product/runtime source introduced by Issue #633 remains `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`. PR #645 changed only canonical `.project/**` state files, so it did not invalidate the #633 product verification anchored to final PR head `5d1f1f82ad555b68cab8ce9205283cf939d3be09` and Core CI run `32564575388`.

Production remains intentionally deployed from source `6e387485b68fb862d9f82ae7f6000b1f5b672764` using immutable frontend release `runtime/frontend-releases/6e387485b68fb862d9f82ae7f6000b1f5b672764-20260820T214127Z`, BUILD_ID `wb6SYt8RD2_XAcyPcyZP2`.

## Active Work Package — Issue #646

Issue #646 — **Add change-impact CI orchestration and protected main merge gate** — is active `status:in-progress` in branch `chore/646-impact-aware-ci`.

Latest code-affecting implementation commit before the repository-state checkpoint is `2ba35d01e51d5bea6c3b78edfa218438a1e9b0ac`.

Implemented on the feature branch:

- dependency-free deterministic changed-file classifier with explicit state/frontend/backend/Device Agent/deployment/migration/dependency/security/CI-governance classes;
- unknown paths fail closed to full Core quality rather than silently receiving a light lane;
- canonical state-only detection is restricted to the four repository state files;
- dependency-free project-state validator checks project/profile identity, Sprint/task integrity, proportional verification policy, canonical JSON shape and read-only safety boundary;
- Core CI now has `Change impact`, `State integrity`, `Quality and build`, and stable `NEXOLAB Merge Gate` jobs;
- state-only PRs skip Node setup/dependency installation, repository-wide lint/Vitest and Next production build;
- documentation-only changes deliberately remain on full Core quality until an equivalent dependency-free formatting gate exists;
- non-state and CI-governance changes remain on full Core quality during this conservative first rollout;
- Node quality jobs use lockfile-enforcing `npm ci --no-audit --fund=false` and npm download caching rather than generic `npm install`;
- for non-state PRs, `NEXOLAB Merge Gate` uses read-only GitHub Actions API access to wait for and aggregate every other PR workflow that actually triggered on the same exact head, failing on non-GREEN or bounded-timeout outcomes;
- repeated external runs are grouped by workflow and the latest exact-head run is authoritative, so an older failed attempt does not poison a later successful rerun;
- repository operating standard and CI runbook define coherent-candidate pushes, proportional verification, exact evidence SHA anchoring, exact-head workflow aggregation and delta Ready audits;
- classifier, project-state and workflow-matrix invariants have focused dependency-free Python regression tests.

No Pull Request has been opened yet. This is intentional: implementation, documentation and state/checkpoint work are being batched into one coherent candidate before triggering remote CI.

## Verification status

- #644 / PR #645: GREEN merged as `bd2a0a56...` after exact-head CI `32566870352` passed formatting, lint, typecheck, 121 test files / 555 tests and production build;
- #646 targeted GitHub CI has not run yet because the coherent candidate has not been published as a PR;
- the #646 workflow changes are CI-governance changes and therefore must pass the full pre-change-equivalent Core matrix on the PR head before merge;
- the first real state-only fast-lane proof will be the mandatory post-#646 state reconciliation after the implementation PR merges; no artificial test-only PR is required;
- specialized domain workflows keep their existing path filters and are not removed by #646;
- non-state merge-gate aggregation must prove that every actually triggered external exact-head PR workflow is GREEN before the stable gate succeeds;
- Raspberry Pi/hardware evidence is not required for CI orchestration; no production deployment/site cutover is in scope.

## Current blocker boundary

The connected GitHub tooling exposes repository/PR/CI/content operations but currently does not expose a branch-protection/rules mutation action. This is a soft access blocker only for the final repository-settings acceptance criterion. All repository-side #646 implementation and CI validation can proceed independently.

The remote `nexolab-edge-01` remains offline; this does not block #646 because no Raspberry Pi action is required.

## Queue after #646

After #646 implementation is GREEN and merged, its state-only reconciliation will serve as the real fast-lane acceptance. The next process-hardening package is the planned **State Model v2 / automated reconciliation** Work Package, kept separate from #646 so CI orchestration and state-model redesign do not share one PR.

After the process-hardening sequence, product work returns to the repository-backed queue, including:

- #618 — independent Saved Dashboard CSV browser-download reliability lane;
- #607 — dual RS-485 KK1/KK2 software architecture prerequisite before #589;
- #589 — blocked on #607;
- #590 — blocked on #589;
- #585 — blocked pending explicit physical W2 / Unit 201 handback confirmation;
- #444 / #245 / #200 / #201 / #202 / #189 — explicit validation/hardware/recovery lanes.

Security maintenance remains time-bounded: the Issue #598 follow-up for four temporary `CVE-2026-14456` exceptions is due **2026-08-26** and must be rechecked before expiry or earlier if Debian publishes a fixed package/reachability assumptions change.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
