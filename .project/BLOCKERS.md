# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #400 — completed

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Software, offline runtime and controlled Raspberry Pi acquisition-invariant acceptance are complete.

Raspberry Pi evidence remains at `/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`.

## Issue #403 — completed

Issue #403 / PR #405 is merged as `c5977f846b87d0a498f84feec5b2e8f966a61d94`. There is no remaining state-reconciliation blocker from #403.

## Issue #406 — critical regression active, no hard blocker

Product Owner reported that the Live Data chart disappears while incoming points are loaded.

Repository-backed root cause is confirmed in `src/hooks/use-live-telemetry.ts`: the persisted-history effect depended on arrays rebuilt from mutable latest telemetry samples. A normal live update could therefore restart full history loading, clear history state and temporarily unmount the chart.

The focused correction is implemented on `fix/406-live-chart-history-continuity`:

- selected identity samples are retained independently from the history-loader trigger;
- stable `selectedKey` is the selection dependency for history loading;
- mutable `selectedIdentities` and rebuilt `reconciledSelectedKeys` are no longer history-effect dependencies;
- real selection/range/retry/scope/live-coverage changes still reload history;
- local MQTT browser regression requires the chart renderer hosts to remain mounted and history request count to remain unchanged when a normal new point arrives.

Targeted typecheck and focused Live history/chart tests are GREEN. Full PR CI, authenticated production browser acceptance, acquisition-invariant gate and Offline Bundle remain required before merge.

There is no hard blocker. No backend, database, scheduler, polling, registry, Device Agent, Modbus or hardware mutation is required.

## Issue #404 — Ready after #406

Issue #404 remains `status:ready` for Saved Live Dashboard canonical Chart System migration. Dependencies #386 and #400 are merged.

Implementation is intentionally paused while critical regression #406 is active because `max_parallel_implementation_tasks` is 1.

Issue #404 does **not** absorb Issue #369. #369 remains Raspberry Pi inventory/filter/select/save acceptance for the dashboard editor.

## Issue #369 — Ready, preserved runtime sequence

Issue #369 remains `status:ready`. Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains `status:ready` for administrator-only local NEXOLAB Version Management. Its #385 dependency is satisfied, but the Product Owner Chart System priority keeps it `ready_not_selected`.

Hard stops specific to #389 remain target identity verification failure, backup failure, unknown migration/rollback compatibility, destructive downgrade, inability to preserve persistent data, secret exposure, or unapproved production/site cutover.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #406 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
