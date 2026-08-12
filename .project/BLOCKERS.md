# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #404 — completed, blockers resolved

Issue #404 / PR #410 is squash-merged as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b` from final product head `ce2356cfb142e241684a7a68a08969cab884c2f5`.

Final controlled Raspberry Pi evidence passed acquisition invariants, exact-series visual continuity, library reopen and cursor-layout stability. No #404 product or merge blocker remains.

## Issue #411 — completed

Issue #411 / PR #412 state reconciliation is merged as `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` after CI #2918 GREEN.

The required fresh Ready audit was completed after that merge and selected Issue #413.

## Issue #413 — physical acceptance pending

Issue #413 / Draft PR #414 migrates Overview XJP60D temperature history from its custom SVG renderer to the canonical Chart System.

No software/offline product blocker is currently known. Clean checkpoint head `cb65b4b08cd0087ea6b405de72c0a16f561e7541` passed:

- CI #2937 — GREEN;
- Authenticated Dashboard Acceptance #1625 — GREEN, 12/12;
- Refrigeration Browser Acceptance #1599 — GREEN;
- Offline Bundle #1008 — GREEN.

The earlier production-browser timeout was trace-diagnosed to a responsive shared `ChartShell` footer overlap: the inspector intercepted legend pointer events inside the narrow Overview card. The footer now remains stacked until `2xl`, and the full 12/12 production browser run passed without relaxing the interaction assertion or timeout.

The branch is intentionally **not Ready for merge** until:

- the final state/audit checkpoint head reruns required canonical gates GREEN;
- focused diff/review audit confirms no unrelated files or unresolved threads;
- controlled Raspberry Pi Overview acceptance passes on that exact frozen head.

Raspberry Pi acceptance must verify a real active Overview temperature series, equal-duration browser-closed versus active-Overview physical acquisition counters, chart continuity through an exact real event, cursor layout stability, zoom/pan/reset, route reopen and clean production restoration.

No synthetic-only fixture may be represented as physical acceptance.

## Issue #369 — Ready, separate scope

Issue #369 remains `status:ready` for Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance. It is independent from #413.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains Ready for administrator-only local Version Management. Product Owner priority currently keeps the Chart System migration active through #413.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #413 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
