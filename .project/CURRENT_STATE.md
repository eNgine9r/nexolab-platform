# NEXOLAB Current State

Updated: 2026-08-18

## Repository and accepted software baseline

The current accepted product baseline remains:

`60797b22e461e3078b535aaaf5b885411eb63aef`

This is the squash merge of PR #568 — **preserve LOCAL_LAN dashboard auth provider during controlled Raspberry Pi deployment**.

Current `main` repository revision before Issue #548 merge is:

`0829e758700385e15fa496e160790b061625ad94`

This revision includes the completed state-only reconciliation from Issue #569 / PR #570.

## Issue #548 / PR #559 — implementation GREEN, pre-merge state reconciliation

Issue #548 — **Add GitHub-aware safe Raspberry Pi update orchestration** is the active product Work Package on existing PR #559 and branch `feat/548-github-update-orchestration`.

The implementation exact head verified before this state-only update is:

`f068192268bed20afbd4890f20f4c52d21086f71`

That head is fully GREEN across all 13 triggered workflows:

- CI #3544 PASS;
- Telemetry service #1734 PASS;
- Offline Bundle #1461 PASS;
- Offline Auth Acceptance #590 PASS;
- Authenticated Dashboard Acceptance #2051 PASS;
- Device Agent Fleet Acceptance #921 PASS;
- Capacity Release Gate #728 PASS;
- Disaster Recovery Browser #912 PASS;
- Disaster Recovery TLS Fleet #862 PASS;
- MQTT TLS Fleet Acceptance #871 PASS;
- Broker Control Acceptance #832 PASS;
- Refrigeration Browser Acceptance #1859 PASS;
- Container Supply Chain #901 PASS.

The final implementation audit also confirms the branch is current with `main` (`behind_by=0`) and uses `0829e758...` as its merge base.

Implemented #548 boundaries include:

- GitHub is an optional update/maintenance plane only; LOCAL_LAN monitoring remains independent of internet availability;
- automatic updates are OFF by default and, when explicitly enabled, the host-local scheduled check is fixed at 02:00 without daytime catch-up;
- manual update discovery remains available regardless of the automatic policy state;
- the browser receives neither shell access nor GitHub credentials;
- only canonical `eNgine9r/nexolab-platform` / `main`, clean tracked worktrees and fast-forward lineage are eligible;
- the exact target SHA must have successful GitHub `CI` evidence from a `push` to `main`;
- a remote GitHub revision is discovery evidence only and never installation authority;
- activation requires an exact matching validated local package with digest, platform, schema and persistent-data compatibility gates;
- the existing version-manager queue remains the single mutation authority;
- capacity preflight runs against the canonical repository before backup or runtime mutation;
- PostgreSQL backup remains mandatory before runtime mutation;
- durable operation phases and safe progress messages survive the expected restart window;
- transient local Version API disconnects use bounded reconnect backoff before durable state is reread;
- post-update verification checks the exact runtime target, API/Dashboard, Device Agent workers and advancing telemetry;
- no destructive fallback, named-volume deletion, persistent-data deletion, Modbus/controller write or hardware write was added.

Offline Bundle acceptance on the implementation head proved that a transferred bundle can start with container egress blocked and pull disabled, and that update/rollback preserve persistent data.

Two pre-existing shell files appear as executable-bit-only diff noise with zero content changes; connector safety controls prevented a low-level mode-only rewrite. This has no runtime or product behavior impact and is recorded for merge review.

The four `.project` files are now being reconciled on PR #559. Because these state-only commits move the PR head, the final PR head must receive a fresh exact-head GREEN check set before PR #559 is marked Ready and merged.

## Current Raspberry Pi runtime

The Raspberry Pi checkout remains unchanged at:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Controlled deployment evidence remains:

`runtime/deployments/20260818T083157Z`

No Raspberry Pi deployment, service restart, hardware action or runtime mutation was performed during Issue #548 implementation or verification.

The previously deployed runtime reported `DEPLOYMENT PASSED` with `runtime_mode=lan`, healthy backend and Device Agent, and expected/active bus workers `1/1`. It still predates the repository-backed deployment-auth correction and #548 update orchestration.

## Issue #560 / #566 — permanent-fix Raspberry Pi acceptance still pending

Full runtime acceptance still requires a separately approved controlled Raspberry Pi deployment of the post-#548 merged `main`, followed by:

- successful local `administrator` login without manual `.env.local` correction;
- Energy Monitoring remaining active through at least one complete local access-token rotation window;
- protected history/consumption requests continuing to succeed;
- no recurrence of `401 invalid_bearer_token`;
- repository-backed evidence for the permanent dashboard auth provider contract;
- #548 update-plane runtime acceptance, including default-OFF policy, manual discovery, 02:00 scheduling behavior and safe local package activation/rollback evidence as applicable.

Do not claim #560/#566 or #548 Raspberry Pi runtime completion before that physical evidence exists.

## Existing validation lanes

- #566 / #560 permanent-fix Raspberry Pi token-rotation acceptance requires a separately approved deployment;
- #444 local user-management end-to-end acceptance remains `needs-validation`;
- #201 cumulative-energy normal operation is hardware verified; restart/power-cycle and rollover/reset/discontinuity evidence remain pending;
- #189 recovery acceptance remains hardware/evidence blocked;
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.

Future deployments must continue to run the capacity guard and may not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
