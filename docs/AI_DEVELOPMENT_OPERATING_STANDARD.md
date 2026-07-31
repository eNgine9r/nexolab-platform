# AI Development Operating Standard

Version: 1.0  
Effective date: 2026-07-31

This document is the shared operating model for product planning, implementation, verification and continuity across ChatGPT, Codex, PowerShell and GitHub.

## 1. Core principle

The conversation is a working interface, not the permanent project memory.

The repository and GitHub are the source of truth:

- `PROJECT_PROFILE.yaml` — runtime and infrastructure constraints;
- `.project/CURRENT_STATE.md` — verified current state and next action;
- `.project/ACTIVE_SPRINT.json` — ordered, machine-readable Sprint queue;
- `.project/BLOCKERS.md` — unresolved blockers and required decisions;
- GitHub Issues — complete Work Packages;
- Pull Requests — reviewed implementation units;
- architecture decisions and runbooks — durable technical knowledge.

A new chat or Codex session must be able to resume work from these sources without reconstructing the whole conversation history.

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

Responsible for Issues, branches, Pull Requests, CI status, release evidence, versioned documentation and recovery after chat or agent interruption.

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

## 6. Autonomous Sprint Mode

The Sprint queue lives in `.project/ACTIVE_SPRINT.json`.

After each Work Package:

1. run targeted verification;
2. record result and changed scope;
3. update current state;
4. write the last checkpoint;
5. create/update a focused Pull Request when publishing is enabled;
6. continue to the next independent Ready task.

Continuity is implemented as a chain of small resumable sessions, not one unbounded conversation.

## 7. Blocker policy

### Soft blockers

Record the blocker, mark the affected task blocked and continue with an independent Ready task. Examples include optional credentials, unavailable noncritical services or a blocked dependency that does not affect other work.

### Hard blockers

Stop only for destructive production changes, data deletion, secret exposure, billing/DNS ownership changes, unsafe hardware writes, missing mandatory credentials, unresolved materially different product choices, inability to protect stable data/runtime, exhausted usage limits or no remaining independent Ready work.

Normal file edits, local tests, branches, commits, PR preparation, CI inspection and documentation updates are not hard blockers.

## 8. Verification ladder

During implementation: targeted tests and touched-file checks.

At Work Package completion: module tests, lint, typecheck/compile and migration consistency where applicable.

Before PR approval: integration tests, production build, security/isolation checks, browser/API verification, state and checkpoint update.

Before merge/release: required CI, local/offline runtime evidence, and rollback/recovery evidence for high-risk changes.

Never claim a check passed unless it actually ran against the referenced state.

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

## 11. Git and GitHub rules

- No direct feature work on `main`.
- No force push to protected branches.
- Branch names identify Issue/Work Package.
- PRs contain one logical change and link the Issue.
- Required checks are green before merge.
- Review conversations are resolved.
- Secrets and personal/production data never enter commits, logs or PR descriptions.

## 12. State continuity protocol

At session start:

1. read `PROJECT_PROFILE.yaml`;
2. read this standard;
3. read applicable `AGENTS.md` files;
4. read current state and active Sprint;
5. inspect linked Issues, PRs and current branch;
6. reconcile docs with code before claiming status.

At Work Package end:

- update task status;
- record checks/evidence;
- update current state and next action;
- record blockers;
- leave a recoverable commit/checkpoint.

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