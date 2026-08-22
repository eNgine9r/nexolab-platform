# NEXOLAB Current State

Updated: 2026-08-22

## State Model v2 boundary

NEXOLAB repository continuity now uses a **durable state + online observations** model.

Durable repository state records facts that remain meaningful in an offline checkout:

- project/profile and Sprint identity;
- accepted product source;
- deployed product source;
- active/next Work Package intent;
- immutable exact-head verification and hardware evidence;
- blockers, maintenance deadlines and safety boundaries.

Current GitHub facts such as `main` HEAD, Issue/PR open/merged state, squash merge SHA and branch-protection state are **not durable invariants**. GitHub is authoritative for those facts when online. If a repository snapshot records one, it is a timestamped observation and never a reason by itself to create another reconciliation PR.

This removes the self-referential cycle where every product merge required a second state Issue/branch/PR just to record the merge.

## Durable baselines

Accepted product source: `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

These identities are intentionally distinct from repository `main` and from state/checkpoint commits.

## Active Work Package — Issue #650

Issue #650 — **Introduce State Model v2 and remove mandatory post-merge reconciliation PRs** — is active in branch `chore/650-state-model-v2`.

The package introduces:

- `schema_version: 2` for canonical machine-readable state;
- dependency-free validation that rejects volatile repository/GitHub facts as durable invariants;
- explicit timestamped `observations` for optional GitHub snapshots;
- deterministic local state tooling for migration, Work Package selection, exact-head evidence, checkpointing and completion;
- completion semantics based on final verified PR head evidence rather than a future merge SHA;
- operating rules allowing the next Work Package to start directly after a GREEN merge when no material planning/state change is needed.

## Preserved evidence

Issue #606 retains final software head `83abc9b4a0056a2709c33a627b203785eeefff79`, hardware-accepted head `804d0b44045a5099c59149c87b70cbf63ca047f8`, PR #632 and the `PASS_22_OF_22` exact-head workflow result.

Issue #633 retains final verified head `5d1f1f82ad555b68cab8ce9205283cf939d3be09`, PR #643 and Core CI `32564575388`. Raspberry Pi post-deployment acceptance remains `UNVERIFIED_PI_OFFLINE`.

Issue #646 retains final verified head `623a72a0fdec8b8ddb15c5a7e145d0ba60a6a135`, PR #647, Core CI `32567703388`, external Telemetry CI `32567703424`, and the GREEN merge-gate evidence.

Issue #648 retains exact state-proof head `d5a1d57de876a94bb90449ad5cb4e21ba1b6e7ee`, PR #649 and Core CI `32568953282`: `state_only`, State integrity PASS, Quality and build SKIPPED, Node/npm/full frontend quality NOT RUN, Merge Gate PASS.

Historical merge SHAs are preserved only in timestamped GitHub observations, not as durable lifecycle requirements.

## Current blocker boundary

Issue #646 is soft-blocked only on repository settings. A GitHub observation captured on 2026-08-22 reports `main` as unprotected with required status checks disabled, while the connected GitHub tool surface exposes no branch-protection/rules mutation action.

This settings blocker does not stop independent Work Packages.

Known product/validation dependencies remain:

- #589 blocked on #607 dual RS-485 architecture;
- #590 blocked on #589;
- #585 blocked pending explicit physical W2 / Unit 201 handback approval;
- #444 and #245 remain validation lanes;
- #200 / #201 / #202 remain hardware/validation evidence lanes;
- #189 remains blocked on controlled actual-host recovery evidence.

Security maintenance remains time-bounded: the four temporary `CVE-2026-14456` exceptions from Issue #598 are due for review/removal by **2026-08-26**, or earlier if a fixed Debian package becomes available or reachability assumptions change.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
