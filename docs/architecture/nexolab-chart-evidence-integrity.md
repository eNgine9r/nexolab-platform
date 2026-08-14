# NEXOLAB Chart Evidence Integrity Contract

Status: normative addendum to `docs/architecture/nexolab-chart-system.md` for Issue #451 / Epic #450.

This document narrows the evidence semantics of the canonical NEXOLAB Chart System. It does **not** change the current stacked compatible-unit composition policy; equipment-centric multi-axis composition is a separate Work Package under Epic #450.

## 1. Scope and invariants

The chart layer is a read-model and visualization boundary only.

Chart interactions must never:

- change physical polling cadence or priority;
- trigger Modbus reads or writes;
- mutate acquisition registry, discovery or device configuration;
- acknowledge, resolve or delete alarm/event entities;
- invent measurements between persisted samples;
- mutate raw persisted measurement precision.

All behavior in this contract must work in `LOCAL_LAN` and disconnected Offline Bundle runtime without mandatory external API, CDN, telemetry or cloud dependency.

## 2. Continuity semantics

A rendered line segment means only that NEXOLAB has consecutive valid measurements inside one continuity segment. The renderer uses `connectNulls: false` and no smoothing/interpolation across evidence gaps.

### Explicit breaks

The following source evidence always breaks continuity:

- non-valid measurement quality, including `communication_error`;
- explicit source gap marker;
- offline/reconnect boundary;
- missing/non-finite measurement;
- other canonical continuity boundary supplied by the read model.

If a canonical failure sample exists, its failure reason remains the provenance of the next segment even when recovery is much later. A later timestamp distance must not overwrite a known `communication_error`/offline/reconnect reason with a generic source-gap reason.

### Silent timestamp gaps

NEXOLAB acquisition uses different configurable cadences. Therefore chart code must not use a route-local fixed `30 s` rule as proof that data is missing.

Where cadence metadata is not present in the telemetry DTO, the read model may derive a bounded render-only tolerance from the observed series cadence to detect an otherwise silent timestamp outage. This heuristic:

- never creates a measurement;
- never changes acquisition;
- never bridges an explicit break;
- is secondary to canonical quality/failure evidence;
- must be deterministic for the same ordered source events.

Malformed timestamps and non-finite values are excluded before renderer input and are never silently treated as valid chart points.

## 3. Stable history/live reconciliation

History and live-tail events use the canonical event identity for deduplication.

For every series:

1. normalize timestamps;
2. reject malformed renderer input;
3. order deterministically by `captured_at`, then stable event identity;
4. deduplicate repeated history/WebSocket copies of the same event;
5. construct continuity segments;
6. apply bounded visualization reduction without removing mandatory endpoints/extrema/evidence boundaries;
7. keep the active segment identity stable while new live-tail samples append.

A live update must not temporarily delete or rename previously accepted points merely because the tail grew.

## 4. Shared Exact Inspector

The inspector uses one shared cursor timestamp for the chart canvas.

At each cursor timestamp NEXOLAB resolves the nearest valid sample **for every visible series**, producing one deterministic synchronized inspection snapshot.

The inspector exposes:

- shared cursor timestamp;
- series identity/name;
- nearest measured sample timestamp;
- formatted value;
- native/display unit;
- measurement quality;
- freshness state.

### Tolerance

Cursor lookup uses a bounded tolerance derived from the valid cadence of each series unless the scene provides an explicit override. This prevents a slow but healthy channel from flashing to `—` between adjacent legitimate samples.

An explicit continuity gap is a hard boundary: the inspector must not borrow a sample from either side while the cursor is inside that gap, regardless of tolerance.

If no acceptable point exists for one series, that series renders `—` while the shared cursor and other series remain stable.

## 5. Numeric presentation

Raw telemetry precision is immutable at the chart layer.

Operator-facing chart values use a centralized presentation formatter with default precision of two fraction digits, for example:

- `25.700000000000003 °C` → `25.70 °C`;
- `227.34 V` → `227.34 V`;
- `3.4 A` → `3.40 A`.

A future metric definition may override presentation precision. Route-local hard-coded precision rules are not allowed.

A value cell has mutually exclusive states:

- valid inspected value → formatted value and unit;
- unavailable inspected value → `—`.

The placeholder is never rendered underneath or together with a real value.

## 6. Alarm/event provenance

A visual event/alarm annotation is evidence and therefore requires a canonical source-domain entity.

Every `ChartEventMarker` must have at least:

- stable event ID;
- finite timestamp;
- event type;
- operator label;
- source entity ID;
- source entity type;
- severity/status where available.

The renderer deduplicates events by stable event ID.

### Prohibited synthesis

`TelemetrySample.alarm` is measurement context. It may be displayed as measurement metadata elsewhere, but **it is not by itself a canonical event entity**.

Therefore:

> no canonical event entity → no chart event/alarm annotation.

Overview, Live Data and Saved Live Dashboards must not synthesize `Alarm context …` vertical lines or alarm pins solely from transitions in `TelemetrySample.alarm`.

### Dense events

Always-visible full labels are not permitted when they can collide. The plot layer must use bounded/collision-safe presentation such as hidden default labels, grouping/count badges or detail-on-demand. Dense event rendering must remain readable and must not duplicate one event across multiple series.

## 7. Accessibility and machine-verifiable semantics

The chart accessible summary reports:

- selected range;
- number of series;
- units;
- freshness state;
- total canonical continuity-break count.

The Exact Inspector remains mounted with stable layout and a table-like semantic structure. Cursor movement must not cause the chart container or surrounding page to jump.

Color is never the only carrier of quality/freshness/event meaning.

## 8. Verification contract

Issue #451 requires evidence at four layers.

### Unit/component

Cover:

- timestamp normalization and deterministic ordering;
- event deduplication;
- cadence-aware continuity;
- explicit failure precedence;
- invalid/non-finite handling;
- shared nearest-point lookup per visible series;
- gap-safe cursor lookup;
- numeric formatting;
- canonical event validation/deduplication;
- mutually exclusive value/placeholder state.

### Production browser

The authenticated local production stack must prove:

- one known `communication_error` fixture produces one continuity break in accessible semantics;
- telemetry `alarm='high'` without a canonical event produces no `Alarm context` annotation;
- shared Exact Inspector contains all visible series and remains stable during cursor movement;
- displayed inspected/chart values use the two-decimal presentation contract;
- live-tail update preserves mounted chart renderer and does not refetch history;
- Hide/Show/Solo/zoom/Pause remain functional;
- 360/1440/1920 layouts have no page overflow;
- one bounded WebSocket path;
- zero acquisition mutations;
- zero mandatory public runtime requests.

### Offline

Disconnected Offline Bundle checks remain GREEN. No new runtime dependency may require internet access.

### Raspberry Pi

Raspberry Pi browser acceptance is recorded separately from software/browser/offline verification. Issue #451 must not claim physical acceptance until evidence is captured on the target device.

## 9. Out of scope

This contract does not authorize:

- equipment-centric multi-axis changes;
- Live Data page composition changes;
- Overview layout changes;
- hierarchical telemetry selector work;
- polling scheduler changes;
- Modbus/hardware writes;
- alarm rule-engine redesign;
- database redesign;
- dependency upgrades.
