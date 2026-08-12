# Issue #404 — Saved Live Dashboard canonical Chart System migration audit

Updated: 2026-08-12

## Scope

Issue #404 migrates only persisted Saved Live Dashboard `line` / `area` history rendering to the canonical NEXOLAB Chart System established by Issue #386 and already consumed by Live Data in Issue #400.

Issue #369 remains separate and owns Raspberry Pi inventory/filter/select/save editor acceptance. This Work Package does not change dashboard CRUD, ETag/versioning, channel inventory, backend telemetry contracts, polling, scheduler, registry, Device Agent or Modbus behavior.

Implementation baseline: `main=f3462861db2a3593e2072a7bad70d557c009b323`.

Feature branch: `feat/404-saved-live-dashboard-chart-system`.

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

The renderer therefore does not connect through:

- invalid quality;
- missing measurements;
- source gaps above the canonical Saved Dashboard boundary;
- other canonical continuity breaks supplied by the shared domain.

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

Saved Dashboard chart groups support:

- shared cursor;
- show/hide;
- solo;
- zoom/pan through the canonical ECharts inside-dataZoom path;
- Reset zoom;
- reset to the persisted dashboard time-window viewport.

A renderer adapter is created once per mounted `DashboardChartPanel` and disposed by the canonical host on unmount.

Presentation interactions do not mutate the persisted dashboard definition.

The existing selected-series REST/history/WebSocket hook remains unchanged. `refresh_seconds` remains a render/display flush preference and does not alter physical acquisition cadence.

### Value and gauge

Persisted `value` and `gauge` items remain separate truthful current-value cards. No synthetic gauge range is introduced. Browser acceptance seeds an explicit latest projection and requires both cards to contain real values rather than `—`.

## Automated tests

Added focused tests for:

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

Targeted checks already run on the feature branch:

- touched-file Prettier: GREEN;
- TypeScript typecheck: GREEN;
- canonical chart + Saved Dashboard focused test suites: GREEN.

## Production browser acceptance added

`e2e/live.production.e2e.ts` now contains a focused Saved Dashboard Chart System acceptance flow.

The fixture creates four persisted items from one compatible measurement group:

1. line;
2. area;
3. value;
4. gauge.

It seeds bounded history plus an explicit local `telemetry_latest` projection using deterministic local database fixtures. No acquisition or hardware operation is used to create the fixture.

The browser flow requires:

- exactly one compatible-unit Saved Dashboard chart panel for the two plotted series;
- canonical `chart-renderer-host` and accessible summary;
- Canvas renderer present and no legacy plot SVG in the panel;
- both plotted channel identities visible;
- value and gauge cards present with real values;
- show/hide and solo controls;
- zoom/pan input followed by Reset zoom;
- renderer remains visible during interaction;
- no additional history request caused by presentation interactions;
- no dashboard mutation request;
- no acquisition mutation request;
- zero public runtime requests;
- no page-level horizontal overflow at 360, 1440 and 1920 px;
- dashboard close/reopen lifecycle does not increase the established WebSocket maximum.

This production browser flow has been authored and typechecked, but the full authenticated production acceptance stack has not yet been run on the final PR head. Its result must be recorded before Ready/merge.

## Offline and network boundary

No dependency version changed. ECharts remains the already-approved locally bundled renderer from Issue #386.

No CDN, remote font, analytics, cloud renderer, licensing request or other mandatory public runtime dependency was added.

The final Offline Bundle job is still required before Ready/merge.

## Acquisition and hardware boundary

Issue #404 changes no:

- polling cadence;
- scheduler policy;
- registry eligibility;
- Device Agent configuration;
- Modbus behavior;
- hardware state.

No Modbus write or hardware write is present.

Controlled Raspberry Pi Saved Dashboard acceptance is **not yet run** and is not claimed. It must be performed only after software/browser/offline gates are GREEN, with equal-duration physical acquisition counters compared against a browser-idle baseline.

## Known limitation / truthful boundary

The existing Saved Dashboard telemetry hook exposes delivery state such as `reconnecting`, but it does not expose a timestamped reconnect-boundary event. The chart therefore preserves reconnecting as a separate freshness state and uses actual observed missing intervals as source-gap continuity breaks; it does not invent a timestamped reconnect break without source evidence.

## Current completion classification

`implementation complete; targeted software checks GREEN; production browser/offline exact-head verification pending; Raspberry Pi Saved Dashboard acceptance pending`
