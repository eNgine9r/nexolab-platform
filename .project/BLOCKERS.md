# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #413 — one physical cursor-stability blocker remains

Issue #413 / Draft PR #414 migrates Overview XJP60D temperature history to the canonical Chart System.

The first frozen final candidate `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5` passed CI #2942, Authenticated Dashboard #1630, Refrigeration #1604 and Offline Bundle #1013, but controlled Raspberry Pi acceptance produced a clean product defect:

```text
cursor_vertical_jump=YES
graph_card_stays_fixed=YES
```

All other physical UI observations passed: exact real-series history continuity, post-event usability, Hide/Show/Solo, zoom/pan/reset, 1h/6h/24h and route reopen. Production restored cleanly with no restart drift.

Physical acquisition evidence on that candidate showed 144 requests / 60 s browser-closed versus 153 / 60 s active Overview. Successful requests were identical at 132 in both windows; the active window had more timeout/retry activity. The acceptance harness therefore classified the raw rate comparison `REVIEW_EQUAL_DURATION_COUNTERS`. Control-plane safety evidence remained clean:

- discovery delta 0;
- configuration mutation delta 0;
- Modbus write attempts 0;
- polling policy unchanged;
- configured targets `38 -> 38`;
- registry revision/summary unchanged;
- service-operation delta `{}`.

The cursor defect is isolated from physical acquisition: `graph_card_stays_fixed=YES` means the earlier ChartShell responsive reflow defect did not recur. The leading cause is the duplicate ECharts moving HTML axis-tooltip content; NEXOLAB already renders a stable canonical `Exact inspector`.

Corrective head `0b0b239911c729e31c791c8fa2eb2c6f433bfcce` disables renderer tooltip content while preserving the vertical axis pointer and exact inspector. CI #2944, Authenticated Dashboard #1632 and Refrigeration #1606 are GREEN; Offline Bundle #1015 was still running when this checkpoint was prepared.

PR #414 remains **Draft/not Ready** until:

1. the final corrective state/audit head is exact-head GREEN across CI, Authenticated Dashboard, Refrigeration and Offline Bundle;
2. focused diff/review audit remains clean;
3. a targeted controlled Raspberry Pi cursor retest on that exact head records `cursor_vertical_jump=NO` and `graph_card_stays_fixed=YES`;
4. production restores cleanly.

Because the corrective product diff is renderer-tooltip/test-only, the already completed 60-second acquisition, exact real-series continuity, controls, range and route-reopen evidence may be carried forward under proportional verification. If the final diff expands into telemetry, acquisition, scheduler, registry, API or hardware-related code, the full physical acquisition matrix must be rerun.

## Issue #369 — Ready, separate scope

Issue #369 remains `status:ready` for Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance. Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains Ready for administrator-only local Version Management and is not mixed into #413.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #413 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
