# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `249a271b4d67dc87c8fa28b81a76027274b07e28`
Previous Work Package: Issue #263 merged through PR #264
Active Work Package: Issue #265 — Equipment Layouts catalog
Branch: `feat/265-equipment-layouts-catalog`
Pull Request: #266 — draft implementation PR
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for the post-merge repository baseline, Work Package definition, branch and PR control state; executable implementation and verification for #265 have not started yet.

## Product route status

Implemented operator routes:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment and canonical layout editor;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — verified LE-01MP Energy Monitoring;
- `/live` — verified universal telemetry explorer, merged through PR #264.

Remaining placeholder routes:

- `/equipment-layouts` — active Work Package #265 in draft PR #266;
- `/equipment` — equipment and metrology registry;
- `/settings` — operator-safe Settings;
- `/cameras` — local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #265 product decision

`/equipment-layouts` will become a cross-asset catalog and read-only preview surface. It will not duplicate the existing refrigeration layout editor.

The catalog will reuse:

- `RefrigerationEquipmentRepository.list()` for organization-scoped equipment inventory;
- `RefrigerationLayoutRepository.getDraft()` for mutable draft version and geometry;
- `RefrigerationLayoutRepository.getPublished()` for the active immutable publication;
- `RefrigerationLayoutRepository.listHistory()` only where publication history metadata is required;
- `/refrigeration/[equipmentId]` as the single edit, upload, publish, restore and conflict-recovery entry point.

The catalog must distinguish published-current, newer unpublished draft changes, draft-only, no-image, empty, retired and failed-summary states. It must use bounded concurrent summary loading, preserve partial successes and never silently fall back to demo data in live mode.

No dependency upgrade, database migration, new persistence model, Modbus write, hardware action or production/site cutover is part of this Work Package.

## Verified repository basis

The post-merge `main` baseline `249a271b4d67dc87c8fa28b81a76027274b07e28` contains:

- the existing authenticated refrigeration equipment repository and live HTTP adapter;
- the versioned layout repository with draft, publish, history, restore and signed image metadata;
- the canonical refrigeration layout workspace and security-aware editor flow;
- the `/equipment-layouts` placeholder that Issue #265 will replace.

Issue #265 defines the complete product outcome, scope, out-of-scope boundaries, permitted directories, acceptance criteria and proportional verification plan.

Draft PR #266 is the only Pull Request for this Work Package. Its current commits update repository control state only; no executable feature behavior is claimed yet.

## Runtime, offline and hardware evidence

```text
post-#264 main verified; Issue #265, feature branch and draft PR #266 verified; no #265 executable implementation or runtime evidence yet; physical hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used.

## Next action

Implement the catalog domain loader and explicit layout-state derivation with focused tests. Then wire the authenticated `/equipment-layouts` screen, URL-backed filters and read-only published-layout preview in PR #266 without dependency migrations or a duplicate editor.
