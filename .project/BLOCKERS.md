# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #378 / #374 recovery chain — resolved

Issue #378 / PR #380 is merged and hardware verified. Same-container CP2104 USB re-enumeration recovery passed on Raspberry Pi without restart/recreate, and Issue #374 is closed as the completed regression parent. RS-485 recovery no longer blocks #368.

## Issue #368 — active; software gate pending

Issue #368 / PR #373 has been reconciled with current `main` through non-force two-parent merge commit `3427df41fab06667904d127313723fa90e130fcd`.

Reconciliation policy:
- current `main` is authoritative for all #378/state files;
- only the ten telemetry-specific #368 files are overlaid from the prior feature head;
- no rebase, force push or `main` mutation;
- PR is mergeable after reconciliation.

The previous `36ccb909...` verification record is historical and not accepted for the next physical run. Current workflow history and prior state metadata are not fully consistent on that old SHA, so the ambiguity is resolved by requiring **fresh exact-head CI on the branch head containing the current #368 checkpoint**.

Do not run Raspberry Pi migration-v2 until that fresh CI is completely GREEN.

### Physical preconditions after GREEN

Immediately before migration verify again:

```text
Alembic = 20260805_0022
telemetry_latest = absent
acquisition newest_age <= 120 s
no advisory lock 263000001 held/waiting unexpectedly
```

Then create a fresh PostgreSQL backup before any schema migration. No destructive rollback, history deletion, volume deletion or Modbus write is permitted.

## Sequencing blockers

- #368: active; fresh exact-head CI required before physical migration-v2/latest-query acceptance.
- #369 waits for #368 physical acceptance and merge.
- #366 waits for the #368 -> #369 runtime acceptance sequence.
- #289 remains downstream after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, privileged hardware containers, or unsupported physical acceptance claims.
