# Issue #413 — Overview temperature canonical Chart System audit

Updated: 2026-08-12

## Status

**Software verified through a clean checkpoint; final exact-head rerun and controlled Raspberry Pi acceptance pending — Draft PR #414.**

Base `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`.

Controlled Raspberry Pi acceptance is intentionally separate from CI and remains required before Ready/merge.

## Selection evidence

Fresh repository-backed Ready audit after Issue #411 / PR #412 found:

- Issue #369 remains `status:ready`, critical and separate for Live Dashboard editor inventory/filter/select/save Raspberry Pi acceptance;
- Issue #389 remains `status:ready`, high and not selected for administrator-only local Version Management;
- no conflicting product PR is open;
- Overview still owned an independent telemetry-history SVG in `src/components/dashboard/temperature-chart.tsx`;
- that SVG filtered invalid/non-renderable samples before path construction and could visually connect valid points across a real communication/quality gap;
- Overview already has its own authenticated latest/history/WebSocket path through `useDashboardTelemetry`, so it does not depend on #369.

Product Owner Chart System priority selected #413 while preserving:

```text
#369 -> #366 -> #289
#389
```

## Product scope

The Work Package migrates only the Overview XJP60D temperature-history visualization to the canonical NEXOLAB Chart System.

Preserved behavior:

- active temperature channels remain controlled by existing XJP60D sensor management;
- live value cards remain the existing truthful valid/error cards;
- Overview keeps the existing 1h / 6h / 24h history range subset;
- history remains the existing authenticated `/telemetry/history` contract;
- latest and WebSocket delivery remain the existing Overview adapter path;
- no chart interaction changes physical acquisition.

Out of scope:

- Live Dashboard editor acceptance #369;
- backend schema or PostgreSQL migrations;
- telemetry REST/WebSocket schema changes;
- Device Agent, scheduler, registry, discovery or Modbus changes;
- dependency upgrades;
- Energy, Sessions or Reports chart migrations.

## Implementation

### Canonical mapping

`src/features/dashboard/overview-chart.ts` now:

- maps real `temperature.probe` samples into full canonical `nodeId/equipmentId/channelId/metric/nativeUnit` identities;
- deterministically groups and orders series;
- applies canonical series tokens;
- deduplicates overlapping history/live events by `event_id`;
- uses `buildChartSegments` with a 30-second maximum source gap;
- converts `sensor_error`, `communication_error`, unknown quality and missing values into explicit continuity boundaries through the canonical continuity helper;
- uses canonical `reduceChartSegments` with a 240-point target and evidence-safe fallback;
- preserves alarm transition evidence pins;
- groups only compatible exact native units;
- keeps temperature series `instantaneous`.

### Renderer migration

`src/components/dashboard/temperature-chart.tsx` no longer constructs a telemetry-history SVG path.

Overview history now uses:

- `ChartShell`;
- `ChartRendererHost`;
- local `EChartsRendererAdapter` Canvas;
- persistent non-animated live scene updates;
- shared exact cursor/inspector;
- show/hide and solo;
- zoom/pan/reset;
- canonical accessibility summary;
- requested history range as reset-domain semantics.

Live temperature cards remain separate from the canonical history plot.

### Focused unit coverage

Added mapping tests for:

- communication-error continuity break;
- > 30-second source gap;
- overlapping history/live event deduplication;
- stable identity/color order regardless of input order;
- canonical bounded reduction with extrema preservation;
- reset-domain anchoring to the newest real sample.

The pre-existing `temperature-chart` component test is intentionally isolated from ECharts browser internals by mocking the new Overview chart panel. Canvas lifecycle and browser APIs are verified in production Playwright rather than simulated as a false JSDOM renderer acceptance.

### Production browser coverage

`e2e/authenticated-dashboard.production.e2e.ts` now verifies:

- authenticated Overview renders canonical chart panel and ECharts Canvas;
- no SVG exists inside the Overview chart panel;
- 1h range change creates exactly one additional history request with exact one-hour boundaries;
- a real local MQTT `temperature.probe` point updates the live value while the same chart host and Canvas stay mounted;
- live point arrival does not trigger another history request;
- show/hide/solo remain presentation-only;
- cursor movement does not change chart host top/height or `window.scrollY`;
- zoom/pan/reset do not trigger another history request;
- 360 / 1440 / 1920 widths have no page-level horizontal overflow;
- chart interaction creates no acquisition mutation request;
- the Overview runtime makes no mandatory public-network request.

## Responsive regression found during acceptance

The first full production-browser attempt did not fail on telemetry, MQTT or Canvas continuity. Playwright trace showed the `Chart inspector` physically overlapping the legend area inside the narrow Overview chart card and intercepting pointer events intended for the `Hide` control.

Root cause:

- shared `ChartShell` switched its footer to two columns at the viewport `lg` breakpoint;
- Overview occupies only a narrower half-width content card even when the overall viewport is large enough for `lg`;
- the inspector column therefore overlaid legend controls despite the page itself having sufficient viewport width.

Focused reusable correction:

- keep the ChartShell legend and inspector stacked through ordinary desktop widths;
- enable the two-column footer only at `2xl`;
- retain the original interaction assertion and workflow timeout.

No test was weakened and no timeout was increased to make the failure disappear.

Corrective proof: Authenticated Dashboard Acceptance #1625 subsequently passed **12/12** production Playwright flows with the `Hide` interaction intact.

## Safety boundary

No backend schema, database migration, telemetry API contract, Device Agent, scheduler, registry, discovery, Modbus, hardware or dependency change is part of #413.

No Modbus write, hardware write, destructive volume/data operation or production/site cutover is permitted.

No mandatory CDN, remote font, analytics, cloud renderer, external API or paid runtime service is introduced.

## Software and offline verification

### Clean product/state checkpoint

Exact head `cb65b4b08cd0087ea6b405de72c0a16f561e7541` passed:

- **CI #2937 — GREEN**: repository formatting, zero-warning lint, strict TypeScript, full Vitest suite and production build;
- **Authenticated Dashboard Acceptance #1625 — GREEN, 12/12** production Playwright flows;
- **Refrigeration Browser Acceptance #1599 — GREEN**;
- **Offline Bundle #1008 — GREEN**, including clean transferred-host simulation, blocked container egress, disconnected startup, and update/rollback persistent-data preservation.

This is the clean software checkpoint for the completed product implementation and responsive correction.

### State checkpoint regression proof

After recording `CURRENT_STATE`, `ACTIVE_SPRINT` and `BLOCKERS`, intermediate head `f6032354e15248194c71e14c3d476705a6144a31` independently passed:

- CI #2940 — GREEN;
- Authenticated Dashboard Acceptance #1628 — GREEN;
- Refrigeration Browser Acceptance #1602 — GREEN;
- Offline Bundle #1011 — GREEN.

Thus the state checkpoint itself did not introduce a software/offline regression.

## Focused diff and review boundary

Before the final checkpoint commit:

- PR #414 remained Draft, open and mergeable;
- base remained exact `main=e89560cd2f52b59ed1c9fda4adca38e4c634a3b7` with no main drift;
- changed-file boundary remained exactly 12 files: four `.project` files, this audit, one authenticated production E2E file, the focused shared `ChartShell` compatibility fix, and five Overview mapper/component/test files;
- no `.github` workflow change remained in the PR;
- unresolved review threads: 0.

Temporary formatter-capture workflow edits used during diagnosis were restored byte-for-byte to canonical `main` and are absent from the final PR diff.

## Final freeze protocol

The final checkpoint consists only of durable state/audit documentation after the already GREEN implementation. Because embedding the final commit SHA into a file would create a self-referential extra commit, the authoritative final candidate SHA is the **PR #414 head after this audit commit**.

Before Raspberry Pi acceptance:

1. read that exact PR head from GitHub;
2. confirm `main` has not drifted;
3. confirm the same focused 12-file diff and zero unresolved review threads;
4. rerun and require GREEN canonical CI, Authenticated Dashboard, Refrigeration Browser and Offline Bundle on that exact head;
5. freeze the branch with no further commits;
6. record the exact frozen SHA and workflow evidence in the PR conversation without changing branch content.

Only then may physical acceptance start.

## Raspberry Pi acceptance still required

Controlled physical acceptance must use the exact frozen final head and one real active Overview XJP60D temperature series. It must separately prove:

1. exact candidate SHA and stable production baseline;
2. equal-duration browser-closed versus active Overview acquisition counters;
3. one exact real-series telemetry event advancing while Overview remains open;
4. existing history remains visible through a valid event or truthful `communication_error`/gap event;
5. cursor movement does not cause chart/card vertical movement or browser scroll jump;
6. zoom, pan and reset remain usable without acquisition side effects;
7. 1h / 6h / 24h range interactions remain usable;
8. route navigation away and back restores the Overview chart cleanly;
9. candidate teardown restores the production dashboard without orphan processes or restart drift.

If no exact real series event occurs during the bounded observation window, classify the physical result **INCONCLUSIVE**, not PASS or product FAIL.

CI fixtures and synthetic-only MQTT telemetry must never be represented as Raspberry Pi physical acceptance.

## Completion classification

Current classification:

```text
software verified; final exact-head rerun pending; Raspberry Pi hardware acceptance pending
```

Issue #413 remains Draft/not Ready until the final exact head is GREEN and controlled Raspberry Pi evidence passes.
