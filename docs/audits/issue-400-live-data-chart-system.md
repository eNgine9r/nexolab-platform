# Issue #400 — Live Data canonical Chart System migration audit

Date: 2026-08-12

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

A deterministic production browser flow is included in the existing authenticated dashboard acceptance lane.

The fixture persists eight telemetry series into the local PostgreSQL history/latest read models:

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

The initial browser version used full-document `page.goto` navigation and incorrectly treated two sequential WebSocket lifecycles as concurrent because it asserted a cumulative maximum. The acceptance was corrected to exercise the actual sibling SPA workspace transition and assert active concurrency. The corrected browser gate is GREEN.

## Frozen software candidate

Candidate `2da08a028f54884acb74ea71cf1fac741426687b` passed the complete pre-hardware exact-head verification cycle:

- repository formatting: GREEN;
- ESLint: GREEN;
- TypeScript: GREEN;
- Vitest + lint-staged compatibility: 77 files / 344 tests GREEN;
- Next.js 16.2.12 production build: GREEN;
- Authenticated Dashboard Acceptance: GREEN, including the new Live Chart System flow and existing acquisition-invariant flow;
- Acquisition Scale Acceptance: GREEN;
- Refrigeration Browser Acceptance: GREEN;
- Offline Bundle: GREEN, including disconnected load/start plus update/rollback persistent-data preservation.

No mandatory public runtime dependency was introduced.

## Controlled Raspberry Pi acceptance

On 2026-08-12 the Product Owner tested the exact candidate `2da08a028f54884acb74ea71cf1fac741426687b` on the controlled Raspberry Pi host while keeping the existing Telemetry Service, PostgreSQL, MQTT and Device Agent runtime unchanged. Only the dashboard process was temporarily replaced, then the production dashboard service was restored.

Evidence directory retained on the host:

`/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`

The candidate production build passed on the Raspberry Pi before the runtime observation.

### Equal-duration physical request-rate comparison

Both windows were 60 seconds.

| Metric | Browser closed baseline | 8-channel active Chart System | Delta |
| --- | ---: | ---: | ---: |
| physical requests | 180 | 181 | +1 |
| physical requests/s | 3.000 | 3.017 | +0.017 (+0.56%) |
| retry attempts | 12 | 12 | 0 |
| successful requests | 168 | 169 | +1 |
| timeouts | 12 | 12 | 0 |
| bus executions | 156 | 157 | +1 |
| bus executions/s | 2.600 | 2.617 | +0.017 (+0.65%) |
| bus busy seconds | 11.928 | 11.772 | -0.156 |

During the active window the operator exercised the 8-channel Live Data chart with range changes, Hide/Show, Solo, zoom/pan, Pause View, Return to Live and the `Saved Dashboards -> Live Data` sibling workspace transition.

Acquisition invariants remained stable:

- scheduler policy unchanged in both windows;
- configured targets remained `38 -> 38`;
- poll-eligible targets remained `38 -> 38`;
- retry count remained 12 in each 60-second window;
- timeout count remained 12 in each 60-second window;
- physical request-rate difference was +0.56%, consistent with normal scheduler phase variation rather than a browser-driven polling change;
- bus busy time did not increase;
- telemetry continued advancing through the active window;
- final Telemetry Service readiness was `ready`, database `ready`, MQTT `ready`, queue size 0 and ingestion lag about 0.136 s;
- final Device Agent remained in the same pre-existing degraded condition with 3 failing/cooldown endpoints, 38 configured targets, 38 poll-eligible targets, MQTT connected and queue depth 0;
- no chart/acquisition configuration mutation was performed;
- no Modbus write or hardware write was performed;
- the production dashboard service was restored after the test.

`observed_modbus_functions=[]` in the health snapshot is not treated as proof that no Modbus reads occurred; the request counters themselves prove ongoing physical acquisition. The safety conclusion is based on the unchanged read-only product scope, unchanged scheduler/registry state, equal-duration request counters and absence of any write/configuration action.

## Acceptance conclusion

Issue #400 hardware acceptance is **PASS**.

Completion classification:

`software verified; offline runtime verified; Raspberry Pi Live Data acquisition-invariant verified; no Modbus/hardware write; ready for final exact-head state/check audit and merge`
