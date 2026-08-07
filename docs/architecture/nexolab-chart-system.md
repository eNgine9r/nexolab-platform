# NEXOLAB Chart System — Technical Specification

**Status:** Proposed architecture baseline  
**Issue:** #383  
**Profile:** `LOCAL_LAN`  
**Baseline:** `main` at `329282496491d2ee27ab4f292e982a30af33c2b7`  
**Last reviewed:** 2026-08-07

## 1. Purpose

NEXOLAB uses charts as an operator and laboratory evidence surface, not as decorative dashboard widgets. This specification defines one common technical, UX and data-truthfulness contract for time-series and event visualizations across Overview, Live Data, saved Live Dashboards, Energy Monitoring, Test Sessions and Reports.

The system must satisfy four goals at the same time:

1. **Laboratory truthfulness** — displayed continuity, extrema, timestamps, units and states must match available evidence.
2. **Operator speed** — live views must remain responsive while data arrives and while routes are revisited.
3. **Visual consistency** — the same interaction, state and visual language must apply across product surfaces.
4. **Offline-first operation** — core charting must work from the local production bundle with no required internet, CDN, remote font or cloud visualization service.

This document is deliberately renderer-independent at the domain boundary. A renderer is an implementation detail below the NEXOLAB chart-domain model.

---

## 2. Non-negotiable architecture invariant

```text
Physical devices / controllers
        ↓
Device Agent / acquisition scheduler
        ↓
local latest/history/outbox
        ↓
Telemetry Service
        ↓
canonical REST snapshot/history + WebSocket stream
        ↓
shared telemetry/history reconciliation
        ↓
NEXOLAB chart-domain model
        ↓
chart renderer adapter
        ↓
operator visualization
```

Chart interaction must never reach upward through this stack to influence physical acquisition.

The following are presentation/query actions only:

- opening or closing a chart;
- selecting a display range;
- changing dashboard refresh preference;
- selecting/hiding/soloing a series;
- zooming or panning;
- moving or pinning a cursor;
- pausing live-follow;
- changing chart size;
- changing a supported display unit;
- exporting a local chart image.

None of those actions may change:

- acquisition registry eligibility;
- Modbus polling cadence;
- scheduler priority;
- Device Agent discovery/configuration;
- controller configuration;
- hardware state.

This preserves the architecture established by the telemetry optimization and Live Dashboard work.

---

## 3. Repository-backed current-state inventory

### 3.1 Overview / dashboard temperature history

**Current file:** `src/components/dashboard/temperature-chart.tsx`

Current characteristics:

- custom SVG renderer;
- `1h`, `6h`, `24h` presets;
- one path per valid temperature channel;
- shared auto-scaled y range;
- channel colors generated from a hash of the channel ID;
- loading/error/empty states;
- no common cursor/tooltip/zoom/pan contract;
- invalid/non-renderable samples are filtered before path construction.

Risk:

Filtering invalid samples before constructing one continuous path can visually connect two valid points across a real data-quality or communication break. The common chart system must replace that behavior with explicit segment continuity.

### 3.2 Live Data comparison

**Current files:**

- `src/components/live/live-telemetry-explorer.tsx`
- `src/features/live/live-history.ts`

Current reusable behavior:

- up to eight stable selected channel identities;
- incompatible units are rendered in separate synchronized groups;
- comparison groups share a cursor ratio;
- complete history windows are paginated against one stable ingestion snapshot watermark;
- downsampling happens after the requested window is loaded;
- source continuity is explicitly segmented;
- non-renderable quality creates a pending break;
- a source gap above `30_000 ms` creates a new segment;
- future skew is bounded;
- history is bounded to `240` rendered points per channel;
- WebSocket tail reconciliation ignores duplicate/out-of-order older samples.

This is the strongest current continuity model and must be reused as domain logic rather than copied into individual renderers.

Current downsampling limitation:

The bucket reducer retains one representative sample per bucket, plus first/last points and segment markers. This can omit a short local minimum or maximum inside a bucket. That is acceptable for a general shape preview but is not sufficient as the final evidence-oriented reduction contract.

### 3.3 Saved Live Dashboard

**Current file:** `src/components/live-dashboards/dashboard-live-view.tsx`

Current characteristics:

- selected-series-only data path;
- unit-grouped line/area plots;
- saved operator-selected colors;
- bounded history and explicit connection status;
- `line`, `area`, `value` and `gauge` presentation concepts;
- custom SVG plot for line/area groups.

Current gap:

The current line/area renderer builds a polyline from numeric samples and does not use the stronger Live Data segment model. The common system must eliminate this difference before the renderer is treated as laboratory-truthful.

### 3.4 Energy Monitoring

**Current files:**

- `src/components/energy/energy-workspace.tsx`
- `src/features/energy/energy-history-path.ts`

Current characteristics:

- custom SVG history;
- per-meter comparison;
- selected metric;
- `1h`, `6h`, `24h` presets;
- explicit energy history segment starts;
- fixed meter color map;
- current/stale/error state handling.

Energy-specific semantics must remain separate from temperature semantics. Instantaneous power, voltage, current, frequency and power factor are time-series measurements; cumulative active energy is a monotonic counter domain and must not be treated as a generic instantaneous signal.

Cumulative-energy visualization remains conditional on the hardware/semantic acceptance tracked separately by Issue #201.

### 3.5 Compact sparklines

**Current file:** `src/components/dashboard/sparkline.tsx`

Current characteristics:

- custom SVG;
- purely numeric points;
- no timestamps, quality or gap semantics;
- hidden from accessibility tree;
- intended as a compact trend cue.

A sparkline may remain a lightweight primitive, but production telemetry sparklines must not imply continuity when their source window contains a known outage. If a compact source cannot carry continuity metadata, it must be classified as a non-evidence trend cue and never replace a detailed chart.

### 3.6 Test Sessions and Reports

These surfaces require the common primitives but must not invent data semantics that are not yet present in their source contracts.

Planned common capabilities:

- session telemetry over one shared time domain;
- stage boundaries;
- alarm/event markers;
- operator annotations;
- door/defrost/system event lanes where those events exist;
- report-safe deterministic chart snapshots.

The chart layer consumes existing events. It does not infer or synthesize laboratory events.

---

## 4. Canonical chart-domain model

Renderer input must be normalized into a product-owned model rather than passing raw API payloads directly into a third-party chart option object.

Conceptual contract:

```ts
interface ChartSeriesIdentity {
  nodeId: string;
  equipmentId: string;
  channelId: string;
  metric: string;
  nativeUnit: string;
}

interface ChartPoint {
  eventId: string;
  capturedAt: string;
  value: number;
  quality: TelemetryQuality;
}

interface ChartSegment {
  identity: ChartSeriesIdentity;
  points: ChartPoint[];
}

interface ChartEvent {
  id: string;
  occurredAt: string;
  kind: "alarm" | "stage" | "annotation" | "system" | "door" | "defrost";
  severity?: string;
  label: string;
}

interface ChartSeriesModel {
  identity: ChartSeriesIdentity;
  displayLabel: string;
  displayUnit: string;
  segments: ChartSegment[];
  latest: ChartPoint | null;
  freshnessState: ChartFreshnessState;
  visualIdentity: ChartVisualIdentity;
}
```

The exact TypeScript names may change during implementation. The separation of responsibilities must not.

### 4.1 Three distinct state dimensions

NEXOLAB must not collapse all data state into one `status` or one color.

#### A. Measurement quality

Use the canonical telemetry vocabulary already defined by the product contract, currently including:

- `valid`;
- `sensor_error`;
- `communication_error`;
- `unknown`.

Do not create a chart-only replacement enum.

#### B. Freshness / delivery state

Derived presentation states can include:

- `live`;
- `stale`;
- `connecting`;
- `reconnecting`;
- `offline`;
- authorization/configuration/error states where applicable.

A last valid measured value may remain visible while delivery is reconnecting or offline, but it must not be labelled live.

#### C. Continuity

Continuity determines whether two measured points may be connected by a trace.

A new segment is required when:

- an explicit segment boundary exists;
- a non-renderable quality event interrupts the series;
- the source cadence gap exceeds the defined continuity threshold;
- a domain-specific reset/discontinuity is recorded;
- an implementation cannot prove continuity.

When uncertain, fail toward a visible break rather than invented continuity.

---

## 5. Time semantics

### 5.1 Source time

`captured_at` remains the measurement time source for telemetry plots.

- raw timestamps remain immutable;
- storage/API time semantics remain independent from browser locale;
- tooltips show the exact source timestamp at useful precision;
- UI may render in the configured laboratory/user timezone, but must make timezone context available;
- exports intended for evidence must preserve UTC timestamps in the underlying data contract.

### 5.2 Standard range vocabulary

The common selector vocabulary is:

- `Live`;
- `5 min`;
- `15 min`;
- `1 h`;
- `6 h`;
- `24 h`;
- `7 d`;
- custom bounded range where the product surface supports it.

A surface may expose a subset, but the meaning and labels must remain consistent.

Changing the range is a query/display operation only.

### 5.3 Live-follow state

`Live` is not merely a time duration. It is a viewport-follow mode.

Rules:

1. The right edge follows newest accepted data while live-follow is active.
2. Manual zoom or pan leaves live-follow and enters **Paused view**.
3. Data delivery continues into the shared bounded telemetry store while the viewport is paused.
4. A visible **Return to Live** action restores the newest viewport.
5. Pausing the viewport must not stop physical polling.
6. Pausing the viewport should not require tearing down the shared WebSocket connection.

---

## 6. Evidence-preserving continuity and downsampling

### 6.1 No invented interpolation

Default telemetry traces use straight measured-point segments.

Forbidden by default:

- spline smoothing that overshoots measured values;
- interpolation across known gaps;
- converting missing values to zero;
- silently replacing invalid measurements with previous values;
- visually hiding resets/discontinuities.

A future domain may explicitly approve interpolation, but that must be a separate documented semantic rule.

### 6.2 NEXOLAB evidence-preserving reduction

The first implementation should use a **segment-aware min/max envelope reduction** rather than a last-point-only bucket reducer.

For each independently continuous segment:

1. pin the first and last points;
2. pin points adjacent to explicit segment boundaries;
3. pin alarm/threshold crossing context when that metadata is available;
4. split the remaining time interval into deterministic buckets;
5. retain both the local minimum and local maximum from each bucket, in chronological order;
6. deduplicate identical event identities;
7. preserve deterministic captured-time ordering;
8. never merge points across segment boundaries.

This guarantees that a short excursion has a materially better chance of surviving visualization reduction than with one arbitrary/last sample per bucket.

If a future range still cannot be reduced to a safe client budget without excessive payload, add a separately scoped backend aggregate/read-model contract. Do not silently raise frontend limits until the browser receives unbounded history.

### 6.3 Threshold preservation

When upper/lower limits are defined, reduction must retain enough adjacent context to make a threshold excursion visible.

A downsampled chart must not claim `in range` merely because the reducer removed the actual excursion sample.

### 6.4 Statistics

`min`, `max` and `average` require an explicit source scope.

- statistics over full persisted raw history must be computed from the full requested evidence set or a backend aggregate proven equivalent;
- statistics must not be calculated from only the reduced render points and presented as full-window statistics;
- UI labels must distinguish full-window statistics from visible-viewport statistics if both are supported.

---

## 7. Units and y-axis policy

### 7.1 Unit compatibility

A single y-axis contains only compatible engineering quantities.

Examples:

- °C with °C — compatible;
- °C with °F — compatible only after an approved deterministic display conversion;
- kW with W — compatible only after deterministic unit normalization/conversion;
- °C with %RH — incompatible;
- V with A — incompatible;
- instantaneous kW with cumulative kWh — semantically incompatible.

### 7.2 Multiple incompatible quantities

The first common implementation must prefer **separate vertically stacked synchronized plots** over dual y-axes.

Dual y-axes are not part of the initial common primitive because they make accidental visual correlation easier and reduce evidence readability.

All synchronized plot groups share:

- x-domain;
- cursor timestamp;
- zoom selection;
- event markers where relevant.

Each group keeps its own y-domain and unit label.

### 7.3 Auto scale stability

Live charts must not visibly jump scale on every small sample change.

Auto-scale rules:

- include all visible valid values;
- include visible configured threshold/limit bands when those bands are part of the plot;
- apply deterministic visual padding;
- update scale only when data leaves the current padded domain or when the selected range changes;
- allow an explicit fixed display domain where a method/equipment definition requires it.

Do not clip an alarm excursion merely to preserve a pretty scale.

---

## 8. Domain visualization contracts

### 8.1 Temperature, humidity and pressure

Default presentation: line chart.

Required semantics:

- measured line is primary;
- current value remains available in legend/inspector;
- configured upper/lower limits are secondary bands/lines;
- active excursions are highlighted without recoloring the entire plot;
- communication/sensor gaps remain breaks;
- `min`, `max`, `average` can be shown for the selected evidence scope;
- sensor fault/missing state is represented separately from a numeric zero.

### 8.2 Instantaneous electrical measurements

Suitable time-series metrics include:

- voltage;
- current;
- active/reactive/apparent power where verified;
- frequency;
- power factor.

Rules:

- compare the same metric/unit across meters in one plot;
- do not put V, A, W and Hz on one y-axis;
- keep meter identity stable in the legend across metric switches where possible;
- communication gaps and quality follow the same canonical continuity model.

### 8.3 Cumulative energy

Cumulative active energy requires its own semantic mode after Issue #201 verifies the register, scale, rollover/reset behavior and unit.

Until then, the chart system must not fabricate `kWh` history or interval consumption.

After hardware acceptance:

- cumulative energy is visualized as a monotonic counter trace with explicit reset/discontinuity markers;
- counter reset/rollover is not drawn as ordinary negative consumption;
- interval consumption is a derived series, not a relabelled counter;
- any interval bars/areas must state the derivation window.

### 8.4 Test Session timeline

A session view uses one synchronized time domain with separate visual lanes:

```text
Telemetry plots
────────────────────────────────
Stage lane
────────────────────────────────
Alarm / deviation lane
────────────────────────────────
Operator annotations
────────────────────────────────
Door / defrost / system events (when available)
```

Events are immutable evidence markers from their source domain. The renderer must not infer a stage, alarm or door event from visual pattern recognition.

### 8.5 Reports

Report charts must be reproducible from persisted data and configuration snapshots.

- report rendering uses a deterministic range/domain;
- charts may reuse the same domain model;
- interactive-only affordances are removed from static output;
- image export does not become the source of numerical truth;
- CSV/XLSX/raw evidence remain separate structured exports.

---

## 9. Common Chart Shell

The shared chart shell owns presentation controls around a plot, not telemetry acquisition.

```text
┌──────────────────────────────────────────────────────────────┐
│ Title / scope       freshness        time range      actions │
│ Secondary context / statistics                              │
├──────────────────────────────────────────────────────────────┤
│ Plot / synchronized plot group                              │
│  • threshold regions                                        │
│  • measured segments                                        │
│  • alarm/event markers                                      │
│  • shared crosshair                                         │
├──────────────────────────────────────────────────────────────┤
│ Interactive legend / value inspector                        │
└──────────────────────────────────────────────────────────────┘
```

### 9.1 Required shell states

- first load with no previous snapshot;
- usable cached/persisted snapshot + background reconciliation;
- empty;
- live;
- stale;
- reconnecting;
- offline;
- forbidden/unauthorized where applicable;
- configuration error;
- history error with retry.

If a valid previous snapshot exists, background reconciliation must not blank the plot.

---

## 10. Interaction contract

### 10.1 Cursor and tooltip

Desktop/operator behavior:

- pointer move shows one shared vertical crosshair;
- all synchronized groups inspect the same timestamp;
- each series reports nearest valid sample and exact sample timestamp;
- if no sample exists within the applicable source-cadence tolerance, show `—` rather than borrowing a distant value;
- tooltip includes value, unit, series identity, quality/freshness cue and timestamp;
- clicking/pointer activation can pin the inspector.

Keyboard behavior must provide an equivalent path to move between timestamp/sample positions and inspect values.

### 10.2 Legend

Each legend item supports:

- identity label;
- current/inspected value;
- unit;
- visible/hidden state;
- optional quality/freshness cue;
- show/hide;
- solo/focus action.

Legend state changes display only. They do not alter subscriptions or acquisition unless a separately defined product optimization changes only the browser payload contract and preserves the physical polling invariant.

### 10.3 Zoom, pan and reset

- wheel/gesture/selection zoom must be bounded to available history;
- pan never requests data outside permitted server bounds without an explicit history query;
- reset restores the selected range;
- zoom/pan from `Live` enters Paused view;
- synchronized plot groups share the x viewport.

### 10.4 Event selection

Event markers can be keyboard/pointer selected to expose:

- event type;
- timestamp;
- source;
- severity/status;
- associated measured context if available.

A marker cannot obscure the raw trace permanently; dense events require clustering/lane treatment rather than an unreadable pile of icons.

---

## 11. Visual language and chart tokens

The chart system extends the existing NEXOLAB Modern Industrial Tech design system.

### 11.1 Base tokens

| Role | Existing baseline |
| --- | --- |
| Background | `#06142A` |
| Deep navy | `#0B1D3A` |
| Steel blue | `#132E5F` |
| Primary | `#0077FF` |
| Cyan | `#00C6E0` |
| Success | `#22C55E` |
| Warning | `#F5B301` |
| Danger | `#FF4D4F` |
| Text primary | `#E6ECF2` |

### 11.2 Chart visual rules

- primary time-series traces: nominally `2–2.5 px` on desktop/operator surfaces;
- grid lines: low-contrast and subordinate to measurements;
- axes: visible enough for laboratory reading, not decorative;
- plot surface: dark cold-tech surface integrated with the containing panel;
- active/hover series receives stronger contrast, not a large glow;
- critical state uses localized red accent and never turns the entire chart red;
- line style, marker shape, direct label or decal supplements color for state/category discrimination where required;
- no neon rainbow palette generated arbitrarily from channel IDs.

### 11.3 Deterministic series palette

The canonical ordered palette begins with the existing product colors:

1. `#00C6E0`
2. `#7ED321`
3. `#0077FF`
4. `#A855F7`
5. `#F5B301`
6. `#14B8A6`
7. `#F97316`
8. `#F43F5E`

Implementation must validate contrast against the chart surface and pair colors with non-color identity cues when needed.

Persistent Live Dashboard colors remain operator preferences but must pass an accessibility/contrast validation policy before save or receive an accessible fallback treatment.

---

## 12. Accessibility

Charts must not require visual color discrimination alone.

Required baseline:

- meaningful chart title/summary;
- keyboard-operable controls;
- visible focus states;
- semantic labels on time-range, legend and action controls;
- a screen-reader-readable summary of range, series count, units, freshness and important alarms;
- an optional structured data table/inspector path for exact values when practical;
- color supplemented by label, dash, marker, status text or pattern;
- reduced-motion mode disables nonessential animated transitions;
- live updates must not spam an ARIA live region for every sample.

If the renderer uses Canvas, accessibility remains an application responsibility. Renderer-provided ARIA is additive, not a substitute for NEXOLAB controls and summaries.

---

## 13. Responsive behavior

### 13.1 Mobile / narrow viewport

- no page-level horizontal overflow caused by a nominal chart canvas width;
- plot fits available width;
- controls wrap or collapse into a compact menu;
- legend becomes collapsible/stacked;
- x-axis labels reduce density rather than overlap;
- minimum useful plot height is maintained;
- touch targets remain approximately 40 px or greater;
- cursor inspection supports tap/pinned inspector behavior.

Dense eight-series comparison remains available, but the UI may encourage solo/focus and collapsed legend behavior on narrow screens.

### 13.2 Standard desktop — 1440 px

Primary design target:

- full shell controls visible;
- interactive legend visible;
- synchronized multi-plot groups readable without horizontal page scrolling;
- exact tooltip/crosshair interactions enabled.

### 13.3 Operator display — 1920 px

- more x-axis label density may be shown;
- more legend/statistics context may remain expanded;
- line thickness and text must not shrink merely because more space is available;
- the display must remain readable at control-room viewing distances.

---

## 14. Performance and lifecycle contract

These are **provisional implementation targets**, not claims about current code. They must be validated on the controlled Raspberry Pi/browser during implementation and can be tightened after the first benchmark.

### 14.1 Bounded series

- common interactive multi-series plot default: maximum `8` visible series, preserving the current Live Data comparison contract;
- larger dashboards split compatible series into explicit groups rather than making one unreadable plot;
- compact single-series sparklines remain separately bounded.

### 14.2 Bounded points

- current accepted baseline is `240` rendered points per channel in Live Data;
- the first common primitive must remain bounded at least as strictly until a benchmark justifies a larger value;
- any increase must be based on measured Raspberry Pi browser performance and the evidence-preserving reducer;
- full raw history must not be rendered merely because a client machine can temporarily handle it.

### 14.3 Render targets

For an already available normalized dataset of up to eight series at the accepted point budget:

- target initial plot render after data readiness: `≤ 250 ms` p95 on the controlled Raspberry Pi browser;
- hard acceptance ceiling for plot-only rendering: `≤ 1 s` under normal local load;
- target incremental live update work: `≤ 100 ms` p95 and no full React route/panel remount;
- pointer/keyboard inspection should remain perceptibly immediate and not block route navigation.

These timings isolate chart rendering from backend/network latency. End-to-end route latency remains governed by the broader performance work (#356/#289).

### 14.4 Long-lived lifecycle

- one chart instance per visible plot/group;
- update the existing renderer instance rather than destroy/recreate it per telemetry sample;
- dispose renderer resources on true unmount;
- use bounded shared telemetry/history storage;
- resize through one observer/lifecycle path;
- background/hidden charts must not accumulate unbounded animation or event work;
- route returns should reuse valid shared telemetry snapshots and remain truthful while reconciling.

### 14.5 Physical request invariant

Browser count, chart count and visualization settings must not increase physical Modbus requests outside the existing scheduler envelope.

This is a hard acceptance gate and is finally measured under #289.

---

## 15. Renderer decision

### 15.1 Current state

NEXOLAB currently has no chart dependency and uses hand-authored SVG. This kept the first vertical slices small but now creates duplicated scale/path/legend/state behavior across routes.

Continuing with only route-local SVG is not recommended because the product now needs:

- synchronized cursors;
- zoom/pan;
- multiple synchronized plot groups;
- event/threshold overlays;
- responsive lifecycle;
- Canvas-level performance headroom;
- consistent accessibility hooks;
- repeatable export behavior.

### 15.2 Preferred implementation candidate: Apache ECharts 6.1

As of this specification date, the official Apache ECharts project advertises version 6.1 and supports:

- Canvas and SVG rendering;
- progressive rendering / stream-oriented large-data behavior;
- modular npm imports such as `echarts/core`;
- responsive charts;
- WAI-ARIA support and decal patterns;
- Apache License 2.0.

Official references reviewed on 2026-08-07:

- `https://echarts.apache.org/en/`
- `https://echarts.apache.org/handbook/en/basics/import/`
- `https://echarts.apache.org/handbook/en/best-practices/canvas-vs-svg/`
- `https://echarts.apache.org/handbook/en/best-practices/aria/`

### 15.3 NEXOLAB integration direction

If the implementation benchmark confirms the candidate:

- install an exact repository-managed npm dependency and lockfile through a separate Issue/PR;
- use local bundled modules only — never runtime CDN loading;
- prefer tree-shakable `echarts/core` imports for required line/bar/custom components;
- start with Canvas for interactive telemetry plots where element count is material;
- keep the renderer behind a NEXOLAB-owned adapter;
- do not add a second React wrapper dependency unless a verified lifecycle gap requires it;
- domain continuity/downsampling/state logic stays outside ECharts options;
- no renderer API leaks into Telemetry Service or acquisition contracts.

### 15.4 Required benchmark before adoption

The separate foundation implementation Issue must compare the candidate against the current custom SVG baseline using representative fixtures:

1. 1 series × 240 points;
2. 8 series × 240 points;
3. multiple synchronized compatible-unit groups;
4. explicit gaps and alarm markers;
5. incremental live tail updates;
6. resize and route remount/reuse;
7. mobile/narrow viewport;
8. disconnected production bundle startup.

Measure:

- bundle delta;
- initial render time;
- incremental update time;
- memory trend;
- interaction responsiveness;
- accessibility output;
- offline/local-bundle behavior.

Adoption is not complete until those results are recorded.

---

## 16. Proposed component boundary

The implementation should converge on a structure similar to:

```text
src/features/charts/
├── domain/
│   ├── continuity.ts
│   ├── downsampling.ts
│   ├── units.ts
│   ├── statistics.ts
│   └── types.ts
├── presentation/
│   ├── chart-shell.tsx
│   ├── chart-legend.tsx
│   ├── chart-inspector.tsx
│   ├── chart-range-control.tsx
│   └── chart-state.tsx
└── renderer/
    ├── chart-renderer.ts
    └── echarts-adapter.tsx   # only if/after renderer adoption
```

Exact filenames are implementation details. The dependency direction is mandatory:

```text
product pages
    ↓
chart presentation + chart domain
    ↓
renderer adapter
    ↓
third-party renderer
```

The third-party renderer must never become the source of NEXOLAB telemetry semantics.

---

## 17. Testing strategy

### 17.1 Domain unit tests

Must cover:

- segment break after invalid quality;
- segment break after source gap;
- no line across offline interval;
- first/last preservation;
- min/max preservation in every reduced bucket;
- chronological order when max occurs before min and vice versa;
- threshold crossing preservation;
- duplicate event identity handling;
- out-of-order live event handling;
- compatible/incompatible unit grouping;
- statistics scope correctness.

### 17.2 Component tests

Must cover:

- loading/empty/error/retry;
- stale/reconnecting/offline with last valid snapshot retained;
- legend show/hide/solo;
- range changes;
- paused-view / Return to Live;
- synchronized cursor state;
- accessible labels and keyboard controls;
- reduced-motion behavior.

### 17.3 Browser acceptance

Representative flows:

1. open Live Data with multiple temperature channels;
2. verify gaps are visible;
3. inspect exact values with synchronized cursor;
4. zoom/pan then return to Live;
5. interrupt WebSocket and verify last snapshot remains visible but not live;
6. switch range without physical acquisition mutation;
7. open Energy and compare meters for one metric;
8. exercise 1440 px, 1920 px and narrow viewport;
9. verify no horizontal page overflow;
10. record chart lifecycle/render performance.

### 17.4 Offline acceptance

- production bundle includes all required chart code locally;
- disconnected startup uses `--pull never` where the existing Offline Bundle gate requires it;
- no chart script/font/assets are requested from the public internet;
- no cloud visualization API is required.

### 17.5 Hardware boundary

Chart-domain correctness can be software verified with deterministic telemetry fixtures.

Real Raspberry Pi acceptance is required for:

- final browser performance budgets;
- route perceived latency;
- proof that browser/chart count does not change physical Modbus request rate.

No hardware write is required or permitted.

---

## 18. Migration strategy

Do not replace every chart in one PR.

Recommended child Work Packages:

### WP-A — Chart domain primitives and renderer benchmark

- segment-aware evidence-preserving reducer;
- unit grouping;
- common chart types;
- renderer adapter contract;
- ECharts 6.1 local-bundle benchmark;
- no route migration beyond a deterministic fixture/harness.

### WP-B — Live Data migration

Use the strongest existing telemetry history/reconciliation domain as the first production consumer.

- common Chart Shell;
- synchronized cursor/inspector;
- zoom/pan/live-follow;
- preserve all #263 behavior;
- browser performance acceptance.

### WP-C — Live Dashboard migration

- remove route-local raw polyline semantics;
- reuse common segmentation/downsampling;
- preserve saved visualization/color preferences;
- selected-series-only transport remains unchanged.

### WP-D — Overview temperature chart migration

- eliminate hashed channel colors;
- reuse common continuity;
- keep Overview concise;
- no duplicate data store or polling path.

### WP-E — Energy migration

- common shell/renderer;
- preserve energy segment semantics;
- same-metric meter comparison;
- cumulative-energy mode remains gated by #201 hardware semantics.

### WP-F — Test Session event timeline

- synchronized telemetry and event lanes;
- stage/alarm/annotation evidence;
- no inferred events.

### WP-G — Report/static chart output

- deterministic report snapshots;
- shared style tokens;
- structured data remains the numerical evidence source.

Each child remains one Issue, one branch and one focused PR.

---

## 19. Explicit out of scope for the chart system foundation

- changing Modbus registers or writes;
- changing polling frequency/priority;
- changing acquisition registry eligibility;
- redesigning Telemetry Service schema without a separate proven requirement;
- silently changing history retention;
- using a mandatory cloud chart service;
- using CDN-loaded renderer code or fonts;
- arbitrary formulas or user-supplied chart code;
- predictive/AI-generated values presented as measured telemetry;
- remote hardware control;
- production/site cutover.

---

## 20. Definition of Done for the future unified system

The NEXOLAB chart system is complete only when:

- all major telemetry chart surfaces consume one chart-domain continuity contract;
- gaps and quality failures are truthful everywhere;
- wide history cannot hide relevant extrema through unsafe reduction;
- units/axes are deterministic and compatible;
- cursor/tooltip/range/legend/zoom/live-follow behavior is consistent;
- temperature, energy and session/event semantics remain domain-correct;
- charts are keyboard accessible and not color-only;
- mobile, 1440 px and 1920 px layouts are accepted;
- renderer lifecycle is bounded and performant on Raspberry Pi;
- Offline Bundle works without public network resources;
- browser count does not alter the physical polling envelope;
- each migration has targeted tests, exact-head CI and evidence.

Until real Raspberry Pi browser/performance acceptance is attached, implementation completion must be reported as:

```text
software verified; Raspberry Pi chart performance/acquisition-invariant acceptance pending
```
