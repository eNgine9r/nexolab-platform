# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #400 — completed

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Raspberry Pi evidence remains at `/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`.

## Issue #403 — completed

Issue #403 / PR #405 is merged as `c5977f846b87d0a498f84feec5b2e8f966a61d94`.

## Issue #406 — completed, no remaining blocker

Issue #406 / PR #407 is squash-merged as `457923927052ed91a23f396b2285e0cfaf6096ad`.

The Live Data chart lifecycle regression is fixed: incoming live samples no longer retrigger persisted-history loading solely because latest sample objects change.

Final exact-head verification was GREEN:

- CI;
- Authenticated Dashboard Acceptance 11/11, including real local MQTT live-point continuity regression and acquisition invariant;
- Refrigeration Browser Acceptance;
- Offline Bundle with disconnected load/start and update/rollback data preservation.

No new Raspberry Pi physical acceptance was run for #406 and none is claimed. No backend, database, scheduler, polling, registry, Device Agent, Modbus or hardware mutation occurred.

## Issue #404 — Ready and selected

Issue #404 is the sole selected implementation lane for Saved Live Dashboard canonical Chart System migration. Dependencies #386 and #400 are merged and #406 no longer blocks continuation.

Issue #404 remains distinct from #369: #404 is the saved-dashboard live renderer migration; #369 is the Raspberry Pi inventory/filter/select/save editor acceptance.

## Issue #369 — Ready, preserved runtime sequence

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

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
