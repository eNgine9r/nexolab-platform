# NEXOLAB Chart System — Technical Specification

**Status:** Proposed architecture baseline

**Issue:** #383

**Profile:** `LOCAL_LAN`

**Baseline:** `main` at `329282496491d2ee27ab4f292e982a30af33c2b7`

**Last reviewed:** 2026-08-07

## 1. Purpose

NEXOLAB uses charts as operator and laboratory evidence surfaces, not as decorative dashboard widgets. This specification defines one common technical, UX and data-truthfulness contract for time-series and event visualizations across Overview, Live Data, saved Live Dashboards, Energy Monitoring, Test Sessions and Reports.

The chart system has four simultaneous goals:

- laboratory truthfulness: displayed continuity, extrema, timestamps, units and states match available evidence;
- operator speed: live views stay responsive while data arrives and when routes are revisited;
- visual consistency: the same interactions, states and visual language apply across product surfaces;
- offline-first operation: core charting works from the local production bundle with no required internet, CDN, remote font or cloud visualization service.

The domain boundary is renderer-independent. A renderer is an implementation detail below the NEXOLAB chart-domain model.

## 2. Non-negotiable architecture invariant

The dependency flow is one-way:

- physical devices and controllers;
- Device Agent and acquisition scheduler;
- local latest/history/outbox state;
- Telemetry Service;
- canonical REST snapshot/history and WebSocket stream;
- shared telemetry/history reconciliation;
- NEXOLAB chart-domain model;
- chart renderer adapter;
- operator visualization.

Chart interaction must never reach upward through this stack to influence physical acquisition.

The following are presentation or query actions only:

- opening or closing a chart;
- selecting a display range;
- changing dashboard refresh preference;
- selecting, hiding or soloing a series;
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
- Device Agent discovery or configuration;
- controller configuration;
- hardware state.

This preserves the architecture established by the telemetry optimization and Live Dashboard work.

## 3. Repository-backed current-state inventory

### 3.1 Overview temperature history

Current file: `src/components/dashboard/temperature-chart.tsx`.

Current characteristics:

- custom SVG renderer;
- `1h`, `6h` and `24h` presets;
- one path per valid temperature channel;
- shared auto-scaled y range;
- channel colors generated from a channel-ID hash;
- loading, error and empty states;
- no common cursor, tooltip, zoom or pan contract;
- invalid or non-renderable samples are filtered before path construction.

Current risk:

Filtering invalid samples before constructing one continuous path can visually connect two valid points across a real data-quality or communication break. The common chart system must replace that behavior with explicit segment continuity.

### 3.2 Live Data comparison

Current files:

- `src/components/live/live-telemetry-explorer.tsx`;
- `src/features/live/live-history.ts`.

Current reusable behavior:

- up to eight stable selected channel identities;
- incompatible units render in separate synchronized groups;
- comparison groups share a cursor ratio;
- complete history windows are paginated against one stable ingestion snapshot watermark;
- downsampling happens after the requested window is loaded;
- source continuity is explicitly segmented;
- non-renderable quality creates a pending break;
- a source gap above `30_000 ms` creates a new segment;
- future skew is bounded;
- history is bounded to `240` rendered points per channel;
- WebSocket tail reconciliation ignores duplicate or out-of-order older samples.

This is the strongest current continuity model and must be reused as domain logic rather than copied into individual renderers.

Current downsampling limitation:

The reducer keeps one representative point per bucket together with first, last and segment-boundary points. A short local minimum or maximum can therefore disappear. That is acceptable for a shape preview but is not sufficient as the final evidence-oriented reduction contract.

### 3.3 Saved Live Dashboard

Current file: `src/components/live-dashboards/dashboard-live-view.tsx`.

Current characteristics:

- selected-series-only data path;
- unit-grouped line and area plots;
- saved operator-selected colors;
- bounded history and explicit connection status;
- `line`, `area`, `value` and `gauge` presentation concepts;
- custom SVG plot for line and area groups.

Current gap:

The current line and area renderer builds a polyline from numeric samples and does not use the stronger Live Data segment model. The common system must eliminate this difference before the renderer is treated as laboratory-truthful.

### 3.4 Energy Monitoring

Current files:

- `src/components/energy/energy-workspace.tsx`;
- `src/features/energy/energy-history-path.ts`.

Current characteristics:

- custom SVG history;
- per-meter comparison;
- selected metric;
- `1h`, `6h` and `24h` presets;
- explicit energy history segment starts;
- fixed meter color map;
- current, stale and error-state handling.

Energy-specific semantics must remain separate from temperature semantics. Instantaneous power, voltage, current, frequency and power factor are time-series measurements. Cumulative active energy is a counter domain and must not be treated as a generic instantaneous signal.

Cumulative-energy visualization remains conditional on the separate hardware and semantic acceptance tracked by Issue #201.

### 3.5 Compact sparklines

Current file: `src/components/dashboard/sparkline.tsx`.

Current characteristics:

- custom SVG;
- numeric points only;
- no timestamp, quality or gap semantics;
- hidden from the accessibility tree;
- intended as a compact trend cue.

A sparkline may remain lightweight, but production telemetry sparklines must not imply continuity when their source window contains a known outage. A compact source without continuity metadata is a non-evidence trend cue and cannot replace a detailed chart.

### 3.6 Test Sessions and Reports

These surfaces require common chart primitives but must not invent semantics absent from their source contracts.

Planned common capabilities include:

- session telemetry on one shared time domain;
- stage boundaries;
- alarm and event markers;
- operator annotations;
- door, defrost and system-event lanes where those events exist;
- deterministic report-safe chart snapshots.

The chart layer consumes existing events. It does not infer or synthesize laboratory events.

## 4. Canonical chart-domain responsibilities

Renderer input must be normalized into a product-owned model rather than passing raw API payloads directly into a third-party renderer configuration.

The chart-domain model owns:

- stable series identity composed from node, equipment, channel, metric and native unit;
- captured timestamp;
- numeric value;
- canonical measurement quality;
- explicit segment boundaries;
- display label and display unit;
- derived freshness or delivery state;
- deterministic visual identity;
- optional threshold and event overlays supplied by their source domains.

The exact TypeScript names are implementation details. The separation of responsibilities is mandatory.

### 4.1 Three distinct state dimensions

NEXOLAB must not collapse all data state into one status or one color.

#### Measurement quality

Use the canonical telemetry vocabulary already defined by the product contract, currently including:

- `valid`;
- `sensor_error`;
- `communication_error`;
- `unknown`.

Do not create a chart-only replacement enum.

#### Freshness and delivery state

Derived presentation states can include:

- `live`;
- `stale`;
- `connecting`;
- `reconnecting`;
- `offline`;
- authorization, configuration and error states where applicable.

A last valid measured value may remain visible while delivery is reconnecting or offline, but it must not be labelled live.

#### Continuity

Continuity determines whether two measured points may be connected by a trace.

A new segment is required when:

- an explicit segment boundary exists;
- a non-renderable quality event interrupts the series;
- the source cadence gap exceeds the defined continuity threshold;
- a domain-specific reset or discontinuity is recorded;
- the implementation cannot prove continuity.

When continuity is uncertain, fail toward a visible break rather than invented continuity.

## 5. Time semantics

### 5.1 Source time

`captured_at` remains the measurement time source for telemetry plots.

Rules:

- raw timestamps remain immutable;
- storage and API time semantics remain independent from browser locale;
- tooltips expose the exact source timestamp at useful precision;
- UI may render in the configured laboratory or user timezone, but timezone context must be available;
- evidence exports preserve UTC timestamps in the underlying structured data contract.

### 5.2 Standard range vocabulary

The common selector vocabulary is:

- `Live`;
- `5 min`;
- `15 min`;
- `1 h`;
- `6 h`;
- `24 h`;
- `7 d`;
- a custom bounded range where the product surface supports it.

A surface may expose a subset, but meaning and labels remain consistent.

Changing range is a query or display operation only.

### 5.3 Live-follow state

`Live` is a viewport-follow mode, not merely a duration.

Rules:

- the right edge follows newest accepted data while live-follow is active;
- manual zoom or pan leaves live-follow and enters `Paused view`;
- data delivery continues into the shared bounded telemetry store while the viewport is paused;
- a visible `Return to Live` action restores the newest viewport;
- pausing the viewport does not stop physical polling;
- pausing the viewport should not tear down the shared WebSocket connection.

## 6. Evidence-preserving continuity and downsampling

### 6.1 No invented interpolation

Default telemetry traces use straight measured-point segments.

Forbidden by default:

- spline smoothing that can overshoot measured values;
- interpolation across known gaps;
- converting missing values to zero;
- silently replacing invalid measurements with previous values;
- visually hiding resets or discontinuities.

A future domain may explicitly approve interpolation only through a separate documented semantic rule.

### 6.2 Segment-aware min/max reduction

The first common implementation should replace last-point-only bucket reduction with a segment-aware min/max envelope reducer.

For every independently continuous segment, the reducer must:

- pin the first and last points;
- pin points adjacent to explicit segment boundaries;
- pin alarm or threshold-crossing context when that metadata is available;
- divide the remaining time interval into deterministic buckets;
- retain both local minimum and local maximum from each bucket in chronological order;
- deduplicate identical event identities;
- preserve deterministic captured-time ordering;
- never merge points across segment boundaries.

If a wide history range still cannot be reduced to a safe client budget without excessive payload, add a separately scoped backend aggregate or read-model contract. Do not silently raise frontend limits until the browser receives unbounded history.

### 6.3 Threshold preservation

When upper or lower limits exist, reduction must retain enough adjacent context to make an excursion visible.

A reduced chart must not appear in-range merely because the reducer removed the excursion sample.

### 6.4 Statistics

`min`, `max` and `average` require an explicit source scope.

Rules:

- full-window statistics use the full requested evidence set or a backend aggregate proven equivalent;
- statistics from reduced render points must never be labelled as full-window statistics;
- if both full-window and visible-viewport statistics exist, the UI distinguishes them explicitly.

## 7. Units and y-axis policy

### 7.1 Unit compatibility

One y-axis contains only compatible engineering quantities.

Examples:

- °C with °C is compatible;
- °C with °F is compatible only after an approved deterministic display conversion;
- kW with W is compatible only after deterministic unit normalization or conversion;
- °C with %RH is incompatible;
- V with A is incompatible;
- instantaneous kW with cumulative kWh is semantically incompatible.

### 7.2 Incompatible quantities

The first common implementation prefers separate vertically stacked synchronized plots over dual y-axes.

Dual y-axes are not part of the initial common primitive because they make accidental visual correlation easier and reduce evidence readability.

All synchronized plot groups share:

- x-domain;
- cursor timestamp;
- zoom selection;
- relevant event markers.

Each group keeps its own y-domain and unit label.

### 7.3 Auto-scale stability

Live charts must not visibly jump scale on every small sample change.

Auto-scale must:

- include all visible valid values;
- include configured threshold or limit bands when those bands are part of the plot;
- apply deterministic visual padding;
- update only when data leaves the current padded domain or the selected range changes;
- allow an explicit fixed display domain where a method or equipment definition requires it.

An alarm excursion must never be clipped merely to preserve a visually stable scale.

## 8. Domain visualization contracts

### 8.1 Temperature, humidity and pressure

Default presentation is a line chart.

Required semantics:

- measured line is primary;
- current value remains available in the legend or inspector;
- configured upper and lower limits are secondary bands or lines;
- active excursions are highlighted without recoloring the whole plot;
- communication and sensor gaps remain breaks;
- `min`, `max` and `average` may be shown for the selected evidence scope;
- sensor fault or missing state is separate from numeric zero.

### 8.2 Instantaneous electrical measurements

Suitable time-series metrics include:

- voltage;
- current;
- active, reactive and apparent power where verified;
- frequency;
- power factor.

Rules:

- compare the same metric and unit across meters in one plot;
- do not put V, A, W and Hz on one y-axis;
- keep meter identity stable in the legend across metric switches where possible;
- communication gaps and quality follow the canonical continuity model.

### 8.3 Cumulative energy

Cumulative active energy requires its own semantic mode after Issue #201 verifies register, scale, rollover or reset behavior and unit.

Until then, the chart system must not fabricate `kWh` history or interval consumption.

After hardware acceptance:

- cumulative energy is visualized as a counter trace with explicit reset or discontinuity markers;
- counter reset or rollover is not drawn as ordinary negative consumption;
- interval consumption is a derived series, not a relabelled counter;
- interval bars or areas state the derivation window.

### 8.4 Test Session timeline

A session view uses one synchronized time domain with separate visual lanes for:

- telemetry plots;
- stage boundaries;
- alarm and deviation events;
- operator annotations;
- door, defrost and system events when available.

Events are immutable evidence markers from their source domain. The renderer does not infer a stage, alarm or door event from visual patterns.

### 8.5 Reports

Report charts must be reproducible from persisted data and configuration snapshots.

Rules:

- report rendering uses a deterministic range and domain;
- reports may reuse the same chart-domain model;
- interactive-only affordances disappear from static output;
- image export does not become the source of numerical truth;
- CSV, XLSX and raw evidence remain separate structured exports.

## 9. Common Chart Shell

The shared shell owns presentation controls around a plot, not telemetry acquisition.

It includes:

- title and scope;
- freshness state;
- time-range control;
- plot or synchronized plot group;
- threshold regions;
- measured segments;
- alarm or event markers;
- shared crosshair;
- interactive legend and value inspector;
- applicable local actions.

### 9.1 Required shell states

The shell handles:

- first load with no previous snapshot;
- usable cached or persisted snapshot plus background reconciliation;
- empty;
- live;
- stale;
- reconnecting;
- offline;
- forbidden or unauthorized where applicable;
- configuration error;
- history error with retry.

When a valid previous snapshot exists, background reconciliation must not blank the plot.

## 10. Interaction contract

### 10.1 Cursor and tooltip

Desktop and operator behavior:

- pointer movement shows one shared vertical crosshair;
- all synchronized groups inspect the same timestamp;
- each series reports the nearest valid sample and its exact timestamp;
- if no sample exists within the applicable source-cadence tolerance, show `—` instead of borrowing a distant value;
- tooltip or inspector shows value, unit, series identity, quality or freshness cue and timestamp;
- pointer activation may pin the inspector.

Keyboard operation must provide an equivalent way to move between inspectable timestamps or samples.

### 10.2 Legend

Every legend item can expose:

- series identity label;
- current or inspected value;
- unit;
- visible or hidden state;
- optional quality or freshness cue;
- show or hide control;
- solo or focus control.

Legend changes affect display only. They do not change physical acquisition.

### 10.3 Zoom, pan and reset

Rules:

- zoom is bounded to available history;
- pan does not request data outside permitted server bounds without an explicit history query;
- reset restores the selected range;
- zoom or pan from `Live` enters `Paused view`;
- synchronized plot groups share the x viewport.

### 10.4 Event selection

Event markers can be selected to expose:

- event type;
- timestamp;
- source;
- severity or status;
- associated measured context when available.

Dense events use clustering or event lanes instead of an unreadable pile of icons over the trace.

## 11. Visual language and chart tokens

The chart system extends the existing NEXOLAB Modern Industrial Tech design system.

Existing base colors are:

- background: `#06142A`;
- deep navy: `#0B1D3A`;
- steel blue: `#132E5F`;
- primary: `#0077FF`;
- cyan: `#00C6E0`;
- success: `#22C55E`;
- warning: `#F5B301`;
- danger: `#FF4D4F`;
- text primary: `#E6ECF2`.

Chart visual rules:

- primary traces use a nominal `2–2.5 px` width on desktop and operator surfaces;
- grid lines remain low-contrast and subordinate to measurements;
- axes remain readable for laboratory use rather than decorative;
- plot surfaces use the dark cold-tech system surface;
- active or hover series get stronger contrast, not excessive glow;
- critical state uses localized red accent rather than recoloring the entire chart;
- line style, marker shape, direct label or pattern supplements color where required;
- arbitrary rainbow colors generated from channel hashes are not part of the target system.

### 11.1 Ordered multi-series palette

The canonical initial palette is:

- `#00C6E0`;
- `#7ED321`;
- `#0077FF`;
- `#A855F7`;
- `#F5B301`;
- `#14B8A6`;
- `#F97316`;
- `#F43F5E`.

Implementation must validate contrast against the chart surface and pair color with non-color identity cues when needed.

Persistent Live Dashboard colors remain operator preferences but must pass an accessibility or contrast policy before save or receive an accessible fallback treatment.

## 12. Accessibility

Charts must not require color discrimination alone.

Required baseline:

- meaningful chart title or summary;
- keyboard-operable controls;
- visible focus states;
- semantic labels on time range, legend and actions;
- screen-reader-readable summary of range, series count, units, freshness and important alarms;
- structured exact-value table or inspector path where practical;
- color supplemented by label, dash, marker, status text or pattern;
- reduced-motion mode disables nonessential animated transitions;
- live updates do not announce every incoming sample through an ARIA live region.

If a renderer uses Canvas, accessibility remains an application responsibility. Renderer-provided ARIA is additive, not a replacement for NEXOLAB controls and summaries.

## 13. Responsive behavior

### 13.1 Mobile and narrow viewport

Requirements:

- no page-level horizontal overflow caused by a nominal chart canvas width;
- plot fits available width;
- controls wrap or collapse compactly;
- legend becomes collapsible or stacked;
- x-axis label density reduces instead of overlapping;
- minimum useful plot height is maintained;
- touch targets remain approximately `40 px` or greater;
- exact-value inspection supports tap and pinned-inspector behavior.

Dense eight-series comparison remains available, but the UI may encourage solo or focus mode and a collapsed legend on narrow screens.

### 13.2 Standard desktop at 1440 px

This is the primary design target.

Requirements:

- full shell controls visible;
- interactive legend visible;
- synchronized multi-plot groups readable without horizontal page scrolling;
- exact tooltip and crosshair interactions enabled.

### 13.3 Operator display at 1920 px

Requirements:

- more x-axis label density may be shown;
- more legend and statistics context may stay expanded;
- line and text size do not shrink merely because more space exists;
- the result remains readable at control-room viewing distances.

## 14. Performance and lifecycle contract

The following are provisional implementation targets, not claims about current code. They must be measured on the controlled Raspberry Pi browser and can be tightened after the first benchmark.

### 14.1 Bounded series

- common interactive multi-series plot default: maximum eight visible series, preserving the current Live Data comparison contract;
- larger dashboards split compatible series into explicit groups instead of one unreadable plot;
- compact single-series sparklines stay separately bounded.

### 14.2 Bounded points

- current accepted baseline is `240` rendered points per channel in Live Data;
- the first common primitive remains at least as strictly bounded until a benchmark justifies a larger value;
- any increase requires measured Raspberry Pi browser evidence and the evidence-preserving reducer;
- full raw history is not rendered merely because a client can temporarily handle it.

### 14.3 Provisional render targets

For an already available normalized dataset of up to eight series at the accepted point budget:

- target initial plot render after data readiness: `≤ 250 ms` p95 on the controlled Raspberry Pi browser;
- hard plot-only acceptance ceiling under normal local load: `≤ 1 s`;
- target incremental live-update work: `≤ 100 ms` p95 without full React route or panel remount;
- pointer and keyboard inspection remain perceptibly immediate and do not block navigation.

These timings isolate renderer work from backend and network latency. End-to-end route latency remains governed by the broader performance work in #356 and #289.

### 14.4 Long-lived lifecycle

Requirements:

- one renderer instance per visible plot or group;
- update an existing renderer instance rather than destroy and recreate it per telemetry sample;
- dispose renderer resources on true unmount;
- use bounded shared telemetry and history storage;
- use one resize lifecycle path;
- hidden charts do not accumulate unbounded animation or event work;
- route returns reuse valid shared telemetry snapshots and remain truthful while reconciling.

### 14.5 Physical request invariant

Browser count, chart count and visualization settings must not increase physical Modbus requests outside the existing scheduler envelope.

This is a hard acceptance gate and is finally measured under #289.

## 15. Renderer decision

### 15.1 Current state

NEXOLAB currently has no dedicated chart dependency and uses hand-authored SVG. This kept early vertical slices small but now creates duplicated scale, path, legend and state behavior across routes.

Continuing with route-local SVG alone is not recommended because the product now needs:

- synchronized cursors;
- zoom and pan;
- multiple synchronized plot groups;
- event and threshold overlays;
- responsive lifecycle management;
- Canvas-level performance headroom;
- consistent accessibility hooks;
- repeatable export behavior.

### 15.2 Preferred benchmark candidate: Apache ECharts 6.1

As of this specification date, the official Apache ECharts project advertises version 6.1 and supports:

- Canvas and SVG rendering;
- progressive rendering and stream-oriented large-data behavior;
- modular npm imports such as `echarts/core`;
- responsive charts;
- WAI-ARIA support and decal patterns;
- Apache License 2.0.

Official references reviewed on 2026-08-07:

- `https://echarts.apache.org/en/`;
- `https://echarts.apache.org/handbook/en/basics/import/`;
- `https://echarts.apache.org/handbook/en/best-practices/canvas-vs-svg/`;
- `https://echarts.apache.org/handbook/en/best-practices/aria/`.

### 15.3 NEXOLAB integration direction

If the implementation benchmark confirms ECharts:

- add an exact repository-managed npm dependency and deterministic lockfile through a separate Issue and PR;
- use local bundled modules only and never runtime CDN loading;
- prefer tree-shakable `echarts/core` imports for required components;
- start with Canvas for interactive telemetry plots where element count is material;
- keep the renderer behind a NEXOLAB-owned adapter;
- do not add a second React wrapper dependency unless a verified lifecycle gap requires it;
- keep continuity, downsampling and state logic outside renderer options;
- prevent renderer APIs from leaking into Telemetry Service or acquisition contracts.

### 15.4 Required benchmark before adoption

The separate foundation implementation Issue compares the candidate with the current custom SVG baseline using representative fixtures:

- one series with `240` points;
- eight series with `240` points;
- multiple synchronized compatible-unit groups;
- explicit gaps and alarm markers;
- incremental live-tail updates;
- resize and route remount or reuse;
- mobile or narrow viewport;
- disconnected production-bundle startup.

Record:

- bundle delta;
- initial render time;
- incremental-update time;
- memory trend;
- interaction responsiveness;
- accessibility output;
- offline and local-bundle behavior.

Adoption is not complete until those results exist.

## 16. Proposed component boundary

The implementation should converge on three layers.

Chart domain owns:

- continuity;
- evidence-preserving reduction;
- units and compatibility;
- statistics;
- chart-domain types.

Chart presentation owns:

- Chart Shell;
- legend;
- inspector;
- range control;
- operator states.

Renderer adapter owns:

- renderer initialization;
- normalized-series mapping;
- incremental updates;
- resize lifecycle;
- disposal;
- renderer-specific event translation.

Dependency direction is mandatory:

- product pages depend on chart presentation and chart domain;
- chart presentation depends on the renderer adapter;
- the renderer adapter depends on the selected third-party renderer;
- the renderer never becomes the source of NEXOLAB telemetry semantics.

## 17. Testing strategy

### 17.1 Domain unit tests

Cover at minimum:

- segment break after invalid quality;
- segment break after source gap;
- no line across offline interval;
- first and last preservation;
- min and max preservation in every reduced bucket;
- chronological order whether max occurs before min or vice versa;
- threshold-crossing preservation;
- duplicate-event identity handling;
- out-of-order live event handling;
- compatible and incompatible unit grouping;
- statistics-scope correctness.

### 17.2 Component tests

Cover at minimum:

- loading, empty, error and retry;
- stale, reconnecting and offline with last valid snapshot retained;
- legend show, hide and solo;
- range changes;
- Paused view and Return to Live;
- synchronized cursor state;
- accessible labels and keyboard controls;
- reduced-motion behavior.

### 17.3 Browser acceptance

Representative flows:

- open Live Data with multiple temperature channels;
- verify gaps remain visible;
- inspect exact values with the synchronized cursor;
- zoom and pan, then return to Live;
- interrupt WebSocket delivery and verify the last snapshot stays visible but is not labelled live;
- switch range without physical acquisition mutation;
- open Energy and compare meters for one metric;
- exercise narrow, 1440 px and 1920 px viewports;
- verify no page-level horizontal overflow;
- record renderer lifecycle and performance evidence.

### 17.4 Offline acceptance

Requirements:

- production bundle contains all required chart code locally;
- disconnected startup keeps the existing Offline Bundle contract;
- no chart script, font or required asset is requested from the public internet;
- no cloud visualization API is required.

### 17.5 Hardware boundary

Chart-domain correctness can be software-verified with deterministic telemetry fixtures.

Real Raspberry Pi acceptance is required for:

- final browser performance budgets;
- route perceived latency;
- proof that browser and chart count do not change physical Modbus request rate.

No hardware write is required or permitted.

## 18. Migration strategy

Do not replace every chart in one PR.

### WP-A — Chart domain primitives and renderer benchmark

Scope:

- segment-aware evidence-preserving reducer;
- unit grouping;
- shared chart types;
- renderer-adapter contract;
- Apache ECharts 6.1 local-bundle benchmark;
- deterministic fixture or harness only, without broad route migration.

### WP-B — Live Data migration

Scope:

- use the strongest existing telemetry history and reconciliation domain as the first production consumer;
- add common Chart Shell;
- add synchronized cursor and inspector;
- add zoom, pan and live-follow;
- preserve all #263 behavior;
- perform focused browser performance acceptance.

### WP-C — Live Dashboard migration

Scope:

- remove route-local raw-polyline continuity semantics;
- reuse common segmentation and downsampling;
- preserve saved visualization and color preferences;
- preserve selected-series-only transport.

### WP-D — Overview temperature migration

Scope:

- eliminate hashed channel colors;
- reuse common continuity;
- keep Overview concise;
- add no duplicate telemetry store or polling path.

### WP-E — Energy migration

Scope:

- reuse common shell and renderer;
- preserve energy segment semantics;
- preserve same-metric meter comparison;
- keep cumulative-energy mode gated by #201 hardware semantics.

### WP-F — Test Session event timeline

Scope:

- synchronized telemetry and event lanes;
- stage, alarm and annotation evidence;
- no inferred events.

### WP-G — Report and static chart output

Scope:

- deterministic report snapshots;
- shared style tokens;
- structured data remains the numerical evidence source.

Each child remains one Issue, one branch and one focused PR.

## 19. Explicit out of scope for the foundation

The chart foundation does not include:

- changing Modbus registers or issuing writes;
- changing polling frequency or priority;
- changing acquisition registry eligibility;
- redesigning Telemetry Service schema without a separate proven requirement;
- silently changing history retention;
- using a mandatory cloud chart service;
- using CDN-loaded renderer code or fonts;
- arbitrary user-supplied formulas or chart code;
- predictive or AI-generated values presented as measured telemetry;
- remote hardware control;
- production or site cutover.

## 20. Definition of Done for the future unified system

The unified NEXOLAB chart system is complete only when:

- all major telemetry chart surfaces consume one chart-domain continuity contract;
- gaps and quality failures are truthful everywhere;
- wide history cannot hide relevant extrema through unsafe reduction;
- units and axes are deterministic and compatible;
- cursor, tooltip, range, legend, zoom and live-follow behavior is consistent;
- temperature, energy and session-event semantics remain domain-correct;
- charts are keyboard accessible and not color-only;
- mobile, 1440 px and 1920 px layouts are accepted;
- renderer lifecycle is bounded and performant on Raspberry Pi;
- Offline Bundle works without public network resources;
- browser count does not alter the physical polling envelope;
- every migration has targeted tests, exact-head CI and evidence.

Until real Raspberry Pi browser and performance acceptance is attached, implementation completion must be reported as `software verified; Raspberry Pi chart performance/acquisition-invariant acceptance pending`.
