# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `249a271b4d67dc87c8fa28b81a76027274b07e28`
Active Work Package: Issue #265 — Equipment Layouts catalog
Branch: `feat/265-equipment-layouts-catalog`
Pull Request: #266 — final readiness checkpoint
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Verified executable source head: `ac0e02f9911e3b299a21931315d6ff5a8d3cf0a2`
Status confidence: high for repository, browser, object-storage and disconnected-runtime evidence; physical hardware remains explicitly unverified.

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

Implemented and verified in PR #266:

- `/equipment-layouts` — authenticated cross-asset catalog and read-only published-layout preview.

Remaining placeholder routes on `main`:

- `/equipment-layouts` until PR #266 merges;
- `/equipment` — equipment and metrology registry;
- `/settings` — operator-safe Settings;
- `/cameras` — local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #265 completed product scope

PR #266 now provides:

- explicit `published-current`, `published-with-draft`, `draft-only`, `no-image`, `empty` and `failed` catalog states;
- immutable publication-versus-current-draft image and normalized geometry comparison;
- deterministic equipment ordering by code and then name;
- combined URL-backed search, laboratory, zone, chamber, equipment-lifecycle and layout-state filters;
- a deterministic clear-filter reload that removes filter query keys and does not retain stale filtered browser history;
- bounded concurrent per-equipment summary loading with cancellation, stale-result suppression and partial-failure preservation;
- authenticated organization-scoped equipment and layout HTTP repositories with no silent live-to-demo fallback;
- responsive cards with lifecycle, draft version, publication revision, placement count, publisher and timestamps;
- read-only signed-image preview with normalized sensor markers and isolated image failure state;
- canonical navigation to `/refrigeration/[equipmentId]` for every mutation workflow;
- no duplicate editor, dependency upgrade, database migration, backend schema change, Modbus write or hardware path.

## Exact executable verification

Verified on source head `ac0e02f9911e3b299a21931315d6ff5a8d3cf0a2`:

- CI `30901392247` GREEN;
- Authenticated Dashboard Acceptance `30901391302` GREEN;
- Refrigeration Browser Acceptance `30901391433` GREEN;
- Offline Bundle `30901391342` GREEN;
- browser evidence artifact `8889283540` captured.

The authenticated browser gate used production Next.js, FastAPI, PostgreSQL and MinIO and proved:

- real organization-scoped fixtures for published-current, newer unpublished draft, draft-only, no-image/retired and partial-summary-failure states;
- URL filters survive reload and clear deterministically;
- one injected summary failure remains local while successful catalog items stay available;
- every observed equipment/layout API request was authenticated, organization-scoped and read-only;
- the published image loaded from a signed MinIO URL with HTTP 200;
- normalized markers rendered at 25%/40% and 75%/65%;
- canonical navigation reached `/refrigeration/50000000-0000-4000-8000-000000000001`;
- zero catalog mutations were observed.

The disconnected Offline Bundle additionally proved archive load/start with egress blocked and `--pull never`, followed by update/rollback persistence preservation without deleting named volumes.

Temporary formatter/fix workflows removed themselves and are absent from the final PR diff.

## Runtime, offline and hardware evidence

```text
software verified; authenticated browser/API/PostgreSQL/MinIO verified; disconnected runtime verified; physical Raspberry Pi and RS-485 hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used.

## Next action

Complete the state-only exact-head repository gate, audit PR #266 review threads/reviews and final focused diff, then mark PR #266 ready for review without merging it.
