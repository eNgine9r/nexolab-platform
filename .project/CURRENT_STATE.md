# NEXOLAB Current State

Updated: 2026-08-22

## Repository baseline

Repository `main` is `19c053e0f197a4ccd925af19a6c40881ec56d348`, the GREEN squash merge of PR #647 implementing the repository-side portion of Issue #646.

The accepted product/runtime source remains `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`. PR #647 changed CI/governance, tests, documentation and project-state metadata only; it did not change NEXOLAB product/runtime behavior and therefore does not invalidate the previously anchored product evidence.

Production remains intentionally deployed from source `6e387485b68fb862d9f82ae7f6000b1f5b672764` using immutable frontend release `runtime/frontend-releases/6e387485b68fb862d9f82ae7f6000b1f5b672764-20260820T214127Z`, BUILD_ID `wb6SYt8RD2_XAcyPcyZP2`.

## Issue #646 repository-side implementation

Issue #646 — **Add change-impact CI orchestration and protected main merge gate** — remains open only because the real state-only acceptance and repository branch-protection settings must still be completed.

Repository-side implementation was merged through PR #647:

- final PR head: `623a72a0fdec8b8ddb15c5a7e145d0ba60a6a135`;
- squash merge: `19c053e0f197a4ccd925af19a6c40881ec56d348`;
- Core CI run `32567703388`: PASS;
- exact-head Telemetry service run `32567703424`: PASS;
- `NEXOLAB Merge Gate`: PASS after waiting for the external exact-head workflow;
- change impact on PR #647: `ci_governance`, full Core quality required;
- deterministic `npm ci --no-audit --fund=false`, formatting, lint, typecheck, tests and production build: PASS;
- no unresolved review threads or blocking review remained before merge.

Implemented behavior now in `main`:

- dependency-free deterministic changed-file classification;
- exact four-file canonical `state_only` fast lane;
- unknown/cross-surface changes fail closed to full Core verification;
- dependency-free project-state integrity validation;
- docs-only changes deliberately retain full Core quality during the conservative rollout;
- Node quality jobs use lockfile-enforcing `npm ci` plus npm download caching;
- stable `NEXOLAB Merge Gate` enforces the required Core lane;
- non-state PRs aggregate every other GitHub Actions PR workflow that actually triggered on the same exact head and remain non-GREEN until those workflows are GREEN.

## Active Work Package — Issue #648

Issue #648 — **Prove Issue #646 state-only fast lane after CI merge** — is the single active Work Package in branch `chore/648-prove-state-fast-lane`.

Its scope is exactly the four canonical state files:

- `.project/CURRENT_STATE.md`;
- `.project/ACTIVE_SPRINT.json`;
- `.project/BLOCKERS.md`;
- `.project/LAST_CHECKPOINT.json`.

This mandatory post-merge reconciliation is also the first real operational acceptance of the new fast lane. The PR must prove:

- `Change impact` reports exactly `state_only`;
- `State integrity` passes;
- `Quality and build` is skipped;
- Node setup, `npm ci`, repository-wide lint/Vitest and Next production build do not run;
- `NEXOLAB Merge Gate` passes from the state-only lane;
- no external product/runtime workflow is required by the state-only diff.

## Current blocker boundary

GitHub reports `main` as `protected: false` with required status-check enforcement off. The connected GitHub tool surface still does not expose a repository-rules/branch-protection mutation action. This remains a **soft access blocker** for the final #646 repository-settings acceptance criterion only.

Do not report branch protection as complete until repository settings are actually changed and verified. After #648 proves the fast lane, #646 may be marked blocked on this settings access while independent Ready work continues.

The remote `nexolab-edge-01` state is irrelevant to #648: no Raspberry Pi, Modbus or hardware acceptance is required for a canonical state-only reconciliation.

## Queue after #648

After #648 is GREEN and merged:

- record the state-only fast-lane evidence in #646;
- if repository-settings mutation remains unavailable, mark only the branch-protection portion of #646 blocked rather than blocking the Sprint;
- proceed to the separate planned **State Model v2 / automated reconciliation** Work Package;
- then return to the repository-backed product queue using delta Ready audits.

Independent product/validation lanes remain visible:

- #618 — Saved Dashboard CSV browser-download reliability;
- #607 — dual RS-485 KK1/KK2 software architecture prerequisite before #589;
- #589 — blocked on #607;
- #590 — blocked on #589;
- #585 — blocked pending explicit physical W2 / Unit 201 handback confirmation;
- #444 / #245 / #200 / #201 / #202 / #189 — explicit validation/hardware/recovery lanes.

Security maintenance remains time-bounded: the Issue #598 follow-up for four temporary `CVE-2026-14456` exceptions is due **2026-08-26** and must be rechecked before expiry or earlier if Debian publishes a fixed package or the reachability assumptions change.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
