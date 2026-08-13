# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #369 — completed, blockers resolved

Issue #369 / PR #420 is completed and squash-merged as
`4a266d73c451e191f2fab683dd07aa4c02d17b7d`.

Final exact-head gates on
`808ecc64c7e5f5282d666636eecb5b5efcd9657e` were GREEN:

- CI #2965;
- Authenticated Dashboard Acceptance #1644;
- Offline Bundle #1027.

Controlled Raspberry Pi / Chromium acceptance passed:

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

No #369 product, hardware or merge blocker remains.

## Issue #421 — active state-only reconciliation

Issue #421 only reconciles the completed #369 merge and the fresh Ready audit in
four `.project` files. No product/runtime code is permitted.

Remaining gate: focused state-only CI and merge.

## Issue #366 — dependency holds resolved; selected next

The historical #366 hold required Issue #368 to complete before broad route
read-model work. Issue #368 is closed/completed. The preserved runtime sequence
also required #369 acceptance first; #369 is now completed and merged.

The existing branch `perf/366-monitoring-read-model-deduplication` contains no
feature commits (`ahead_by=0`) and is only stale behind current `main`. After #421
merges, fast-forward that branch to the reconciled `main`, move #366 out of its
stale `status:blocked` label and resume the evidence-first implementation.

The repeated `.../layout/published` 404 read pattern observed during #369 is
recorded as #366 audit evidence. The `layout_not_published` response remains a
truthful empty-state contract; the task is to determine whether equivalent reads
are unnecessarily repeated across route/remount consumers.

## Issue #389 — independent Ready package

Issue #389 remains `status:ready` for administrator-only local Version
Management. It is independent and valid, but is `priority:high`; #366 is the
selected `priority:critical` continuation after #421.

## Issue #289 — downstream

Issue #289 remains downstream of #366 and must not start before the #366
read-model lifecycle/deduplication work is resolved.

## Other known boundaries

- Issue #415 remains an open Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- Open PRs are dependency-update lanes and do not block #366.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on
**2026-09-05**. Issues #369 and #421 do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
