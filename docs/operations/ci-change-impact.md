# NEXOLAB change-impact CI and merge gate

## Purpose

NEXOLAB verifies the exact changed product surface instead of running the same expensive Core pipeline for every pull request. Optimization is fail-closed: unknown or risk-sensitive changes receive broader verification, never less verification by assumption.

The stable Core flow is:

```text
exact PR diff
    ↓
Change impact
    ↓
State integrity OR Quality and build
    ↓
NEXOLAB Merge Gate
    ↓
external exact-head PR workflow matrix (non-state PRs)
```

Specialized domain workflows keep their own repository path filters. For non-state pull requests, the stable merge gate waits for every other PR workflow that actually triggered on the same exact head and fails if any latest workflow run is not GREEN.

## Canonical state-only fast lane

A pull request is `state_only` only when every changed path is one of:

```text
.project/CURRENT_STATE.md
.project/ACTIVE_SPRINT.json
.project/BLOCKERS.md
.project/LAST_CHECKPOINT.json
```

The lane performs dependency-free State Model validation and exact diff checks. It deliberately does **not** install Node dependencies, run repository-wide ESLint/Vitest or create a Next.js production build because those product/runtime inputs did not change.

If any other file is present, the PR is not state-only.

Issue #648 / PR #649 is the real acceptance evidence for this lane:

- classifier = `state_only`;
- State integrity = PASS;
- Quality and build = SKIPPED;
- Node/npm/full frontend quality = NOT RUN;
- Merge Gate = PASS.

State Model v2 changes the _frequency_ of state-only PRs: they remain valid for material planning/evidence/schema changes but are no longer mandatory after every normal product merge.

## Documentation-only changes

Documentation is classified explicitly but remains on full `Quality and build` during the initial rollout. This preserves the repository Prettier contract until an equivalent deterministic lightweight formatting gate exists.

## Product and engineering changes

Frontend, backend, Device Agent, deployment/runtime, dependency/toolchain, security/supply-chain, CI-governance and cross-surface changes continue through full Core quality verification.

New or unknown paths fail closed into full Core verification.

## Change classes

The repository classifier reports one or more of:

- `state_only`;
- `docs_only`;
- `frontend`;
- `backend`;
- `device_agent`;
- `deployment_runtime`;
- `database_migration`;
- `dependency_toolchain`;
- `security_supply_chain`;
- `ci_governance`;
- `cross_surface_or_unknown`.

A class describes the changed surface. It does not replace specialized acceptance requirements from the Work Package.

## Node dependency installation

Core jobs that need the frontend graph use the committed lockfile through:

```bash
HUSKY=0 npm ci --no-audit --fund=false
```

GitHub Actions may cache npm download artifacts keyed by the lockfile and Node baseline. `node_modules` is not an authoritative cached source of truth.

## Merge-gate invariant

`NEXOLAB Merge Gate` always runs in Core CI.

It fails when:

- change classification failed;
- a state-only PR did not pass `State integrity`;
- a non-state PR did not pass `Quality and build`;
- a required Core lane was failed, cancelled, absent or unexpectedly skipped;
- a non-state change attempts to claim the lightweight lane;
- for a non-state PR, any latest external workflow run actually triggered on the exact PR head is failed, cancelled, skipped or otherwise non-successful;
- external exact-head workflows remain queued/in-progress beyond the bounded aggregation timeout.

The aggregator groups repeated runs by workflow and uses the latest run for the exact head. It excludes its own current Core workflow and requires a stable observation window before declaring the external matrix GREEN.

Software CI does not substitute for Raspberry Pi or real-hardware acceptance.

## Development cadence

During implementation:

1. make local commits freely;
2. run touched-file and targeted checks;
3. batch related review findings when safe;
4. publish a coherent PR candidate rather than every micro-fix;
5. use remote CI for candidate/final gates, not as the primary edit-test loop;
6. after the last code-affecting change, require one exact-head GREEN merge gate;
7. record durable exact-head evidence before merge when it materially changes project state;
8. after merge, query GitHub and continue to the next Work Package without an automatic reconciliation PR.

A state-only checkpoint does not invalidate anchored product/hardware evidence when no product/runtime path changed.

## Local candidate gate

Before pushing a coherent committed candidate, run:

```bash
python3 scripts/verify-local-candidate.py --base origin/main --candidate HEAD
```

`--base` defaults to `origin/main` and `--candidate` defaults to `HEAD`; both may be
any unambiguous local commit ref. The command resolves and reports both SHAs, computes
the exact `base...candidate` file set, and invokes `scripts/classify-ci-impact.py` from
a detached clean candidate worktree.

Canonical state-only candidates run the exact diff check and dependency-free project
state validator without installing Node dependencies. Other known candidates run the
local equivalent of Core Quality/build: CI-policy and repository-policy validation,
the exact Node baseline, deterministic `npm ci`, format, lint, typecheck, tests and the
production build. Unknown paths return `RED` rather than claiming incomplete local
evidence. Add `--include-compose-validation` when Compose contract validation is part
of the Work Package.

The final summary reports the resolved SHAs, impact classes, `fail_closed`, required
remote workflows, checks executed and `GREEN` or `RED`. A `GREEN` result is pre-push
evidence only; GitHub exact-head required CI and `NEXOLAB Merge Gate` remain
authoritative before merge.

## State Model v2 interaction

`State integrity` validates `schema_version: 2` through dependency-free tooling.

Current `main` HEAD, merge SHA and GitHub lifecycle are not canonical state invariants. See `docs/operations/project-state-model-v2.md`.

Changing state tooling/schema/governance itself is a CI-governance change and must receive full Core verification. Only exact four-file canonical state diffs receive the fast lane.

## Extending the classifier

When adding a new top-level repository area or verification-sensitive path:

1. classify it explicitly in `scripts/classify-ci-impact.py`;
2. add a regression case in `tests/test_ci_change_impact.py`;
3. choose the conservative required lane;
4. broaden verification if ownership is ambiguous;
5. never make an unknown path lightweight merely to reduce CI time.

When adding or changing a specialized PR workflow, preserve exact-head semantics and path filters.

## Branch protection

The target repository rule is:

- pull request required for normal changes to `main`;
- stable `NEXOLAB Merge Gate` required;
- force push disabled;
- direct feature push disabled;
- controlled administrative recovery remains exceptional and documented.

Repository-rule activation must be evidenced separately because changing GitHub repository settings is not the same operation as changing workflow code.
