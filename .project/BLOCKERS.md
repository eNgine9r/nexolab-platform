# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #413 — physical cursor blocker resolved

Issue #413 / Draft PR #414 migrates Overview XJP60D temperature history to the canonical Chart System.

The first frozen candidate `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5` passed software/browser/offline gates but controlled Raspberry Pi acceptance exposed `cursor_vertical_jump=YES` while the graph/card itself remained fixed.

Corrective product head `0b0b239911c729e31c791c8fa2eb2c6f433bfcce` removed duplicate moving ECharts tooltip content while preserving the vertical axis pointer and canonical Exact inspector.

Corrective gates are GREEN:

- CI #2944;
- Authenticated Dashboard Acceptance #1632;
- Refrigeration Browser Acceptance #1606;
- Offline Bundle #1015.

Targeted controlled Raspberry Pi retest passed:

```text
cursor_vertical_jump=NO
graph_card_stays_fixed=YES
chart_visual_continuity=PASS
post_event_overview_render=PASS
hide_show_solo=PASS
zoom_pan_reset=PASS
range_1h_6h_24h=PASS
route_reopen=PASS
dashboard_remains_usable=YES
```

No #413 physical UI blocker remains. The prior full acquisition/control-plane evidence remains applicable because the corrective product diff is renderer/test-only and does not touch telemetry, Device Agent, scheduler, registry, polling cadence or hardware state.

PR #414 still requires a final exact-head state-only CI/review audit before Ready/merge.

## Issue #415 — follow-up UX enhancement

Issue #415 records a new Product Owner request for natural left-button drag-to-pan on canonical desktop charts. This is not a blocker for #413 and must not mutate the already accepted #413 product code.

Select #415 only after #413 merge/post-merge reconciliation and a fresh Ready audit.

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
