# NEXOLAB Current State

Updated: 2026-08-13

Canonical Issue #366 baseline on `main`:
`3a91a180ff6b842321c18a2273f405bcdd42e149` — Issue #421 / PR #422
post-#369 reconciliation and #366 selection.

## Completed Work Package — Issue #366 / PR #423

Issue #366 audits and deduplicates non-telemetry monitoring-route read models.
PR #423 was squash-merged as
`a8daee3468e2384c505f988eb006fca05c2afa3f`; Issue #366 is closed.

Verified slices on the branch before the current Overview alerts correction:

- one bounded organization-scoped non-telemetry SWR/deduplication contract;
- reuse of the #357 refrigeration structural cache for equipment/layout reads;
- retained composed Equipment Layouts catalog;
- retained canonical Live Dashboard inventory;
- route-transition security-session deduplication;
- retained exact-query Overview session list with mutation invalidation.

The #314 route-persistent telemetry runtime remains the only telemetry cache.
Nodes remain uncached because browser evidence showed no duplicate node-list or
operational-state reads.

## Overview alerts proven gap — corrected

Authenticated Dashboard #1676 proved that one six-route cycle issued two exact
active-alert reads and two exact acknowledged-alert reads. The current local
correction adds a narrow Overview alerts read model with:

- organization-scoped keying;
- 5-second fresh and 30-second stale TTLs;
- the existing explicit 5-second polling cadence;
- retained last-valid content with truthful refresh error state;
- targeted invalidation after acknowledge/close;
- no second telemetry cache and no fabricated fallback.

Local canonical Authenticated Dashboard acceptance passed all 12 scenarios. The
route cycle recorded:

```text
active_alert_reads=1
acknowledged_alert_reads=1
overview_return_ms=334
latest_requests=1
history_requests=3
websocket_opened=1
websocket_max_concurrent=1
acquisition_mutations=0
```

The locally verified product/state commit is
`625355c988a286bd007e9c84c48384f2473c0ba6`.

Acquisition invariant phases remained near the fixture's 20 requests/second
rate, including browser navigation, multiple authenticated contexts, WebSocket
reconnect and telemetry-service restart.

## Software verification on the local alerts correction

- targeted Vitest: 12/12 GREEN;
- formatting: GREEN;
- ESLint: GREEN;
- strict TypeScript: GREEN;
- full Vitest/lint-staged: 86 files / 375 tests GREEN;
- production build: GREEN;
- canonical Authenticated Dashboard acceptance: 12/12 GREEN in 5.2 minutes.

The first two direct harness attempts did not execute product browser tests: one
used an uppercase auto-generated Compose project name rejected by local Docker
Compose, and one omitted the required acquisition fixture. The canonical
`run-acquisition-invariant-browser-acceptance.sh` entrypoint then passed.

## Final exact-head verification

Final PR head `11a58e99a69ec04eea38316553724cdad4c83493` passed every triggered
exact-head gate:

- CI;
- Authenticated Dashboard Acceptance;
- Alerts Browser Acceptance;
- Nodes Browser Acceptance;
- Test Sessions Browser Acceptance;
- Refrigeration Browser Acceptance;
- Offline Auth Acceptance;
- Offline Bundle;
- both Disaster Recovery Browser jobs.

Offline Auth initially hit a runner/container-start transient immediately after
pulling `postgres:16-alpine`; the targeted rerun passed as workflow #402 without
code changes. Offline Bundle passed as #1068.

## Active state-only reconciliation — Issue #427

Issue #427 records the #366 merge and post-merge Ready audit in exactly four
`.project` files plus this audit. No product/runtime change belongs in #427.

The fresh audit establishes:

- Issue #289 remains `status:needs-validation`; its own repository comment
  requires a focused #356 route-prefetch/time-to-usable slice before final
  physical/performance measurement, and no such child Work Package exists yet;
- Issue #389 remains the only independently labeled `status:ready` package;
- #415 remains an unselected Chart System UX follow-up;
- #245 remains a separate Raspberry Pi validation lane.

Therefore #389 is the next repository-backed Ready Work Package after #427
merges. Planning a focused #356 route-prefetch/time-to-usable child remains a
separate critical backlog action before #289 final acceptance.

## Safety boundary

No database migration, Device Agent configuration/discovery, scheduler, registry,
polling-policy, Modbus, hardware, persistent-data, dependency or site-cutover
change is included. Core runtime remains LOCAL_LAN and offline-capable.
