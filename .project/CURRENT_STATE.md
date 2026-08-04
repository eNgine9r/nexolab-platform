# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `249a271b4d67dc87c8fa28b81a76027274b07e28`
Active Work Package: Issue #265 — Equipment Layouts catalog
Branch: `feat/265-equipment-layouts-catalog`
Pull Request: #266 — draft implementation PR
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Verified executable source head: `f61d6de5231ab9326901c0bc005e572ae1735bf2`
Status confidence: high for the implemented catalog domain, focused tests, authenticated frontend wiring and repository CI; browser/API/MinIO acceptance remains pending.

## Product route status

Implemented on merged `main`:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment and canonical layout editor;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — verified LE-01MP Energy Monitoring;
- `/live` — verified universal telemetry explorer, merged through PR #264.

Active branch implementation:

- `/equipment-layouts` — placeholder replaced in PR #266 by the authenticated catalog and read-only published-layout preview.

Remaining placeholder routes on `main`:

- `/equipment-layouts` until PR #266 merges;
- `/equipment` — equipment and metrology registry;
- `/settings` — operator-safe Settings;
- `/cameras` — local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #265 implementation slice

The first vertical slice is implemented on source head `f61d6de5231ab9326901c0bc005e572ae1735bf2`.

Delivered behavior:

- explicit catalog states: `published-current`, `published-with-draft`, `draft-only`, `no-image`, `empty` and `failed`;
- state derivation compares the immutable published image and normalized sensor geometry with the current draft instead of assuming draft and publication version numbers are directly comparable;
- deterministic equipment sorting by code and then name;
- combined search plus laboratory, zone, climate chamber, equipment lifecycle and layout-state filters;
- URL-backed filter parameters with reload/share continuity;
- bounded per-equipment summary loading with a default concurrency of four and a hard maximum of eight;
- stale-load cancellation at the catalog orchestration boundary and suppression of stale state commits;
- per-equipment failure isolation so successful summaries remain visible and failed items remain retryable;
- authenticated live runtime that reuses the existing equipment and layout HTTP repositories;
- explicit demo-mode/configuration/auth/error/empty/loading/refresh states with no silent live-to-demo fallback;
- read-only signed-image preview with normalized sensor markers and local broken-image handling;
- canonical navigation to `/refrigeration/[equipmentId]` for upload, edit, save, publish, restore and conflict recovery;
- no duplicate editor, dependency upgrade, database migration, backend schema change or hardware path.

Focused unit tests cover state derivation, combined filters, bounded concurrency, partial failure preservation and cancellation.

## Exact source verification

Verified on executable source head `f61d6de5231ab9326901c0bc005e572ae1735bf2`:

- CI `30892831371` GREEN;
- standalone Raspberry Pi runtime contracts GREEN;
- repository Prettier check GREEN;
- ESLint GREEN;
- strict TypeScript GREEN;
- complete Vitest suite GREEN, including the focused Equipment Layouts tests;
- production Next.js build GREEN.

Temporary read-only formatter workflows were removed completely and are absent from the final branch diff.

## Runtime, offline and hardware evidence

```text
Equipment Layouts domain and frontend source verified; production build verified; browser-to-FastAPI/PostgreSQL/MinIO acceptance pending; physical hardware unverified
```

The implementation introduces no package, Compose, container, database migration or offline-delivery change. GitHub may run the repository Offline Bundle automatically, but this slice does not rely on that result as its acceptance evidence.

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used.

## Next action

Add the focused Equipment Layouts browser acceptance against production Next.js, authenticated FastAPI, PostgreSQL and MinIO. Prove URL filter reload, published-current versus unpublished-draft states, partial item failure, read-only signed-image preview and canonical navigation. Then run the final executable-head gates, update state-only evidence and keep PR #266 draft until all required acceptance is GREEN.
