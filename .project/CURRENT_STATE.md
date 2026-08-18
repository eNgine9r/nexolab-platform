# NEXOLAB Current State

Updated: 2026-08-18

## Accepted product baseline

The current accepted NEXOLAB product baseline is:

`9732b68b0d14e4056e5773e0a9bec3f3741e267f`

This is the squash merge of PR #559 — **feat: add safe GitHub update discovery plane**, closing Issue #548.

Post-merge project-state reconciliation PR #572 was merged at:

`0339bef188ac482a6b77450c3b14861dc58ed29e`

State-only commits after the accepted product merge do not change the accepted product baseline.

Final PR #559 exact-head verification was performed on:

`76120bef1108086fdc1648cddbcf9bd293502e6e`

All 13 triggered PR workflows were GREEN on that exact head:

- CI #3548 PASS;
- Telemetry service #1738 PASS;
- Offline Bundle #1465 PASS;
- Offline Auth Acceptance #594 PASS;
- Authenticated Dashboard Acceptance #2055 PASS;
- Device Agent Fleet Acceptance #925 PASS;
- Capacity Release Gate #732 PASS;
- Disaster Recovery Browser #916 PASS;
- Disaster Recovery TLS Fleet #866 PASS;
- MQTT TLS Fleet Acceptance #875 PASS;
- Broker Control Acceptance #836 PASS;
- Refrigeration Browser Acceptance #1863 PASS;
- Container Supply Chain #905 PASS.

State-only PR #572 exact-head CI #3550 also passed format, lint, typecheck, tests and production build before merge.

## Issue #548 / PR #559 — software merged, Raspberry Pi acceptance pending

Issue #548 is closed with `status:done` and PR #559 is merged.

The merged software adds the bounded GitHub-aware maintenance plane while preserving the LOCAL_LAN/offline-first architecture:

- GitHub remains optional update-plane only and is not required for monitoring runtime;
- automatic updates are OFF by default;
- when enabled, the scheduled host-local check is fixed at 02:00 with no daytime catch-up;
- manual discovery remains available with automatic updates ON or OFF;
- the browser receives neither shell access nor GitHub credentials;
- only canonical `eNgine9r/nexolab-platform` / `main`, clean tracked worktrees and fast-forward lineage are eligible;
- exact successful main-branch `CI` evidence is required for the target SHA;
- remote GitHub revision discovery is never installation authority;
- activation requires an exact matching validated local package plus digest/platform/schema/persistent-data compatibility gates;
- the existing version-manager queue remains the single mutation authority;
- capacity preflight runs against the canonical repository before backup or runtime mutation;
- PostgreSQL backup remains mandatory before runtime mutation;
- durable progress state and bounded local reconnect preserve the same operation across expected restart;
- final success requires exact target/runtime identity, API/Dashboard readiness, Device Agent workers and advancing telemetry evidence;
- no destructive fallback, named-volume deletion, product-data deletion, Modbus/controller write or hardware write was added.

Offline Bundle acceptance proved disconnected startup with pull disabled and container egress blocked, plus update/rollback preservation of persistent data.

## Current Raspberry Pi runtime

The Raspberry Pi remains unchanged at:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Controlled deployment evidence remains:

`runtime/deployments/20260818T083157Z`

No Raspberry Pi deployment, service restart, host package installation, hardware action or runtime mutation was performed during Issue #548 implementation, verification, merge or state reconciliation.

The deployed runtime therefore predates the repository-backed deployment-auth correction and the merged #548 update orchestration.

## Current execution boundary

Issue #571 / PR #572 state reconciliation is completed.

The next product-relevant Work Package is Issue #566: controlled deployment of the merged NEXOLAB product baseline to Raspberry Pi and combined #566/#560/#548 runtime acceptance.

This Work Package is currently **hard blocked waiting for separate explicit user approval**. No Raspberry Pi action is authorized before that approval.

The controlled acceptance should prove where practical:

- repository-backed local `administrator` login without manual `.env.local` correction;
- Energy Monitoring continuity through at least one complete local access-token rotation window;
- protected history/consumption requests continue to succeed;
- no recurrence of `401 invalid_bearer_token`;
- #548 automatic-update policy defaults OFF on the host;
- manual update discovery works without making GitHub a runtime dependency;
- 02:00 scheduler/policy installation and host-local semantics are present;
- version-management package validation, capacity, backup, runtime verification and rollback evidence behave truthfully;
- actual Raspberry Pi runtime identity, API/Dashboard readiness, Device Agent health and telemetry freshness are captured.

Do not claim #566/#560 or #548 Raspberry Pi runtime completion before that physical evidence exists.

## Existing validation lanes

- #566 / #560 post-merge Raspberry Pi deployment and token-rotation acceptance: waiting for explicit approval;
- #444 local user-management end-to-end acceptance remains `needs-validation`;
- #201 cumulative-energy normal operation is hardware verified; restart/power-cycle and rollover/reset/discontinuity evidence remain pending;
- #189 recovery acceptance remains hardware/evidence blocked;
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.

Future deployments must continue to run the capacity guard and may not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
