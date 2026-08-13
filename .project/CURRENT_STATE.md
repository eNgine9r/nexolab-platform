# NEXOLAB Current State

Updated: 2026-08-13

Canonical repository baseline on `main`:
`4a266d73c451e191f2fab683dd07aa4c02d17b7d` — Issue #369 / PR #420
Raspberry Pi Live Dashboard inventory acceptance merged.

## Completed Work Package — Issue #369 / PR #420

Issue #369 is completed and closed. PR #420 was squash-merged as
`4a266d73c451e191f2fab683dd07aa4c02d17b7d`.

Final PR head:
`808ecc64c7e5f5282d666636eecb5b5efcd9657e`.

Final exact-head gates were GREEN:

- CI #2965;
- Authenticated Dashboard Acceptance #1644;
- Offline Bundle #1027.

Controlled Raspberry Pi / Chromium LOCAL_LAN acceptance passed:

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

The product/runtime implementation was unchanged by PR #420; the product diff
added deterministic 162-channel regressions plus durable project-state updates.
No Device Agent, scheduler, registry, polling, Modbus or hardware-write behavior
changed.

The browser session also exposed repeated `.../layout/published` 404 requests.
Repository code intentionally treats `layout_not_published` as an empty published
layout, so this was not a #369 failure. The repeated read pattern is recorded as
evidence for #366.

## Active Work Package — Issue #421

Issue #421 is a state-only reconciliation of the completed #369 merge and fresh
Ready/dependency audit.

Branch:
`chore/421-reconcile-issue-369-state`

Permitted changes are exactly:

- `.project/CURRENT_STATE.md`;
- `.project/ACTIVE_SPRINT.json`;
- `.project/BLOCKERS.md`;
- `.project/LAST_CHECKPOINT.json`.

No product/runtime code, workflow, dependency, database, telemetry or hardware
change belongs in #421.

## Fresh Ready/dependency audit

The post-#369 repository-backed audit establishes:

- Issue #368, the explicit dependency hold recorded on #366, is completed;
- Issue #369 is completed and merged;
- Issue #366 remains open with `priority:critical`;
- existing branch `perf/366-monitoring-read-model-deduplication` has no feature
  commits (`ahead_by=0`) and is only stale behind current `main`;
- Issue #389 remains the only independently labeled `status:ready` package and is
  `priority:high`;
- Issue #289 remains downstream of #366;
- open PRs are dependency-update lanes and do not block the critical runtime lane.

Therefore the next product Work Package after #421 merges is **Issue #366 — Audit
and deduplicate monitoring-route read models**.

Before #366 implementation, fast-forward its empty feature branch to the
reconciled `main`, then resume the evidence-first audit. Do not cache around
telemetry/runtime defects and do not change acquisition behavior.

## Preserved lanes

- #366 — next critical product Work Package after #421 merge;
- #289 — downstream of #366;
- #389 — independent Ready/not selected administrator Version Management;
- #415 — open Chart System UX follow-up;
- #245 — separate Raspberry Pi standalone validation track;
- #257 — blocked;
- #256 — deferred.

## Safety boundary

No Modbus write, hardware write, destructive database/volume operation,
production/site cutover, mandatory cloud dependency or polling-policy change was
performed by #369 or #421.

The `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on
2026-09-05.

## Next action

Complete #421 with a four-file focused diff and GREEN state-only CI, merge it,
fast-forward `perf/366-monitoring-read-model-deduplication` to the reconciled
`main`, move #366 out of its stale blocked state, and resume Issue #366.
