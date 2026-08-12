# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `f3462861db2a3593e2072a7bad70d557c009b323` — Issue #408 / PR #409 post-#406 state reconciliation merge.

## Completed — Issue #385

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`. Local users, four roles, administrator-managed permissions and offline-local authentication are software- and Raspberry-Pi-verified.

## Completed — Issue #386

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`. Canonical Chart Domain, truthful continuity, compatible-unit grouping, evidence-preserving reduction, ECharts 6.1.0 Canvas adapter, Chart Shell and renderer host are canonical.

## Completed — Issue #400

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Live Data uses the canonical Chart System. Controlled Raspberry Pi acquisition-invariant acceptance was PASS. Evidence remains at `/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`.

## Completed — Issue #406

Issue #406 / PR #407 is merged as `457923927052ed91a23f396b2285e0cfaf6096ad`. The Live Data chart-disappearance regression is fixed and protected by a real local MQTT -> browser continuity regression. Exact-head CI, Authenticated Dashboard 11/11, Refrigeration Browser and Offline Bundle were GREEN. No new physical Raspberry Pi acceptance was claimed for #406.

## Completed — Issue #408

Issue #408 / PR #409 is completed and merged as `f3462861db2a3593e2072a7bad70d557c009b323`. It reconciled #406 and selected Issue #404.

## Active Work Package — Issue #404

Issue #404 — **Migrate Saved Live Dashboards to the canonical NEXOLAB Chart System** — is the sole active implementation lane on `feat/404-saved-live-dashboard-chart-system`.

Implementation is complete at the focused software level:

- persisted Saved Dashboard `line` and `area` series map into canonical Chart Domain;
- legacy `SeriesChart` SVG is removed from the Saved Dashboard live view;
- line/area rendering uses `ChartShell`, `ChartRendererHost` and the local `EChartsRendererAdapter`;
- persisted order and saved colors remain stable;
- canonical quality/freshness/continuity separation is preserved;
- invalid-quality and >30-second source gaps break continuity instead of being bridged;
- alarm transitions pin adjacent evidence points and expose canonical event markers;
- canonical evidence-preserving reduction targets 240 points and falls back to already-bounded source history rather than deleting mandatory evidence;
- compatible exact native units share synchronized plot groups; incompatible quantities remain separate;
- `Wh`/`kWh` and energy metrics are classified as cumulative counters and are not mixed with instantaneous power semantics;
- Saved Dashboard `area` uses an optional canonical `areaFillOpacity`; existing line consumers remain unchanged;
- shared cursor, show/hide, solo, zoom/pan and Reset zoom are wired through the canonical chart path;
- persisted `dashboard.time_window` remains the reset/initial viewport;
- `refresh_seconds` remains display-only in the existing selected-series telemetry hook;
- value/gauge remain separate truthful current-value cards with no invented gauge range;
- renderer adapter lifecycle remains mount-scoped and disposed by the canonical host;
- no Saved Dashboard CRUD/version/ETag or telemetry API contract changed.

Focused tests cover persisted order/colors, line/area, unit grouping, invalid/source gaps, alarm pins, cumulative energy, hide/solo, persisted viewport and ECharts area rendering.

A production browser acceptance fixture is authored in `e2e/live.production.e2e.ts`. It creates a persisted four-item dashboard (line, area, value, gauge), deterministic bounded history and an explicit local latest projection. The flow verifies canonical Canvas rendering, no legacy SVG in the chart panel, truthful value/gauge cards, interactions, responsive widths, no dashboard/acquisition mutations, zero public runtime requests and bounded close/reopen WebSocket lifecycle.

### Verification status

Completed on the feature branch:

- touched-file Prettier: GREEN;
- TypeScript typecheck: GREEN;
- focused canonical chart and Saved Dashboard tests: GREEN;
- browser fixture code typecheck: GREEN.

Still required before Ready/merge:

- exact-head repository format/lint/typecheck/full tests/build;
- authenticated production Saved Dashboard browser acceptance on the PR head;
- existing acquisition-invariant browser gate;
- Offline Bundle;
- focused diff/review audit;
- controlled Raspberry Pi Saved Dashboard acceptance after software/offline gates are GREEN.

No Raspberry Pi #404 acceptance has been run yet and none is claimed.

## Scope boundary

Issue #404 does not change backend schema/API, database migrations, telemetry retention, polling, scheduler, registry, Device Agent, Modbus or hardware state. No dependency version changed and no mandatory public runtime dependency was added.

Issue #404 remains distinct from Issue #369:

- #404 = persisted Saved Dashboard live renderer migration;
- #369 = Raspberry Pi inventory/filter/select/save editor acceptance.

Issue #389 remains Ready/not selected. Preserved runtime sequence remains:

```text
#369 -> #366 -> #289
```

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on 2026-09-05. Issue #404 does not broaden it.

## Next action

Open the focused Issue #404 PR from the current feature branch, run exact-head CI/browser/offline gates, resolve findings without broadening scope, then perform controlled Raspberry Pi Saved Dashboard acceptance before final Ready/merge. After #404, the next Chart System migration is Overview.
