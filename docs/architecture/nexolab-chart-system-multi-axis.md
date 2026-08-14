# NEXOLAB Chart System — equipment-centric multi-axis extension

Status: accepted implementation contract for Issue #453 / PR #456  
Profile: `LOCAL_LAN`  
Scope: frontend/read-model presentation only

## Context

The canonical Chart System established by Issues #400, #404, #413 and #451 originally grouped plotted series by native unit. That boundary preserved truthful units but split one physical equipment context into separate canvases. An energy meter could therefore show Voltage (`V`), Current (`A`) and Active Power (`W`) only as independent plots even though operators inspect those measurements as one synchronized equipment state.

Issue #453 intentionally extends the canonical Chart System instead of adding a Live Data route-local exception.

## Decision

For Live Data and Saved Live Dashboards, the first chart grouping key is the physical `equipment_id`. All selected plottable series for that equipment share one time X domain. Each distinct canonical native-unit/physical-quantity group receives one deterministic Y axis.

The following invariants are mandatory:

- raw telemetry values and native units are never converted implicitly;
- every series maps to exactly one deterministic axis ID;
- axis IDs derive from the canonical physical quantity plus native unit, with the metric included only for unknown quantities;
- axis ordering is deterministic and independent of render timing;
- left/right placement and offsets derive from deterministic axis order;
- hiding the last visible series for an axis removes that axis from the rendered option;
- showing it restores the same axis identity and order;
- solo leaves only the selected series and its required axis visible;
- the renderer instance and ChartShell remain mounted across hide/show/solo and live-tail updates;
- the shared X axis, reset zoom, pause-view and exact-inspector contracts from #451 remain unchanged.

## Readability budget

One equipment scene may render at most five simultaneous Y axes. This is a presentation/readability limit, not an acquisition limit. If an equipment context contains more than five canonical axis groups, the series are deterministically partitioned into additional equipment scenes while preserving series identity, order and colors.

Different equipment contexts remain separate even when their units are compatible. NEXOLAB does not build a global multi-equipment mega-chart from this rule.

## Renderer contract

ECharts receives one `yAxis` entry per visible canonical axis and each rendered line segment receives the matching `yAxisId`. Dynamic visibility updates use `replaceMerge: ["series", "yAxis"]` so an omitted hidden axis cannot remain as stale renderer state.

No smoothing or interpolation is introduced. Canonical continuity breaks remain separate line segments, and explicit communication/quality/offline/reconnect gaps remain visually truthful.

## Accessibility contract

ChartShell exposes a non-color accessible summary based on visible series only. The summary states:

- selected time range;
- visible series count;
- visible Y-axis count;
- distinct visible native units;
- freshness state;
- visible continuity-break count.

Legend labels and Exact Inspector values remain unit-explicit. Hidden series stay keyboard-operable in the legend but do not appear as active axes or inspector rows.

## Acquisition and offline boundary

This extension is read-model/presentation only. It does not change:

- Device Agent or Modbus behavior;
- discovery/configuration endpoints;
- acquisition registry or scheduler cadence;
- telemetry persistence schema;
- REST history selection rules;
- WebSocket count;
- LOCAL_LAN/offline runtime requirements.

More visible units must not create an additional WebSocket or any acquisition/configuration mutation. No Modbus or hardware write is authorized.

## Verification

Required evidence for the Work Package is:

1. unit regression coverage for deterministic V/A/W axis identity/order, hide/show/solo and the five-axis budget;
2. Live Data and Saved Dashboard regression coverage proving equipment-centric grouping while preserving series identity/order/colors;
3. renderer regression coverage proving `yAxisId` binding, dynamic axis removal/restoration and persistent renderer lifecycle;
4. ChartShell accessibility coverage for visible-unit/axis semantics;
5. production browser acceptance with a seeded mixed-unit equipment context, shared cursor, hide/show/solo and narrow/1440/1920 overflow checks;
6. full CI, Authenticated Dashboard acquisition invariant and disconnected Offline Bundle on the exact PR head;
7. separate Raspberry Pi operator evidence classification; software verification does not imply physical hardware acceptance.
