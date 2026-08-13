# Issue #413 — Overview temperature canonical Chart System audit

Updated: 2026-08-12

## Completion status

**COMPLETED / MERGED / HARDWARE VERIFIED**

Issue #413 / PR #414 merged into `main` as
`ecd61dfc8682f5aa0c7231b8a73341d1d292f03a`.

Final PR head before merge:
`a845e39b0daa628e20e551289a378dcc33ffef2b`.

Hardware-tested corrective product head:
`0b0b239911c729e31c791c8fa2eb2c6f433bfcce`.

Commits after that corrective product head were state/audit-only. No product/runtime
code changed after the successful Raspberry Pi retest.

## Product scope delivered

Overview XJP60D temperature history now uses the canonical NEXOLAB Chart System:

- stable node/equipment/channel/metric/native-unit identity;
- truthful invalid-quality and source-gap continuity boundaries;
- canonical evidence-preserving reduction;
- deterministic canonical series identity;
- `ChartShell` + `ChartRendererHost` + local ECharts Canvas;
- persistent non-animated live updates;
- exact vertical cursor with canonical external Exact inspector;
- show/hide/solo and zoom/pan/reset;
- responsive legend/inspector layout;
- no legacy Overview telemetry-history SVG;
- no extra history requests from chart interaction;
- no chart-driven acquisition mutation;
- zero mandatory public runtime requests.

## First physical acceptance and defect isolation

First frozen candidate `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5`
passed CI #2942, Authenticated Dashboard #1630, Refrigeration #1604 and Offline
Bundle #1013.

Controlled Raspberry Pi acceptance used real channel `126-04`, metric
`temperature.probe`, source `dixell-xjp60d`. It proved real-series history
continuity and unchanged acquisition/control-plane behavior, but exposed one
visual defect:

```text
cursor_vertical_jump=YES
graph_card_stays_fixed=YES
```

Because the graph/card itself remained fixed, the defect was isolated from the
responsive ChartShell layout and traced to duplicate renderer-owned moving
ECharts tooltip content.

## Preserved physical acquisition evidence

The completed #413 audit retains the exact hardware measurements used to support
the acquisition-invariant conclusion.

Equal-duration 60-second windows:

- browser closed: 144 physical requests, 2.400 req/s, 132 successful requests,
  12 timeouts, 12 retry attempts, 9.92298 s bus busy;
- active Overview: 153 physical requests, 2.550 req/s, 132 successful requests,
  21 timeouts, 17 retry attempts, 12.871187 s bus busy.

The raw request-rate comparison was classified `REVIEW_EQUAL_DURATION_COUNTERS`,
not automatic PASS/FAIL. Successful polls remained exactly 132 in both windows;
the higher active raw request count coincided with additional timeout/retry
activity.

Control-plane evidence remained unchanged:

- discovery delta: `0`;
- configuration mutation delta: `0`;
- Modbus write attempts: `0`;
- polling policy: `priority_adaptive_v1` unchanged;
- configured targets: `38 -> 38`;
- registry revision: unchanged;
- registry summary: unchanged;
- service-operation delta: `{}`.

Exact real-series continuity evidence:

- old event `1b19f5f5-4f4f-4734-83d6-b896d9a61438` at
  `2026-08-12 18:35:03.216544+00`, quality `valid`, value `25.9 °C`;
- new event `508e5cf9-be2f-44dc-8a61-f15fd089fcab` at
  `2026-08-12 18:35:08.227509+00`, quality `valid`, value `25.9 °C`.

No browser-driven scheduler, registry, discovery, configuration or hardware
mutation was observed.

## Corrective renderer fix

Corrective product head:
`0b0b239911c729e31c791c8fa2eb2c6f433bfcce`.

The shared adapter correction:

- keeps the vertical time axis pointer;
- keeps `updateAxisPointer` cursor events;
- sets ECharts tooltip `showContent: false`;
- stops dispatching `showTip` for shared cursor movement;
- keeps the canonical external Exact inspector;
- adds a focused unit regression.

No telemetry API, WebSocket contract, Device Agent, scheduler, registry, polling,
database or hardware behavior changed.

Corrective product gates were GREEN:

- CI #2944;
- Authenticated Dashboard Acceptance #1632, including acquisition invariant;
- Refrigeration Browser Acceptance #1606;
- Offline Bundle #1015.

## Controlled Raspberry Pi corrective retest

The Product Owner reported:

```text
chart_visual_continuity=PASS
post_event_overview_render=PASS
cursor_vertical_jump=NO
graph_card_stays_fixed=YES
hide_show_solo=PASS
zoom_pan_reset=PASS
range_1h_6h_24h=PASS
route_reopen=PASS
dashboard_remains_usable=YES
```

This closed the physical cursor blocker. The earlier full physical
acquisition/control-plane evidence remained applicable because the corrective
diff was renderer/test-only.

## Final exact-head verification

Final PR head `a845e39b0daa628e20e551289a378dcc33ffef2b` passed:

- CI #2950;
- Authenticated Dashboard Acceptance #1638;
- Refrigeration Browser Acceptance #1612;
- Offline Bundle #1021, including disconnected startup and update/rollback
  persistent-data preservation.

Final review boundary before merge:

- 14 focused files;
- no `.github` workflow diff;
- ahead 35 / behind 0 from the then-current base;
- unresolved review threads 0;
- submitted blocking reviews 0.

PR #414 merged as `ecd61dfc8682f5aa0c7231b8a73341d1d292f03a`, and Issue #413
closed as completed.

## Follow-up UX

Issue #415 records the Product Owner request for natural desktop left-button
drag-to-pan on canonical charts. It is intentionally separate from #413 and
requires fresh Ready-audit selection before implementation.

## Safety boundary

No Modbus write, hardware write, destructive data/volume operation,
production/site cutover, backend schema migration or mandatory public runtime
dependency was introduced by #413.

## Final classification

```text
software verified
browser verified
offline verified
hardware verified
merged
```
