# Issue #400 — Live Data canonical Chart System migration audit

Date: 2026-08-11

## Scope

Issue #400 migrates the operator Live Data explorer to the canonical NEXOLAB Chart System established by Issue #386 / PR #399. It does not migrate the Saved Live Dashboard renderer.

Repository baseline before implementation:

- `main`: `61998415e334cb31555e54ae4013d938e7607b6e`
- Chart System foundation: `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`
- branch: `feat/400-live-data-chart-system`
- PR: #402

## Repository topology decision

The repository audit found that `/live` intentionally mounts the Saved Live Dashboard workspace after Issue #288, while the completed Issue #263 `LiveTelemetryExplorer` remained in the repository but was no longer mounted.

Issue #400 is explicitly distinct from Saved Live Dashboard migration. The focused solution therefore preserves the existing Saved Dashboard library/workspace and exposes the Live Data explorer as a sibling `/live` workspace. Only the Explorer chart renderer is migrated in this Work Package.

## Product behavior implemented

- `/live?workspace=explorer` exposes the Live Data explorer without removing Saved Dashboards.
- up to eight selected telemetry channels remain supported;
- route-local SVG comparison rendering is removed from the Explorer;
- canonical `ChartShell`, `ChartRendererHost` and `EChartsRendererAdapter` render the production chart;
- stable Chart Domain series identities are derived from node, equipment, channel, metric and native unit;
- measurement quality, delivery freshness and continuity remain separate concepts;
- explicit gaps remain separate chart segments;
- canonical segment-aware min/max reduction preserves first/last points, local extrema, continuity boundaries and pinned alarm transition evidence;
- compatible native units share a plot group while incompatible units receive synchronized separate groups;
- cumulative energy series retain explicit counter semantics;
- synchronized cursor and x-domain are shared across plot groups;
- show/hide and solo are renderer-independent series state;
- canonical ranges are exposed: Live, 5 min, 15 min, 1 h, 6 h, 24 h, 7 d and Custom;
- Live Follow, Pause View, Return to Live, zoom/pan and reset remain display-only;
- Custom is bounded to the existing local seven-day history contract rather than expanding backend scope;
- one persistent ECharts adapter instance is retained per mounted chart panel;
- the existing route-persistent telemetry client, stable-watermark history loading and WebSocket tail reconciliation remain authoritative.

## Acquisition and safety boundary

No Issue #400 product code changes:

- REST or WebSocket schemas;
- PostgreSQL schema;
- telemetry retention;
- Device Agent configuration;
- registry eligibility;
- adaptive scheduler priorities or intervals;
- Modbus requests or writes;
- hardware state.

No Modbus writes, hardware writes, persistent-data deletion or site cutover are part of this Work Package.

## Evidence-preserving reduction

The prior Live history reducer kept a single representative last point per bucket. Issue #400 routes Live history through the canonical Chart System reducer.

Focused tests prove:

- first and last samples survive bounded reduction;
- both short local minimum and maximum survive the same reduced window;
- communication failure creates a recovery segment rather than a connected line;
- alarm entry and recovery context remain pinned;
- delayed replay cannot close a newer pending outage;
- output remains bounded.

## Canonical chart mapping tests

Focused tests prove:

- freshness and measurement quality remain independent;
- explicit history gaps become separate Chart Domain segments;
- incompatible native units create separate synchronized plot groups;
- alarm transitions become evidence markers;
- show/hide and solo do not mutate series identity;
- cumulative energy is explicitly classified as a cumulative counter.

## Browser acceptance

A new deterministic production browser flow is included in the existing authenticated dashboard acceptance lane.

The fixture persists eight real telemetry series into the local PostgreSQL history/latest read models:

- six temperature series (`degC`);
- two voltage series (`V`).

The browser acceptance verifies:

- `/live?workspace=explorer` loads under real authentication/permissions;
- all eight channels are selectable;
- six temperature channels and two voltage channels render as two synchronized compatible-unit chart groups;
- accessible Chart Shell summaries are present;
- latest and history API requests occur;
- only one concurrent telemetry WebSocket is present for the Live workspace lifecycle;
- switching `Live Data -> Saved Dashboards -> Live Data` does not create a parallel socket;
- no acquisition/configuration mutation request is emitted;
- no public HTTP runtime request is emitted;
- show/hide, solo and reset controls operate;
- 5-minute range, Return to Live and Pause View operate;
- no page-level horizontal overflow at 360, 1440 or 1920 px;
- evidence screenshot and JSON request/socket summary are captured by CI.

The initial browser version used full-document `page.goto` navigation and incorrectly treated two sequential WebSocket lifecycles as concurrent because it asserted a cumulative maximum. The acceptance was corrected to exercise the actual sibling SPA workspace transition and assert active concurrency. The corrected browser gate is GREEN on the implementation head.

## Software verification before final state refresh

Implementation head `fb6cec76397da1dc6baf2b21c668c6b99f282bb0` produced:

- repository formatting: GREEN;
- ESLint: GREEN;
- TypeScript: GREEN;
- Vitest + lint-staged compatibility: 77 files / 344 tests GREEN;
- Next.js 16.2.12 production build: GREEN;
- Authenticated Dashboard Acceptance: GREEN, including the new Live Chart System flow and existing acquisition-invariant flow;
- Acquisition Scale Acceptance: GREEN;
- Refrigeration Browser Acceptance: GREEN.

A new exact-head verification cycle is required after this audit/state refresh. Offline Bundle must be GREEN on that exact candidate before hardware handoff/Ready classification.

## Existing Raspberry Pi baseline

Before Issue #400 candidate deployment, the Product Owner deployed `main=61998415e334cb31555e54ae4013d938e7607b6e` on the controlled Raspberry Pi in `lan` mode.

Observed baseline:

- controlled deployment: PASS;
- dashboard: active;
- Telemetry Service: healthy;
- API/database/MQTT readiness: ready;
- Device Agent: healthy;
- MQTT connected;
- queue depth: 0;
- real RS-485 telemetry advancing;
- configured/poll-eligible targets: 38;
- sampled acquisition counters: `physical_requests_total=818`, `success=657`, `timeout=161`, `retry_attempts_total=161`;
- no Modbus or hardware writes were performed.

These counters are a pre-#400 runtime baseline only; they are not yet proof of the candidate acquisition invariant.

## Hardware acceptance still required

Before Issue #400 can claim full production acceptance, run the frozen exact candidate on the controlled Raspberry Pi and record equal-duration request-rate observations for:

1. dashboard/browser idle baseline;
2. Live Data explorer open with eight channels;
3. active chart interaction (range, show/hide, solo, zoom/pan, Pause/Return Live);
4. sibling workspace transition away/back.

Acceptance requires no chart-driven change to Device Agent scheduler policy, registry eligibility or physical request cadence beyond normal scheduler variation, no Modbus writes, continued telemetry advancement and acceptable browser performance.

Until that physical test is completed, use:

`software verified; production Live Data Raspberry Pi acquisition-invariant acceptance pending`
