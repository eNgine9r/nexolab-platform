# AI Development Operating Standard

Version: 1.2  
Effective date: 2026-08-22

This document is the shared operating model for product planning, implementation, verification and continuity across ChatGPT, Codex, PowerShell and GitHub.

## 1. Core principle

The conversation is a working interface, not permanent project memory.

The repository and GitHub together are the source of truth:

- `PROJECT_PROFILE.yaml` — runtime and infrastructure constraints;
- `.project/CURRENT_STATE.md` — durable offline-readable current planning/evidence summary;
- `.project/ACTIVE_SPRINT.json` — ordered machine-readable Sprint queue and durable evidence;
- `.project/BLOCKERS.md` — unresolved blockers and required decisions;
- `.project/LAST_CHECKPOINT.json` — recoverable execution checkpoint;
- GitHub Issues — complete Work Packages and current issue lifecycle when online;
- Pull Requests — reviewed implementation units and merge outcome when online;
- architecture decisions and runbooks — durable technical knowledge.

Repository state must remain sufficient to resume safely offline, but it must not duplicate volatile GitHub facts as timeless invariants.

## 2. Roles

### Product Owner — user

Responsible for product goals, business priority, workflow feedback, major product compromises, access to hardware/test data and approval of destructive or production-critical operations.

### ChatGPT — Team Lead / Senior / Architect

Responsible for discovery, technology and integration assessment, architecture, security boundaries, roadmap, Work Package preparation, sequencing, review and repository-state continuity.

### Codex — Implementation Engineer

Responsible for one scoped Work Package at a time, implementation, targeted verification, clean diffs and a recoverable checkpoint. Codex must not independently redefine product scope, architecture, data ownership or safety boundaries.

### PowerShell Sprint Runner — execution coordinator

Responsible for reading the active queue, selecting unblocked Ready work, launching scoped Codex sessions, recording logs/checkpoints and continuing after soft blockers.

### GitHub — durable control plane

Responsible for Issues, branches, Pull Requests, CI status, merge history, release evidence and recovery after chat or agent interruption.

## 3. Project profiles

Every project declares one primary profile in `PROJECT_PROFILE.yaml`:

- `CLOUD_SAAS`;
- `LOCAL_DESKTOP`;
- `LOCAL_LAN`;
- `HYBRID`.

The profile states development/runtime internet requirements, paid-service policy, operating systems, deployment/update model, data location, backup requirements and external integrations.

No mandatory runtime dependency may conflict with the profile.

## 4. Mandatory project gates

### Gate 0 — Product Discovery

Define problem, users, roles, workflows, MVP, out-of-scope, success criteria and constraints.

### Gate 1 — Technology and Integration Discovery

Evaluate authentication, database, storage, scheduling, monitoring, analytics, UI system, external APIs, realtime, AI, backup, restore, updates and local/free alternatives. Record each decision as `USE_NOW`, `PLAN_FOR_LATER`, `NOT_NEEDED` or `REJECTED`.

### Gate 2 — Architecture

Define system components, data ownership, contracts, roles, security boundaries, environments, failure recovery and rollback.

### Gate 3 — Roadmap

Use `Vision → Milestone → Epic → Sprint → Issue → Pull Request`. Plan vertical product slices instead of disconnected pages.

### Gate 4 — Implementation Readiness

A Work Package is Ready only with problem, outcome, current/expected behavior, scope, out-of-scope, dependencies, acceptance criteria, technical constraints, permitted directories, verification commands and Definition of Done.

### Gate 5 — Verification and Release

A task is not Done without required code, runtime and user-flow evidence.

## 5. Work-in-progress rules

- One primary vertical feature is active at a time.
- One critical bugfix may interrupt it.
- New ideas enter Backlog unless explicitly classified otherwise.
- One Issue maps to one branch and one focused Pull Request.
- Unrelated cleanup is not bundled into a feature PR.
- Architecture changes require a recorded decision.
- Local commits and targeted checks may be frequent; pushes that trigger expensive remote CI should represent a coherent candidate, not every micro-fix.
- After a remote review/CI cycle, batch related fixes when safe and rerun the smallest relevant local/targeted checks before publishing the next candidate.
- A final exact-head gate is required after the last code-affecting change. Do not repeatedly rerun a full matrix on unchanged product code merely to re-prove already anchored evidence.

## 6. Autonomous Sprint Mode

The Sprint queue lives in `.project/ACTIVE_SPRINT.json`.

For each Work Package:

1. run targeted verification during implementation;
2. publish one coherent PR candidate when ready;
3. collect exact-head verification/review/hardware evidence that is known before merge;
4. update the durable state/checkpoint when planning, blockers, baselines or evidence materially changed;
5. merge only on required GREEN checks;
6. query GitHub for the current merge/Issue result when online;
7. continue directly to the next independent Ready Work Package.

A dedicated post-merge state Issue/branch/PR is **not required** merely to record a new `main` SHA, squash merge SHA or GitHub Issue closure. Create a genuine state-only PR only when durable planning/evidence content materially changes.

Continuity is implemented as a chain of small resumable sessions, not one unbounded conversation.

## 7. Blocker policy

### Soft blockers

Record the blocker, mark the affected task blocked and continue with an independent Ready task. Examples include optional credentials, unavailable noncritical services or a blocked dependency that does not affect other work.

### Hard blockers

Stop only for destructive production changes, data deletion, secret exposure, billing/DNS ownership changes, unsafe hardware writes, missing mandatory credentials, unresolved materially different product choices, inability to protect stable data/runtime, exhausted usage limits or no remaining independent Ready work.

Normal file edits, local tests, branches, commits, PR preparation, CI inspection and documentation updates are not hard blockers.

## 8. Verification ladder and change-impact policy

During implementation: targeted tests and touched-file checks.

At Work Package completion: module tests, lint, typecheck/compile and migration consistency where applicable.

Before PR approval: integration tests, production build, security/isolation checks, browser/API verification and exact-head evidence.

Before merge/release: required CI, local/offline runtime evidence, and rollback/recovery evidence for high-risk changes.

Never claim a check passed unless it actually ran against the referenced state.

### Change-impact orchestration

Pull requests targeting `main` are classified from their exact changed-file set by repository-owned deterministic tooling. Verification must be proportional to the changed product surface and fail closed when classification is unknown or ambiguous.

Current policy:

- an exact canonical state-only diff under `.project/CURRENT_STATE.md`, `.project/ACTIVE_SPRINT.json`, `.project/BLOCKERS.md` and `.project/LAST_CHECKPOINT.json` uses the dependency-free state-integrity lane and must not install the frontend dependency graph;
- documentation-only changes remain on full repository quality until an equivalent deterministic dependency-free formatting gate exists;
- product, backend, Device Agent, deployment/runtime, dependency/toolchain, security/supply-chain and CI-governance changes retain full Core quality verification;
- cross-surface or previously unknown paths broaden verification rather than silently skipping checks;
- specialized browser/backend/edge/offline/security workflows keep their domain-specific path filters and exact-head semantics;
- for non-state PRs, the stable `NEXOLAB Merge Gate` requires the correct Core lane and waits for every other PR workflow actually triggered on the same exact head;
- state-only PRs use only the canonical state-integrity path because no product/runtime surface changed.

This policy optimizes verification selection; it does not reduce acceptance criteria. Software checks never substitute for required hardware/runtime evidence.

### Evidence anchoring

State Model v2 distinguishes:

- `accepted_product_sha` — latest accepted product/runtime source baseline;
- `deployed_product_sha` — source actually deployed;
- `verified_head_sha` — exact PR head to which review/CI evidence applies;
- `hardware_evidence_sha` — exact source physically accepted, when applicable;
- timestamped GitHub observations — optional snapshots such as merge SHA, current `main` HEAD or branch-protection state.

A future squash merge SHA is **not required** to complete repository-side Work Package evidence. GitHub is authoritative for merge status and merge SHA when online.

A state-only change does not invalidate already completed product/hardware evidence when no product/runtime path changed. Any product/runtime change after evidence was collected requires affected evidence to be rerun.

## 9. Offline readiness

For local and hybrid runtimes verify:

- offline installation package;
- startup without internet;
- local authentication;
- local database/storage;
- hardware communication;
- absence of mandatory CDN, cloud font, telemetry or external API calls;
- local logs and diagnostics;
- backup and restore;
- offline update and rollback;
- safe restart and power-loss behavior.

External AI/cloud functions must be optional and isolated unless a local runtime is provided.

## 10. Codex efficiency rules

- One session handles one Work Package.
- Use exact permitted directories and acceptance criteria.
- Read project state instead of replaying chat history.
- Run targeted checks before full suites.
- Resume from checkpoints instead of re-analyzing the repository.
- Do not ask Codex to fix everything.
- Use stronger reasoning only where justified.
- Do not attempt to bypass usage limits.
- Do not spend a Codex implementation session re-auditing unrelated backlog or architecture when the Work Package already provides the execution contract.
- Prefer one coherent implementation/review candidate over repeated remote pushes that only trigger the same expensive verification matrix.

## 11. Git and GitHub rules

- No direct feature work on `main`.
- No force push to protected branches.
- Branch names identify Issue/Work Package.
- PRs contain one logical change and link the Issue.
- Required checks are green before merge.
- Review conversations are resolved.
- Secrets and personal/production data never enter commits, logs or PR descriptions.
- `main` must be technically protected when repository capabilities permit it; normal merges must pass the stable required merge gate rather than relying only on operator discipline.
- A controlled administrative recovery path may exist, but it must not become the normal development path or a routine bypass around required verification.

## 12. State continuity protocol

State Model v2 separates durable offline state from volatile online observations.

### Durable state

Keep in version control:

- project/profile and Sprint identity;
- accepted/deployed baselines;
- active/next Work Package intent;
- blockers, safety and maintenance deadlines;
- final exact-head verification/review evidence;
- hardware/runtime evidence anchored to an exact SHA.

### Volatile observations

Current `main` HEAD, PR/Issue lifecycle, squash merge SHA and repository settings are queried from GitHub when online. If copied into repository state, they must live under explicit `observations` with `source`, `observed_at`, `kind` and `data`. They must not become invariants that force a follow-up commit.

### Session start

1. read `PROJECT_PROFILE.yaml`;
2. read this standard;
3. read applicable `AGENTS.md` files;
4. validate and read current state/Sprint/checkpoint;
5. inspect linked GitHub Issues, PRs and current branch when online;
6. reconcile observations with durable state before claiming current status.

### Work Package end

- record exact-head checks/evidence before merge when known;
- leave a recoverable checkpoint;
- merge only after required GREEN verification;
- use GitHub for current merge/Issue observations;
- run a delta Ready audit;
- start the next independent Ready Work Package without a mandatory reconciliation PR unless durable state materially changed.

Use dependency-free `scripts/project-state.py` / `scripts/validate-project-state.py` for deterministic state operations. Mutation commands must support dry-run and must never require network access.

Prefer delta Ready audits after normal Work Package completion. Run a full backlog/Ready audit when the queue is exhausted, architecture changes materially, a new critical defect changes priority, or Sprint boundaries change.

## 13. Standard result report

```text
Outcome
Scope completed
Files changed
Checks actually run
Runtime evidence
Open blockers
Risks
Next Ready Work Package
```

## 14. Instruction priority

1. current explicit user requirement;
2. safety, legal and data-protection constraints;
3. project `AGENTS.md` and accepted architecture decisions;
4. `PROJECT_PROFILE.yaml`;
5. this standard;
6. active Issue/Sprint;
7. existing code conventions;
8. general best practices.

Project-specific hardware, offline, security and domain rules remain authoritative.
