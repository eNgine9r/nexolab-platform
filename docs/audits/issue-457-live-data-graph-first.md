# Issue #457 — Live Data graph-first composition

## Product boundary

Issue #457 recomposes the existing Live Data explorer around the canonical Chart System without changing telemetry acquisition, persistence, WebSocket ownership, history APIs, or hardware behavior.

The operator reading order is now:

1. Live Data identity and telemetry connection status.
2. Primary canonical chart workspace, including selected context, range controls, Pause/Return to Live, legend, Exact Inspector, and truthful chart states.
3. Search and filters.
4. Latest-values inventory and comparison selection table.

The inventory remains locally horizontally scrollable, and the page itself must remain overflow-safe at 360, 1440, and 1920 pixel viewport widths.

## Data-flow invariants

- `LiveDataWorkspace` still creates exactly one `useLiveTelemetry` model.
- Graph-first composition does not add a WebSocket or create route-local telemetry subscriptions.
- Empty comparison selection performs no history request.
- History remains bounded to selected channel identities and the selected time window.
- Search, filtering, layout, range, zoom, pause, legend, and selection presentation do not mutate acquisition, discovery, configuration, Device Agent, Modbus, or hardware state.
- No new runtime dependency, CDN, remote font, cloud service, or public network requirement is introduced.

## Regression evidence

Component coverage asserts the semantic DOM and focus order `chart → filters → inventory`, a truthful no-selection state, and locally contained table overflow.

Production Live Chart System acceptance additionally asserts:

- primary chart, filter panel, and inventory panel are visible before their relative DOM order is evaluated;
- primary chart is before filters and inventory before any channel is selected;
- no history request occurs with an empty comparison selection;
- selected context is adjacent to the chart after selection;
- history requests reference only selected channels;
- existing mixed-unit axes, Exact Inspector, continuity, live-tail, hide/show/solo, range, Pause/Return to Live, and Reset zoom behavior remains intact;
- max one WebSocket, zero acquisition/configuration mutations, and zero public runtime requests;
- graph-first vertical order and no document-level horizontal overflow at 360, 1440, and 1920 pixels.

## Hardware classification

Software/browser/offline verification does not constitute Raspberry Pi operator acceptance. Physical acceptance remains separate and pending until real-device evidence is captured.
