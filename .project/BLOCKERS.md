# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #400 — completed

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`.

There is no remaining #400 blocker. Software, offline runtime and controlled Raspberry Pi acquisition-invariant acceptance are complete.

Raspberry Pi evidence:

```text
candidate: 2da08a028f54884acb74ea71cf1fac741426687b
60s browser closed: 180 physical requests / 3.000 req/s
60s active 8-channel chart: 181 physical requests / 3.017 req/s
rate delta: +0.56%
retries: 12 -> 12
timeouts: 12 -> 12
bus executions: 156 -> 157
scheduler policy: unchanged
configured targets: 38 -> 38
poll-eligible targets: 38 -> 38
telemetry: advancing
```

Evidence directory:

`/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`

No Modbus write, hardware write, polling/scheduler change, persistent-data deletion or site cutover occurred.

## Issue #403 — state-only reconciliation

Issue #403 has no product blocker. It exists only to reconcile the four canonical `.project` state files after the #400 merge and record the fresh Ready audit.

No product code, dependency, runtime, database or hardware changes are permitted in #403.

## Issue #404 — Ready, selected next after #403

Issue #404 migrates the persisted Saved Live Dashboard line/area history renderer to the canonical NEXOLAB Chart System.

It is open, assigned, `priority:high` and `status:ready`.

No implementation blocker is currently known. Dependencies #386 and #400 are merged.

Important boundary: #404 does **not** absorb Issue #369. #369 remains the Raspberry Pi browser inventory/filter/select/save acceptance for the dashboard editor.

Hardware acceptance for #404 must again be reported separately after software gates are GREEN; CI/mock evidence must not be called physical acceptance.

## Issue #369 — Ready, preserved runtime sequence

Issue #369 remains `status:ready` and covers actual Raspberry Pi browser acceptance for canonical Live Dashboard inventory, filtering, selection and save.

Its product scope remains separate from #404 renderer migration.

The preserved runtime sequence is:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains `status:ready` for administrator-only local NEXOLAB Version Management. Its #385 dependency is satisfied, but the Product Owner Chart System priority keeps it `ready_not_selected`.

Hard stops specific to #389 remain:

- target package/version identity cannot be verified;
- required PostgreSQL backup fails;
- migration or rollback compatibility is unknown;
- rollback would require destructive schema/data downgrade;
- named volumes or edge SQLite cannot be preserved;
- secrets would be exposed;
- action would cross into unapproved production/site cutover.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #400 did not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
