# Issue #404 — Saved Live Dashboard canonical Chart System migration audit

Updated: 2026-08-12

## Scope

Issue #404 migrates only persisted Saved Live Dashboard `line` / `area` history rendering to the canonical NEXOLAB Chart System established by Issue #386 and already consumed by Live Data in Issue #400.

Issue #369 remains separate and owns Raspberry Pi inventory/filter/select/save editor acceptance. This Work Package does not change dashboard CRUD, ETag/versioning, channel inventory, backend telemetry contracts, polling, scheduler, registry, Device Agent or Modbus behavior.

Implementation baseline: `main=f3462861db2a3593e2072a7bad70d557c009b323`.

Feature branch: `feat/404-saved-live-dashboard-chart-system`.

Pull Request: #410.

## Implementation

### Canonical domain mapping

`src/features/live-dashboards/chart.ts` maps persisted `LiveDashboardItem` / `LiveDashboardSeries` into canonical Chart Domain objects.

Properties preserved:

- persisted item order;
- persisted series color, with deterministic canonical fallback;
- exact native unit;
- channel and metric identity;
- persisted dashboard time window as the reset/initial viewport;
- measurement quality independently from delivery freshness;
- cumulative energy semantics (`Wh` / `kWh` or energy metric) independently from instantaneous metrics.

Stable Saved Dashboard chart identity uses the persisted dashboard and channel definition rather than mutable latest telemetry samples.

### Truthful continuity and reduction

History is sorted deterministically and passed through canonical `buildChartSegments` with a 30-second source-gap boundary.

The renderer does not connect through invalid quality, missing measurements, source gaps above the boundary or other canonical continuity breaks supplied by the shared domain.

Alarm transitions pin both adjacent evidence points and are exposed as canonical chart event markers.

Visualization reduction uses canonical `reduceChartSegments` with a 240-point target. If mandatory evidence cannot fit that target, the mapper falls back to the already-bounded source history rather than dropping required evidence. The existing Saved Dashboard hook caps history at 500 samples per series and 8000 total samples, so this fallback remains bounded.

No statistics are computed from reduced visualization samples.

### Compatible units

`groupCompatibleChartUnits` remains authoritative. Compatible exact native units share synchronized plot groups. Incompatible quantities remain separate. There is no implicit conversion or default dual-axis mixing.

Cumulative energy remains separate from active power.

### Renderer

The independent `SeriesChart` SVG implementation was removed from `dashboard-live-view.tsx`.

Saved Dashboard line/area plots now use:

- `ChartShell`;
- `ChartRendererHost`;
- `EChartsRendererAdapter`;
- local modular ECharts Canvas rendering.

The canonical Chart Domain gained one optional presentation property, `areaFillOpacity`, and the ECharts adapter renders it as deterministic `areaStyle`. Existing line-only consumers are unchanged because the property is optional.

ECharts still uses `smooth: false` and `connectNulls: false`; each continuity segment is rendered independently, including area fills.

### Interaction and lifecycle

Saved Dashboard chart groups support shared cursor, show/hide, solo, zoom/pan, Reset zoom and reset to the persisted dashboard time-window viewport.

A renderer adapter is created once per mounted `DashboardChartPanel` and disposed by the canonical host on unmount.

Presentation interactions do not mutate the persisted dashboard definition.

The existing selected-series REST/history/WebSocket hook remains authoritative. `refresh_seconds` remains a render/display flush preference and does not alter physical acquisition cadence.

### Value and gauge

Persisted `value` and `gauge` items remain separate truthful current-value cards. No synthetic gauge range is introduced. Browser acceptance seeds an explicit latest projection and requires both cards to contain real values rather than `—`.

## Automated tests

Focused tests cover:

- persisted order and saved colors;
- line versus area presentation;
- compatible-unit grouping;
- invalid-quality continuity breaks;
- source-gap continuity breaks;
- alarm-transition evidence pins;
- cumulative-energy semantic mode;
- hide/solo behavior without identity mutation;
- persisted time-window viewport derivation;
- optional ECharts area fill without altering normal line rendering.

## Production browser acceptance

`e2e/live.production.e2e.ts` contains a focused Saved Dashboard Chart System acceptance flow.

The fixture creates four persisted items from one compatible measurement group:

1. line;
2. area;
3. value;
4. gauge.

It seeds bounded history plus an explicit local `telemetry_latest` projection.

The browser flow verifies canonical Canvas rendering, no legacy plot SVG, truthful value/gauge cards, show/hide/solo, zoom/pan/reset, responsive 360/1440/1920 layouts, no dashboard/acquisition mutations, zero public runtime requests and bounded close/reopen WebSocket lifecycle.

## Pre-hardware software candidate

Candidate `2b508d8a1c22ab28069c24833b792261b16193e6` passed the original complete software/browser/offline cycle:

- CI: GREEN;
- Authenticated Dashboard Acceptance: 12/12 GREEN;
- Acquisition Scale Acceptance: GREEN;
- Refrigeration Browser Acceptance: GREEN;
- Offline Bundle: GREEN, including disconnected startup and update/rollback persistent-data preservation.

## First controlled Raspberry Pi acceptance attempt

The Product Owner built and ran exact candidate `2b508d8a1c22ab28069c24833b792261b16193e6` on the controlled Raspberry Pi while leaving Telemetry Service, PostgreSQL, MQTT and Device Agent unchanged. Only the dashboard process was temporarily replaced.

### Acceptance-harness cleanup before baseline

An orphan `next-server` from the earlier Issue #400 temporary dashboard handoff was discovered holding port 3000. This caused `nexolab-dashboard.service` to repeatedly fail with `EADDRINUSE` and restart every five seconds.

The orphan process was terminated. Port 3000 was released. The production dashboard was restarted and observed as:

- `ActiveState=active`;
- `SubState=running`;
- `NRestarts=0`;
- HTTP 200;
- no new restart over the follow-up observation window.

This was an acceptance-harness/runtime cleanup issue and did not change backend data, acquisition configuration or hardware state.

### Equal-duration acquisition evidence

Both windows were 60 seconds.

| Metric              | Browser closed baseline | Active Saved Dashboard |
| ------------------- | ----------------------: | ---------------------: |
| physical requests   |                     156 |                    144 |
| physical requests/s |                   2.600 |                  2.400 |
| retry attempts      |                      18 |                     12 |
| successful requests |                     132 |                    132 |
| timeouts            |                      24 |                     12 |
| bus executions      |                     126 |                    120 |
| bus executions/s    |                   2.100 |                  2.000 |
| bus busy seconds    |                  13.819 |                 10.110 |

Acquisition state remained stable:

- scheduler policy unchanged;
- configured targets `38 -> 38`;
- poll-eligible targets `38 -> 38`;
- degraded endpoints `4 -> 4`;
- cooldown endpoints `4 -> 4`;
- service-operation mutation counters remained empty;
- `last_sample_at` advanced throughout both windows.

Acquisition conclusion: **PASS**. The active Saved Dashboard did not amplify physical acquisition.

### Visual result

The operator explicitly recorded:

`chart_visual_continuity=FAIL`

Therefore the physical acceptance as a whole was **FAIL** and PR #410 remained Draft.

The first manual test protocol also instructed the operator to return to the dashboard library and reopen the dashboard within the same window used for the continuity question. That intentional navigation necessarily unmounts the chart. The FAIL remains recorded, but the repeated test separates continuous live-point observation from intentional close/reopen lifecycle so the result is unambiguous.

## Corrective visual-continuity slice

Repository review showed that normal Saved Dashboard telemetry flushes rebuild a canonical scene and call ECharts `setOption` with the existing persistent instance. Before the corrective slice those rolling scene updates were animated. On Raspberry Pi this creates a credible blank-transition mechanism even though React and the ECharts instance remain mounted.

The corrective implementation passes `reducedMotion` to the Saved Dashboard `ChartRendererHost`, which makes Saved Dashboard rolling ECharts scene updates non-animated. This is scoped to the Saved Dashboard panel; it does not change acquisition or the global renderer contract.

The production browser acceptance was strengthened with a real local MQTT -> telemetry -> WebSocket live-point regression. Across the dashboard `refresh_seconds` interval it now proves:

- the same `ChartRendererHost` DOM node remains mounted;
- the same ECharts Canvas DOM node remains mounted;
- Canvas remains present after the new point;
- the live point does not trigger an additional history request;
- existing no-mutation, no-public-request and WebSocket lifecycle assertions still apply.

Corrective source head `67846013a8c7d357716321e2149509a2fb526f43` passed:

- CI: GREEN;
- Authenticated Dashboard Acceptance including the new real MQTT continuity regression: GREEN;
- Acquisition Scale Acceptance: GREEN;
- Refrigeration Browser Acceptance: GREEN;
- Offline Bundle including blocked egress, disconnected startup and update/rollback persistent-data preservation: GREEN.

## Repeated physical acceptance protocol

The next Raspberry Pi run must use the final exact corrective SHA after canonical state checkpointing and exact-head gates.

It must separate two phases:

### Phase A — continuous live-point visual continuity

- open one existing real Saved Dashboard containing a `line` or `area` chart;
- remain on that dashboard for the full bounded observation window;
- do not navigate to the library or another route;
- allow real telemetry points to arrive;
- chart host and plot must remain continuously visible with no blank/disappear cycle;
- compare equal-duration physical acquisition counters with browser-closed baseline.

### Phase B — intentional lifecycle

- leave to the Saved Dashboard library;
- verify the chart intentionally unmounts and WebSocket lifecycle cleans up;
- reopen the same dashboard;
- verify the chart initializes once and resumes truthful data;
- this intentional unmount is not counted as a Phase A visual-continuity failure.

## Offline and network boundary

No dependency version changed. ECharts remains the already-approved locally bundled renderer from Issue #386.

No CDN, remote font, analytics, cloud renderer, licensing request or other mandatory public runtime dependency was added.

## Acquisition and hardware boundary

Issue #404 changes no polling cadence, scheduler policy, registry eligibility, Device Agent configuration, Modbus behavior or hardware state.

No Modbus write or hardware write is present.

## Known limitation / truthful boundary

The existing Saved Dashboard telemetry hook exposes delivery state such as `reconnecting`, but it does not expose a timestamped reconnect-boundary event. The chart therefore preserves reconnecting as a separate freshness state and uses actual observed missing intervals as source-gap continuity breaks; it does not invent a timestamped reconnect break without source evidence.

## Current completion classification

`implementation corrected; first Raspberry Pi acquisition invariant PASS but visual continuity FAIL; corrective software/browser/offline verification GREEN; final exact-head checkpoint and repeated Raspberry Pi visual-continuity acceptance pending`
