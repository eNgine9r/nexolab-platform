# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` — Issue #411 / PR #412 post-#404 state reconciliation merge.

## Completed Chart System foundation and migrations

- Issue #386 / PR #399 — canonical Chart Domain, truthful continuity, evidence-preserving reduction, ECharts Canvas adapter, Chart Shell and renderer host — merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.
- Issue #400 / PR #402 — Live Data canonical Chart System migration — merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2` with controlled Raspberry Pi acquisition-invariant PASS.
- Issue #404 / PR #410 — Saved Live Dashboard canonical Chart System migration — merged as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b` with controlled Raspberry Pi continuity, reopen and cursor-layout PASS.
- Issue #411 / PR #412 — post-#404 state reconciliation — merged as current `main=e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` after CI #2918 GREEN.

## Active Work Package — Issue #413 / Draft PR #414

Issue #413 migrates Overview XJP60D temperature history from the route-local SVG renderer to the canonical NEXOLAB Chart System while preserving live cards, active sensor selection, authenticated latest/history/WebSocket delivery and the 1h/6h/24h contract.

Delivered product scope:

- canonical stable node/equipment/channel/metric/unit identities;
- invalid-quality and source-gap continuity boundaries;
- canonical evidence-preserving reduction;
- `ChartShell` + `ChartRendererHost` + local ECharts Canvas;
- persistent non-animated live updates;
- exact cursor/inspector, show/hide/solo and zoom/pan/reset;
- no legacy Overview telemetry SVG;
- responsive shared ChartShell footer fix;
- no extra history/acquisition/public-runtime requests from chart interaction.

## Physical acceptance history

First frozen candidate `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5` passed CI #2942, Authenticated Dashboard #1630, Refrigeration #1604 and Offline Bundle #1013. Controlled Raspberry Pi acceptance proved real-series continuity and the physical acquisition/control-plane boundary, but exposed one visual defect: `cursor_vertical_jump=YES` while `graph_card_stays_fixed=YES`.

The defect was isolated to duplicate renderer-owned moving ECharts tooltip content. Corrective product head `0b0b239911c729e31c791c8fa2eb2c6f433bfcce` disables tooltip content and `showTip` dispatch while preserving the vertical axis pointer and canonical Exact inspector.

Corrective exact-product gates are GREEN:

- CI #2944;
- Authenticated Dashboard Acceptance #1632, including acquisition invariant;
- Refrigeration Browser Acceptance #1606;
- Offline Bundle #1015.

Targeted controlled Raspberry Pi retest on the corrective product code passed:

- chart visual continuity — PASS;
- post-event Overview render — PASS;
- cursor vertical jump — NO;
- graph/card stays fixed — YES;
- Hide/Show/Solo — PASS;
- zoom/pan/reset — PASS for the current #413 acceptance contract;
- 1h -> 6h -> 24h — PASS;
- route reopen — PASS;
- dashboard remains usable — YES.

Therefore the #413 physical UI blocker is resolved. The already proven real-series acquisition/control-plane evidence remains valid because the corrective product diff is renderer/test-only and does not change telemetry, Device Agent, scheduler, registry, polling or hardware behavior.

## Follow-up UX requirement

Issue #415 records the Product Owner request for natural desktop left-button drag-to-pan across canonical NEXOLAB charts. It is intentionally separate from #413 so the hardware-tested #413 product code is not expanded after acceptance. #415 is open as a focused follow-up and is not selected until post-#413 reconciliation and fresh Ready audit.

## Preserved independent lanes

- Issue #369 remains Ready and preserves runtime sequence `#369 -> #366 -> #289`.
- Issue #389 remains Ready/not selected.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked.
- Issue #256 remains deferred.

## Safety boundary

No Modbus write, hardware write, backend schema change, PostgreSQL migration, Device Agent change, acquisition scheduler/registry change or dependency upgrade is part of #413. No mandatory CDN, remote font, analytics, cloud renderer, external API or paid runtime dependency is introduced.

The `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and is not broadened by #413.

## Next action

Run final exact-head CI/review audit on the state-only completion head. If GREEN and `main` remains unchanged, mark PR #414 Ready and squash-merge with an exact-head guard. Then perform focused post-merge state reconciliation and a fresh Ready audit before selecting the next Work Package, including consideration of new Issue #415 alongside preserved #369 and #389 lanes.
