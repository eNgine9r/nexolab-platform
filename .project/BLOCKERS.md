# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #267 — Equipment and metrology registry

PR #268 was squash-merged into `main` as `2f3c1ebcff3d19558ed4d2b5818f7bdd48b0dfae` after a clean final audit.

Final verified head `b40faeb7999acea0f3e3ae2105bbd77b122add2d`:

- CI `30929890208` GREEN;
- Authenticated Dashboard Acceptance `30929890332` GREEN;
- Refrigeration Browser Acceptance `30929890463` GREEN;
- Offline Bundle `30929890230` GREEN;
- inline review threads: zero;
- submitted reviews: zero;
- focused files: 15;
- branch behind `main`: zero commits.

Issue #267 has no remaining software blocker. Physical Raspberry Pi and RS-485 acceptance remains separate and explicitly unverified.

## Issue #269 — operator-safe Settings workspace

No product, architecture or repository-access blocker prevents implementation from starting.

Verified repository boundary:

- `/settings` is currently a pure placeholder;
- authenticated identity, organization, roles and permissions are available from the existing session contract;
- client-visible data/auth mode and API/WebSocket configuration already exist in runtime modules;
- no `/api/v1/settings` endpoint exists;
- no persisted universal settings table exists;
- no safe generic mutation contract exists for organization, memberships, nodes, devices, retention, security or deployment.

The Ready slice is therefore constrained to:

- read-only organization and operator context;
- sanitized runtime/deployment diagnostics;
- explicit ready, incomplete and unsafe configuration states;
- versioned browser-local presentation preferences;
- canonical links to existing workflows;
- honest unsupported-configuration messaging.

## Residual risks, not blockers

- Public runtime variables are client-visible by design, but displayed URLs still require sanitization to remove credentials, query strings, fragments and secret-like values.
- Runtime configuration modules were created per feature; Issue #269 may need a narrow shared read-only adapter, but must not trigger a broad runtime-config refactor.
- Browser-local preferences must recover deterministically from malformed or obsolete storage without affecting acquisition, alarms, security or device behavior.
- Auth provider `disabled` may exist in development/demo contexts; the page must represent it honestly and must not silently downgrade a live authenticated deployment.
- Physical hardware evidence is not relevant to the software-only settings workspace and must not be inferred.

## Explicitly unsupported and out of scope for Issue #269

- organization or membership CRUD;
- node provisioning, credentials or deployment changes;
- Modbus/RS-485 parameters or device writes;
- alarm-rule, retention, backup or restore mutation;
- CORS, TLS, DNS, VPN or secret rotation;
- database migration or universal settings API;
- dependency upgrade or unrelated design-system refactor;
- production/site cutover.

## Product-page priority

Issue #269 is the active Ready Work Package. After it merges, `/cameras` is next. `/lockers` remains blocked pending a concrete inventory, read-only protocol and operator workflow.

Deferred toolchain Issues #252–#257 remain outside the page-completion sequence unless a security, support or concrete product blocker appears.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production device behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Hardware and operational risks

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending controlled access.
- **N-037:** Sharp compatibility override remains monitored.
- **N-023:** node health durability is not claimed equal to telemetry process-restart durability.
- **N-024:** rollback must preserve named volumes and spool compatibility.
- **N-025:** actual-host spool capacity evidence remains required.
- **N-032:** actual Raspberry Pi ARM64 archive/load/start/update/rollback remains unverified.
- **#200:** physical RS-485 topology hardware-blocked.
- **#201:** cumulative LE-01MP energy hardware-blocked.
- **#202:** extended XJP60D semantics hardware-blocked.

## Next Ready action

Create `feat/269-operator-safe-settings` from the updated `main`, open one focused draft Pull Request and implement the typed settings diagnostics and browser-local preference vertical slice under Issue #269.
