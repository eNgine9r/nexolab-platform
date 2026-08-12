# Issue #413 — Overview temperature canonical Chart System audit

Updated: 2026-08-12

## Status

**In progress — Draft PR #414.**

Base `main`: `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`.

Controlled Raspberry Pi acceptance is intentionally pending until exact-head software/browser/offline gates are GREEN.

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

## Implementation checkpoint

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
- >30-second source gap;
- overlapping history/live event deduplication;
- stable identity/color order regardless of input order;
- canonical bounded reduction with extrema preservation;
- reset-domain anchoring to the newest real sample.

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

## Safety boundary

No backend schema, database migration, telemetry API contract, Device Agent, scheduler, registry, discovery, Modbus, hardware or dependency change is part of #413.

No Modbus write, hardware write, destructive volume/data operation or production/site cutover is permitted.

No mandatory CDN, remote font, analytics, cloud renderer, external API or paid runtime service is introduced.

## Verification status

Initial Draft PR #414 implementation checkpoint started:

- CI #2920;
- Authenticated Dashboard Acceptance #1608;
- Refrigeration Browser Acceptance #1582;
- Offline Bundle #991.

These runs are not final because state/audit checkpoint commits followed the initial product commit. Final exact-head runs must be GREEN before Raspberry Pi acceptance.

## Remaining acceptance

1. Inspect/fix focused exact-head CI/browser/offline findings.
2. Confirm focused diff and no unrelated product/runtime changes.
3. Freeze a final candidate with required GREEN gates.
4. Run controlled Raspberry Pi Overview acceptance using one real plotted XJP60D temperature series.
5. Compare browser-closed versus active Overview acquisition counters.
6. Observe an exact real-series event while the chart remains visible.
7. Verify cursor stability and zoom/pan/reset on Pi.
8. Restore production cleanly with no orphan candidate.
9. Record exact hardware evidence before Ready/merge.
