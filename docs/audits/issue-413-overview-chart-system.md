# Issue #413 — Overview temperature canonical Chart System audit

Updated: 2026-08-12

## Status

**Corrective cursor fix implemented and software/browser verified; final exact-head rerun plus targeted Raspberry Pi cursor retest pending — Draft PR #414.**

Base `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`.

## Product scope delivered

Issue #413 replaces the independent Overview XJP60D temperature-history SVG with the canonical NEXOLAB Chart System while preserving the existing Overview product and acquisition contracts.

Delivered behavior:

- exact stable node/equipment/channel/metric/native-unit identity;
- truthful invalid-quality and >30 s source-gap continuity boundaries;
- canonical evidence-preserving reduction with 240-point target;
- deterministic series identity/color and compatible-unit grouping;
- `ChartShell` + `ChartRendererHost` + local ECharts Canvas;
- persistent non-animated live updates;
- canonical exact cursor/inspector;
- show/hide/solo and zoom/pan/reset;
- existing live value cards unchanged;
- existing XJP60D sensor-management selection unchanged;
- existing 1h/6h/24h history contract unchanged;
- no extra history requests from cursor/visibility/zoom/live updates;
- no chart-driven acquisition mutation;
- zero mandatory public runtime requests.

A shared responsive correction keeps ChartShell legend and inspector stacked until `2xl`, preventing the inspector from overlapping `Hide` in narrow Overview cards.

## Initial final software freeze

Exact head `634dcdfd8561d7e0ebe844b871ffa9f44d9fbcb5` passed:

- CI #2942 — GREEN;
- Authenticated Dashboard Acceptance #1630 — GREEN, including acquisition invariant;
- Refrigeration Browser Acceptance #1604 — GREEN;
- Offline Bundle #1013 — GREEN, including disconnected startup and update/rollback persistent-data preservation;
- focused diff and zero unresolved review threads before physical cutover.

## Controlled Raspberry Pi acceptance on `634dcdfd...`

### Real target

Read-only inventory selected:

- channel `126-04`;
- metric `temperature.probe`;
- source `dixell-xjp60d`;
- 120 real events / preceding 10 minutes;
- 16,594 valid samples / preceding 24 hours.

### Equal-duration acquisition evidence

| Metric | Browser closed | Active Overview |
| --- | ---: | ---: |
| Window | 60 s | 60 s |
| Physical requests | 144 | 153 |
| Requests/s | 2.400 | 2.550 |
| Success | 132 | 132 |
| Timeout | 12 | 21 |
| Retry attempts | 12 | 17 |
| Bus busy seconds | 9.92298 | 12.871187 |

The acceptance harness classified the raw request-rate comparison `REVIEW_EQUAL_DURATION_COUNTERS`, not automatic PASS/FAIL. The active window did **not** add successful polls: success remained exactly 132. Its higher raw request count coincided with additional timeout/retry activity.

Control-plane invariants were unchanged:

- discovery delta 0;
- configuration mutation delta 0;
- Modbus write attempts 0;
- polling policy remained `priority_adaptive_v1`;
- configured targets `38 -> 38`;
- registry revision unchanged;
- registry summary unchanged;
- service-operation delta `{}`.

This evidence does not show a browser-driven scheduler/registry mutation. The corrective code below is presentation-only, so the full 60-second acquisition drill is carried forward under proportional verification unless later diff expansion touches runtime/acquisition code.

### Exact real-series continuity

The exact real series advanced while Overview remained open:

- old event `1b19f5f5-4f4f-4734-83d6-b896d9a61438` — `2026-08-12 18:35:03.216544+00`, valid, 25.9 °C;
- new event `508e5cf9-be2f-44dc-8a61-f15fd089fcab` — `2026-08-12 18:35:08.227509+00`, valid, 25.9 °C.

Results:

- existing graph stayed visible — PASS;
- post-event Overview remained usable — PASS;
- Hide/Show/Solo — PASS;
- zoom/pan/reset — PASS;
- 1h -> 6h -> 24h — PASS;
- route reopen — PASS;
- dashboard remained usable — YES;
- graph/card stayed fixed — YES;
- **cursor vertical jump — YES**.

Production restored cleanly after the test with `NRestarts 0 -> 0` and no orphan candidate process.

### Classification

The physical result is **PRODUCT FAIL for cursor visual stability**. PR #414 correctly remains Draft and was not merged.

## Cursor defect diagnosis and correction

The physical answers distinguish two different effects:

```text
cursor_vertical_jump=YES
graph_card_stays_fixed=YES
```

Therefore the earlier responsive ChartShell reflow defect did not recur. The remaining moving visual element was the renderer-owned ECharts HTML axis tooltip. That tooltip duplicated information already rendered in NEXOLAB's canonical stable `Exact inspector` and ECharts could reposition it vertically as the cursor moved.

Focused shared correction on product head `0b0b239911c729e31c791c8fa2eb2c6f433bfcce`:

- keep ECharts `trigger: "axis"` so the vertical time pointer and `updateAxisPointer` events remain available;
- set `tooltip.showContent = false` so ECharts does not create moving tooltip content;
- stop dispatching `showTip` from `setSharedCursor`;
- continue to drive canonical exact inspection from `updateAxisPointer` into the external `Exact inspector`;
- add a unit regression that locks this contract.

This correction changes no data mapping, y-scale, continuity, API, WebSocket, Device Agent, scheduler, registry, discovery, polling or hardware state.

## Corrective software/browser verification

On `0b0b239911c729e31c791c8fa2eb2c6f433bfcce`:

- CI #2944 — GREEN: format, lint, strict typecheck, full unit tests and production build;
- Authenticated Dashboard Acceptance #1632 — GREEN, including JWT REST/history/WebSocket and acquisition-invariant flow;
- Refrigeration Browser Acceptance #1606 — GREEN;
- Offline Bundle #1015 was still running when this batched state checkpoint was created.

The browser regression therefore confirms that removing renderer tooltip content preserves the canonical cursor event path, exact inspector, Canvas lifecycle and telemetry/acquisition boundary.

## Final corrective freeze protocol

After this audit/state commit:

1. read exact PR #414 head from GitHub;
2. confirm `main` remains `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`;
3. confirm focused changed-file boundary is 14 files and no workflow file is modified;
4. require CI, Authenticated Dashboard, Refrigeration and Offline Bundle GREEN on that exact head;
5. confirm zero unresolved review threads;
6. freeze the branch with no further commits;
7. run only the affected controlled Raspberry Pi cursor retest on that exact head.

Targeted physical PASS requires:

```text
cursor_vertical_jump=NO
graph_card_stays_fixed=YES
dashboard_remains_usable=YES
```

Also verify the vertical time pointer still moves, the `Exact inspector` still updates to measured values, and production restores cleanly. The already proven exact real-series continuity, controls/range/reopen and acquisition control-plane evidence may be carried forward only while the final product diff remains limited to renderer-tooltip presentation.

## Safety boundary

No backend schema, database migration, telemetry API, Device Agent, scheduler, registry, discovery, Modbus, hardware or dependency change is part of #413.

No Modbus write, hardware write, destructive data/volume operation or production/site cutover is permitted. No mandatory CDN, remote font, analytics, cloud renderer, external API or paid runtime dependency is introduced.

## Completion classification

```text
software/browser verified on corrective product head; final exact-head state gate and targeted Raspberry Pi cursor acceptance pending
```

Issue #413 remains Draft/not Ready until the corrective exact head is GREEN and the controlled Pi cursor retest passes.
