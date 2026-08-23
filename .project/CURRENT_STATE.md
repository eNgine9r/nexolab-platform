# NEXOLAB Current State

Updated: 2026-08-23

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle and merge SHA; a separate post-merge reconciliation PR is not required merely to copy volatile GitHub facts.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted source includes Issue #590 / PR #657 operator acquisition-cadence controls. The Raspberry Pi deployment baseline is intentionally older and must not be represented as containing #607/#589/#590 or later work until a controlled deployment actually occurs.

## Completed Work Package — Issue #590

Issue #590 — **Add operator acquisition cadence controls to NEXOLAB Settings** — merged through PR #657 as accepted source `286a219611f95413b5580d8099a7c5665416d1ad`.

Exact product evidence remains anchored to verified head `b4b8608d82e90844ae9905c60b083232e68ef689`; the final PR head `a2e0b4b73a9acfff599bd58ac3ebea179c2c942d` added durable state only and also passed the full exact-head matrix and `NEXOLAB Merge Gate` before merge.

Hardware cadence acceptance remains **unverified** because the Remote Desktop/Raspberry Pi connector is offline. No software evidence is represented as physical KK1/KK2 acceptance.

## Active Work Package — Issue #615

Issue #615 — **Fix authenticated dashboard acceptance Compose project-name generation** — is active in `fix/615-dashboard-compose-project-name`.

Repository-backed defect:

- the acceptance runner generated `RUN_SUFFIX` with uppercase `T`/`Z`;
- Docker Compose project names are lowercase-compatible only;
- callers previously needed a manual lowercase `COMPOSE_PROJECT_NAME` override to bypass the runner defect.

Current focused candidate:

- changes only the generated timestamp separators from `T/Z` to `t/z`;
- leaves explicit caller-provided `COMPOSE_PROJECT_NAME` untouched;
- retains PID-based per-run uniqueness;
- adds dependency-free `test_ci_*.py` coverage that executes the real runner bootstrap up to project-name export, proves the generated Compose-compatible shape, proves two runs are distinguishable and proves explicit override preservation;
- does not change dashboard acceptance coverage, product runtime, Compose application names, dependency graph, Modbus behavior or hardware behavior.

The candidate is **not accepted yet**. Targeted checks and exact-head PR CI still need to run. A minor EOF-newline-only diff artifact in the runner must be removed before final review so the product change remains a true one-line functional edit.

## Runtime and offline boundary

Issue #615 changes acceptance tooling only. It does not alter the NEXOLAB deployed runtime or require internet/cloud services at runtime.

The real Raspberry Pi connector remains offline; this is not a blocker for repository-side #615 implementation or CI evidence.

## Current blocker boundary

- #615: no software hard blocker; required verification remains pending.
- #607/#590: physical Raspberry Pi acceptance remains unavailable while the connector is offline.
- #646: technical `main` branch protection remains a soft access blocker; current GitHub observation still reports protection disabled.
- Security maintenance: temporary `CVE-2026-14456` exceptions remain due for review/removal by **2026-08-26** or earlier if fixed packages/reachability assumptions change.
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval.
- #444 and #245 remain validation lanes.
- #200 / #201 / #202 remain hardware/validation evidence lanes.
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. Issue #615 authorizes no Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency.
