# NEXOLAB Current State

Updated: 2026-08-13

Canonical repository baseline on `main`:
`28cbe0aa9552a43ed3069818c60ad218f350d0bf` — Issue #417 / PR #418
post-#413 state reconciliation merged.

## Active Work Package — Issue #369 / PR #420

Issue #369 validates the canonical Live Dashboard channel inventory on the actual
Raspberry Pi browser and adds deterministic 162-channel regression coverage.

Branch:
`fix/369-live-dashboard-inventory-browser`

Pre-state product/test head:
`d037b732a8ae87a8d9f79f31cffeddde01a5eec9`.

The PR product surface is test-only:

- `src/features/live-dashboards/inventory-162.test.ts`;
- `src/components/live-dashboards/dashboard-editor-162.test.tsx`.

No runtime/API schema, Device Agent, scheduler, registry, polling, Modbus or
hardware-write behavior was changed.

## Issue #369 automated evidence

Exact-head gates on `d037b732a8ae87a8d9f79f31cffeddde01a5eec9` were GREEN:

- CI #2961;
- Authenticated Dashboard Acceptance #1640;
- Offline Bundle #1023.

The regression proves a realistic 162-channel canonical inventory loads through
`/api/v1/live-dashboards/channel-inventory`, supports editor search/select/reorder/
validation/save behavior, and does not use generic `/api/v1/telemetry/latest` as
an inventory dependency.

## Issue #369 Raspberry Pi browser acceptance

Controlled LOCAL_LAN browser acceptance on the real Raspberry Pi runtime passed:

```text
inventory_http_status=200
inventory_total=162
inventory_duration_ms~=44.84
search=PASS
filter=PASS
select_two_channels=PASS
reorder=PASS
configuration_valid=YES
save=PASS
reopen=PASS
telemetry_latest_inventory_dependency=NO
```

Observed request:
`GET /api/v1/live-dashboards/channel-inventory?limit=500&offset=0`.

Browser preview showed `items[0..161]`, `limit: 500`, `offset: 0`, `total: 162`.

The browser console also showed unrelated `404 Not Found` responses for equipment
`.../layout/published` resources. They did not affect the Live Dashboard
inventory/search/select/reorder/save/reopen acceptance and are not being hidden
as a clean-console result.

Completion classification for the product acceptance:

```text
software verified; Raspberry Pi browser verified
```

## Current merge state

PR #420 remains Draft while this durable `.project` reconciliation is added.
Because state commits change the PR head, required exact-head checks must be GREEN
again before Ready transition and merge.

Issue #369 must remain open until PR #420 is GREEN and merged.

## Preserved dependency lanes

- Issue #366 remains blocked until #369 is merged; then its dependency state must
  be re-audited before selection.
- Issue #289 remains downstream of #366.
- Issue #389 remains `status:ready` for administrator-only local Version
  Management and is independent of the runtime sequence.
- Issue #415 remains an open Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked.
- Issue #256 remains deferred.

## Safety boundary

No Modbus write, hardware write, destructive database/volume operation,
production/site cutover, mandatory cloud dependency or polling-policy change was
performed by Issue #369.

The `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on
2026-09-05.

## Next action

Complete the four-file `.project` reconciliation on PR #420, require fresh
exact-head GREEN CI/browser/offline gates, audit the focused diff and review
threads, mark PR #420 Ready, merge it, close Issue #369, update `main`, then run a
fresh repository-backed Ready audit before selecting the next Work Package.
