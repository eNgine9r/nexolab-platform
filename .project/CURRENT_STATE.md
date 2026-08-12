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

Issue #404 — **Migrate Saved Live Dashboards to the canonical NEXOLAB Chart System** — remains the sole active implementation lane on `feat/404-saved-live-dashboard-chart-system`. PR #410 remains Draft and must not merge until the repeated controlled Raspberry Pi visual-continuity acceptance passes.

Implemented product scope:

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

### First controlled Raspberry Pi attempt

The exact pre-fix candidate `2b508d8a1c22ab28069c24833b792261b16193e6` built successfully on the controlled Raspberry Pi. Equal 60-second windows proved the acquisition boundary remained UI-independent:

| Metric              | Browser closed | Active Saved Dashboard |
| ------------------- | -------------: | ---------------------: |
| physical requests   |            156 |                    144 |
| physical requests/s |          2.600 |                  2.400 |
| retries             |             18 |                     12 |
| timeouts            |             24 |                     12 |
| bus executions      |            126 |                    120 |
| bus busy seconds    |         13.819 |                 10.110 |

Scheduler policy remained unchanged, configured targets remained `38 -> 38`, poll-eligible targets remained `38 -> 38`, degraded/cooldown endpoints remained `4 -> 4`, service-operation mutation counters remained empty and telemetry advanced through the active window.

Acquisition classification: **PASS**.

The operator recorded `chart_visual_continuity=FAIL`, so #404 did not pass physical acceptance and PR #410 remained Draft.

The first manual script also mixed continuous rendering with an intentional `library -> reopen` navigation inside one observation window. That intentional navigation necessarily unmounts the chart, so the repeated acceptance separates continuous live-point observation from close/reopen lifecycle verification. The original FAIL remains recorded rather than being silently reclassified.

### Operational cleanup discovered during acceptance

An orphan `next-server` from the earlier #400 temporary dashboard handoff was found holding port 3000 and causing repeated `EADDRINUSE` restarts of `nexolab-dashboard.service`. The orphan was terminated, port 3000 was released and the production service was restored to `ActiveState=active`, `SubState=running`, `NRestarts=0`, HTTP 200 before the #404 baseline. This was an acceptance-harness/runtime cleanup issue, not a #404 product-code failure.

### Corrective visual-continuity slice

The Saved Dashboard chart path now uses non-animated ECharts scene updates through the canonical host. This preserves the same mounted React host and ECharts instance while avoiding an animated full-series transition on each `refresh_seconds` rolling scene update.

The production Saved Dashboard browser acceptance now publishes a real local MQTT telemetry point and waits across the dashboard refresh interval. It verifies:

- the same `ChartRendererHost` DOM node remains mounted;
- the same ECharts Canvas DOM node remains mounted;
- Canvas remains present after the live point;
- no extra history request is triggered by that live point;
- existing dashboard/acquisition mutation, public-network and WebSocket lifecycle assertions remain enforced.

Corrective source head `67846013a8c7d357716321e2149509a2fb526f43` passed:

- CI — format, zero-warning lint, TypeScript, full tests and production build: GREEN;
- Authenticated Dashboard Acceptance with the new Saved Dashboard MQTT continuity regression: GREEN;
- Acquisition Scale Acceptance: GREEN;
- Refrigeration Browser Acceptance: GREEN;
- Offline Bundle including clean-host simulation, blocked egress, disconnected startup and update/rollback persistent-data preservation: GREEN.

A final exact-head gate is still required after this canonical checkpoint is committed. Then the new exact SHA must be re-tested on the controlled Raspberry Pi.

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

Create the final pre-hardware exact candidate after this checkpoint, run CI + Authenticated Dashboard + Acquisition Scale + Refrigeration Browser + Offline Bundle on that exact SHA, then repeat controlled Raspberry Pi acceptance in two separate phases: (1) continuous live-point observation without navigation and (2) close/reopen lifecycle. Merge only if both product behavior and acquisition invariants pass.
