# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #413 — completed, blockers resolved

Issue #413 / PR #414 is merged as
`ecd61dfc8682f5aa0c7231b8a73341d1d292f03a`.

Hardware-tested corrective product head:
`0b0b239911c729e31c791c8fa2eb2c6f433bfcce`.

The controlled Raspberry Pi retest passed:

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

Final PR head `a845e39b0daa628e20e551289a378dcc33ffef2b` passed CI #2950,
Authenticated Dashboard #1638, Refrigeration #1612 and Offline Bundle #1021.
No #413 product, hardware or merge blocker remains.

## Issue #417 — active state-only reconciliation

Issue #417 records the completed #413 merge in four `.project` files plus the
#413 audit. No product/runtime code is permitted in this Work Package.

The only remaining gate is focused state-only CI and merge, followed by the
mandatory fresh Ready audit.

## Issue #415 — follow-up UX enhancement

Issue #415 requests natural left-button drag-to-pan on canonical desktop charts.
It is not a #413 blocker and remains pending the fresh Ready audit after #417.

## Issue #369 — Ready, separate scope

Issue #369 remains `status:ready` for Raspberry Pi Live Dashboard
inventory/filter/select/save editor acceptance.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains Ready for administrator-only local Version Management.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on
**2026-09-05**. Issue #417 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
