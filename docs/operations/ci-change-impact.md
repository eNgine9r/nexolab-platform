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
```

Specialized domain workflows keep their own repository path filters and remain authoritative for the surfaces they cover.

## Initial rollout policy

### Canonical state-only fast lane

A pull request is `state_only` only when every changed path is one of:

```text
.project/CURRENT_STATE.md
.project/ACTIVE_SPRINT.json
.project/BLOCKERS.md
.project/LAST_CHECKPOINT.json
```

The lane performs dependency-free project-state validation and exact diff checks. It deliberately does **not** install Node dependencies, run repository-wide ESLint/Vitest or create a Next.js production build because those product/runtime inputs did not change.

If any other file is present, the PR is not state-only.

### Documentation-only changes

Documentation is classified explicitly but remains on full `Quality and build` during the initial rollout. This preserves the repository Prettier contract until an equivalent deterministic lightweight formatting gate exists.

### Product and engineering changes

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

A class describes the changed surface. It does not by itself replace specialized acceptance requirements from the Work Package.

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
- a non-state change attempts to claim the lightweight lane.

The gate intentionally does not convert software CI into Raspberry Pi or real-hardware acceptance. Hardware/runtime evidence remains separately anchored to the exact source that was physically tested.

## Development cadence

During implementation:

1. make local commits freely;
2. run touched-file and targeted checks;
3. batch related review findings when safe;
4. publish a coherent PR candidate rather than every micro-fix;
5. use remote CI for candidate/final gates, not as the primary edit-test loop;
6. after the last code-affecting change, require one exact-head GREEN merge gate.

A later state-only checkpoint does not invalidate already anchored product/hardware evidence if the diff proves no product/runtime path changed.

## Extending the classifier

When adding a new top-level repository area or verification-sensitive path:

1. classify it explicitly in `scripts/classify-ci-impact.py`;
2. add a regression case in `tests/test_ci_change_impact.py`;
3. choose the conservative required lane;
4. broaden verification if ownership is ambiguous;
5. never make an unknown path lightweight merely to reduce CI time.

## Branch protection

The target repository rule is:

- pull request required for normal changes to `main`;
- stable `NEXOLAB Merge Gate` required;
- force push disabled;
- direct feature push disabled;
- controlled administrative recovery remains exceptional and documented.

Repository-rule activation must be evidenced separately because changing GitHub repository settings is not the same operation as changing workflow code.
