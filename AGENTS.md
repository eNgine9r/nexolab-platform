<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# NEXOLAB Agent Operating Rules

These rules apply to ChatGPT, Codex and other implementation agents working in this repository.

## Required reading before work

1. `PROJECT_PROFILE.yaml`;
2. `docs/AI_DEVELOPMENT_OPERATING_STANDARD.md`;
3. `.project/CURRENT_STATE.md`;
4. `.project/ACTIVE_SPRINT.json`;
5. `.project/BLOCKERS.md`;
6. applicable ADRs and operations runbooks;
7. the linked GitHub Issue and current branch diff.

Do not infer project state from chat history when repository-backed state exists.

## Product and runtime identity

NEXOLAB is an industrial IoT laboratory-monitoring platform with a `LOCAL_LAN` primary profile.

Hard runtime constraints:

- development may use internet;
- core production runtime must not require internet;
- core runtime must not require paid cloud services;
- local PostgreSQL, local MQTT and edge SQLite continuity remain first-class;
- online/cloud functions must be optional and isolated;
- offline installation, operation, backup, restore, update and rollback must be testable.

## Safety rules

- Never perform Modbus write operations.
- Never add a hidden write path to discovery, test or production tools.
- Use stable `/dev/serial/by-id/...` device paths for production hardware.
- Do not perform a production/site cutover unless the Work Package explicitly scopes it and the user approves it.
- Do not delete persistent volumes, production data or evidence.
- Never use `docker compose down -v` in operational procedures.
- Missing real-hardware evidence must be reported as unverified, never assumed to pass.
- Stale telemetry must never be shown as live.
- Demo data must never silently replace a failed live path.

## Work Package discipline

- One GitHub Issue maps to one branch and one focused Pull Request.
- Implement one scoped Work Package at a time.
- Plan vertical operator outcomes across UI, API, data, edge, deployment and recovery where required.
- Do not jump between pages or subsystems without a dependency recorded in the Issue.
- Respect permitted directories and explicit out-of-scope boundaries.
- New ideas go to Backlog unless classified as a critical defect or approved architecture change.
- Update `.project/CURRENT_STATE.md` and `.project/LAST_CHECKPOINT.json` before ending a Work Package.

## Architecture principles

Preserve existing repository principles unless an accepted ADR changes them:

- offline-first edge acquisition;
- local SQLite outbox for temporary central/MQTT outages;
- MQTT QoS 1 delivery;
- explicit demo and live modes;
- typed REST and WebSocket contracts with runtime validation;
- newest `captured_at` wins;
- repeated `event_id` values are deduplicated;
- PostgreSQL migrations complete before readiness;
- PostgreSQL is not exposed unnecessarily to the host/network;
- persistent data survives container recreation and rollback;
- MQTT, PostgreSQL, backend and WebSocket failures remain independently diagnosable;
- critical UI states use text/icon signals, not color alone.

## Offline dependency gate

Before introducing a dependency, determine whether it is:

- local and mandatory;
- optional online with a clear offline state;
- development-only;
- prohibited because it makes core runtime depend on internet or payment.

Do not add mandatory CDN assets, remote fonts, external telemetry, cloud authentication, online license checks or external APIs to the core runtime.

## Verification

Run the smallest relevant checks first. The repository verification entry point is:

```powershell
./scripts/verify-project.ps1 -Component All
```

Use `-IncludeComposeValidation` when Compose contracts are affected.

Software checks do not replace:

- real-device Modbus read evidence;
- offline startup evidence;
- MQTT/central outage evidence;
- backup and restore evidence;
- power-loss/restart evidence;
- controlled deployment and rollback evidence.

Only claim checks that actually ran against the referenced commit/environment.

## Autonomous continuation

Normal repository inspection, file edits, local tests, feature branches, commits, PR preparation, CI inspection and documentation updates do not require repeated user confirmation.

If a task encounters a soft blocker:

1. record it in `.project/BLOCKERS.md`;
2. mark the task blocked;
3. continue with another independent Ready Work Package.

Stop only for the hard blockers declared in `PROJECT_PROFILE.yaml` and the operating standard, including unsafe hardware actions, destructive data operations, site cutover, missing mandatory access, materially different product decisions or exhausted usage limits.

## Product Owner autonomous execution authorization (recorded 2026-11-22)

The Product Owner explicitly authorized autonomous completion of the **XWEB Advanced Chart System programme** (WP-A … WP-J, tracked from #1643 onward). Within that programme, agents may, without asking again:

- create/update GitHub Issues and feature branches, commit, push, open and review Pull Requests;
- fix CI failures and **merge** a Pull Request into `main` when all of these hold: every required exact-head check is GREEN including NEXOLAB Merge Gate, the branch is up to date with `main`, the final diff was reviewed, acceptance criteria are met, no unresolved review threads or blocking defects remain, and project-state/checkpoint integrity passes (`scripts/validate-project-state.py`);
- synchronize local `main` after merging, update Sprint state/checkpoints, and begin the next Ready Work Package.

This authorization does **not** lift any safety boundary: no Modbus/hardware writes, no Raspberry Pi / site production cutover or release activation without separate approval, no destructive data operations, no secret handling, no billing/DNS change, no bypass of RBAC, tool permissions or CI gates. Stop only for the hard blockers in `PROJECT_PROFILE.yaml`. Missing real-hardware or site evidence must still be reported as unverified.

## Required completion report

Every completed Work Package must report:

```text
Outcome
Scope completed
Files changed
Checks actually run
Offline and hardware evidence
Open blockers
Risks
Next Ready Work Package
```
