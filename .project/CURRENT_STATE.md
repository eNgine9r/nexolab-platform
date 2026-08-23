# NEXOLAB Current State

Updated: 2026-08-23

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle and merge SHA; a separate post-merge reconciliation PR is not required merely to copy volatile GitHub facts.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted product source includes Issue #590 / PR #657 operator acquisition-cadence controls. The Raspberry Pi deployment baseline remains intentionally older and must not be represented as containing #607/#589/#590 or later work until a controlled deployment actually occurs.

## Completed Work Package — Issue #590

Issue #590 — **Add operator acquisition cadence controls to NEXOLAB Settings** — merged through PR #657 as accepted product source `286a219611f95413b5580d8099a7c5665416d1ad`.

Hardware cadence acceptance remains **unverified** because the Remote Desktop/Raspberry Pi connector is offline. No software evidence is represented as physical KK1/KK2 acceptance.

## Completed Work Package candidate — Issue #615

Issue #615 — **Fix authenticated dashboard acceptance Compose project-name generation** — is software/tooling-complete in PR #658 and is awaiting final state-head verification/merge.

Exact implementation evidence is anchored to verified PR head `107935b7ab08ca48878b73603a6d1a9e683985f0`:

- dependency-free project-name regression tests: PASS `3/3` inside Core CI;
- Core CI `32607900557`: PASS — State Model/CI policy, standalone runtime contracts, ADR/dependency policy, format, lint, typecheck, full tests and production build;
- Authenticated Dashboard Acceptance `32607900561`: PASS — the real runner started the authenticated acceptance stack without a manual `COMPOSE_PROJECT_NAME` override and completed dashboard/acquisition-invariant acceptance;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero.

Implementation outcome:

- the generated UTC run suffix uses lowercase `t/z` separators accepted by Docker Compose project-name validation;
- explicit caller-provided `COMPOSE_PROJECT_NAME` remains byte-for-byte unchanged;
- PID-based per-run uniqueness remains intact;
- runner functional diff is one line;
- deterministic `test_ci_*.py` coverage executes the real runner bootstrap through project-name export;
- no dashboard acceptance semantics, product runtime, application Compose names, dependency graph, Modbus behavior or hardware behavior changed.

The final state-only PR head still must pass exact-head Core/Auth Dashboard aggregation and `NEXOLAB Merge Gate` before merge. Issue #615 is recorded completed in durable Sprint state because its implementation evidence is already GREEN; GitHub Issue closure remains merge-owned.

## Runtime and offline boundary

Issue #615 changes acceptance tooling only and does not alter the deployed NEXOLAB runtime. It introduces no internet/cloud runtime dependency.

The real Raspberry Pi connector remains offline. Hardware verification is not required for this repository-only tooling Work Package.

## Current blocker boundary

- #615: no product/software blocker; final state-head CI/merge remains pending.
- #607/#590: physical Raspberry Pi acceptance remains unavailable while the connector is offline.
- #646: technical `main` branch protection remains a soft access blocker; current GitHub observation still reports protection disabled.
- Security maintenance: temporary `CVE-2026-14456` exceptions remain due for review/removal by **2026-08-26** or earlier if fixed packages/reachability assumptions change.
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval.
- #444 and #245 remain validation lanes.
- #200 / #201 / #202 remain hardware/validation evidence lanes.
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. Issue #615 authorizes no Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency.
