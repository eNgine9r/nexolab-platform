# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #400 — completed

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Raspberry Pi evidence remains at `/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`.

## Issue #406 — completed

Issue #406 / PR #407 is merged as `457923927052ed91a23f396b2285e0cfaf6096ad`. The Live Data chart-disappearance regression is fixed; exact-head CI/browser/offline gates were GREEN. No new physical Raspberry Pi claim was made for #406.

## Issue #408 — completed

Issue #408 / PR #409 is merged as `f3462861db2a3593e2072a7bad70d557c009b323`.

## Issue #404 — active, no hard blocker

Issue #404 is the sole active implementation lane for Saved Live Dashboard canonical Chart System migration.

Implementation is complete at the focused software layer and targeted checks are GREEN. Remaining work is verification, not a product blocker:

- open focused PR and run exact-head repository CI;
- run authenticated production Saved Dashboard browser acceptance;
- run the existing acquisition-invariant browser gate;
- run Offline Bundle;
- review focused diff/review threads;
- after software/browser/offline GREEN, run controlled Raspberry Pi Saved Dashboard acceptance with equal-duration physical acquisition counters;
- record evidence and repeat final exact-head audit before merge.

No backend, database, polling, scheduler, registry, Device Agent, Modbus or hardware change is required.

Known truthful limitation: the existing Saved Dashboard delivery hook reports `reconnecting` freshness but does not expose a timestamped reconnect event. The chart therefore does not invent a reconnect-break timestamp; it preserves reconnecting as freshness and uses actual missing/source-gap evidence for continuity.

## Issue #369 — Ready, separate scope

Issue #369 remains `status:ready` for Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance. It is not absorbed by #404.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains `status:ready` for administrator-only local Version Management, but Product Owner Chart System priority keeps it `ready_not_selected`.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #404 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
